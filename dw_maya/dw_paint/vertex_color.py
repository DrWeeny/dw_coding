"""WeightSource wrapper for vertex color channels (RGBA).

Maya does not expose the individual channels of a colorSet as paintable
scalar maps.  This module treats each channel (red, green, blue, alpha)
of a colorSet as a standard ``WeightSource`` map so Slimfast (and any
other consumer) can read, write, smooth, remap, copy/paste, and visualise
one channel at a time without touching the other three.

Features:
    - Read/write any single channel per vertex (polyColorPerVertex).
    - Four maps per colorSet: ``alpha`` (default), ``red``, ``green``, ``blue``.
    - Preview mode: copies the active channel -> RGB on a temp colorSet for
      B&W viewport feedback.
    - Interactive artisan painting via artUserPaintCtx (paint one channel
      in real-time).
    - Compatible with apply_operation (flood, smooth, vector, radial ...).

Classes:
    VertexColorSet — WeightSource exposing a colorSet's channels as maps.

Functions:
    install_mel_procs — Register the MEL callbacks needed by artUserPaintCtx.
    create_alpha_map — Create a colorSet and flood its alpha channel.

Example::

    from dw_maya.dw_paint.vertex_color import VertexColorSet
    src = VertexColorSet('pSphere1', color_set='colorSet1')
    src.use_map('red')
    weights = src.get_weights()
    src.set_weights([w * 0.5 for w in weights])

Author: DrWeeny
"""

from __future__ import annotations
import re

from typing import List, Optional, Set

from maya import cmds
from dw_maya.dw_paint.protocol import WeightSource, WeightList
from dw_maya.dw_paint.core.mesh_data import MeshDataFactory
from dw_logger import get_logger
import numpy as np
logger = get_logger()

# Name of the temporary colorSet used for B&W preview
_PREVIEW_SET = '_channel_preview_bw'
# artUserPaintCtx context name (singleton) — must match artisan_maya.CTX_ALPHA
_CTX_NAME = 'dwAlphaPaintCtx'

# channel map name -> (polyColorPerVertex flag, MColor component index)
_CHANNELS = {
    'red':   ('r', 0),
    'green': ('g', 1),
    'blue':  ('b', 2),
    'alpha': ('a', 3),
}

# Maya returns MColor(-1,-1,-1,-1) for vertices that were never assigned a
# color — that -1 is an "unset" sentinel, not a stored value (it would
# otherwise leak into weight ranges as a negative minimum, and into sibling
# channels on write). Unset vertices read as 0.0 (empty map). Stored values
# are returned untouched — including genuine negatives / out-of-0-1 data
# (debug or HDR colorSets): getVertexColors(defaultUnsetColor) substitutes
# only truly unassigned vertices, so no clamping happens anywhere.
_UNSET_VALUE = 0.0

# ---------------------------------------------------------------------------
# MEL callback installation
# ---------------------------------------------------------------------------

_MEL_PROCS_INSTALLED = False


def install_mel_procs() -> None:
    """Register the MEL global procedures used by artUserPaintCtx.

    Based on the proven artUserPaintCtx callback pattern.  The initializeCmd
    returns ``-path 1`` so that ``setValueCommand`` receives the full shape
    path, enabling multi-shape support.
    """
    global _MEL_PROCS_INSTALLED

    from maya import mel

    # Determine the correct MEL→Python bridge command.
    try:
        mel.eval('python("1")')
        py = 'python'
    except Exception:
        py = 'python3'

    ctx = _CTX_NAME
    # MEL procs follow the reference pattern exactly:
    # The object is stored in __main__ as the context name itself.
    # MEL procs call python("contextName.method(...)").
    mel_code = f'''
        global proc string {ctx}_init_cmd(string $shape){{
            return {py}("{ctx}.init_cmd('" + $shape + "')");}}
        global proc {ctx}_on_cmd(){{
            {py}("{ctx}.on_cmd()");}}
        global proc {ctx}_off_cmd(){{
            {py}("{ctx}.off_cmd()");}}
        global proc {ctx}_before_stroke_cmd(){{
            {py}("{ctx}.before_stroke_cmd()");}}
        global proc {ctx}_set_value_cmd(int $shape_id, int $v_id, float $value, string $shape_long){{
            {py}("{ctx}.set_value_cmd(" + $shape_id + "," + $v_id + "," + $value + ",'" + $shape_long + "')");}}
        global proc {ctx}_during_stroke_cmd(){{
            {py}("{ctx}.during_stroke_cmd()");}}
        global proc {ctx}_after_stroke_cmd(){{
            {py}("{ctx}.after_stroke_cmd()");}}
        global proc {ctx}_final_cmd(string $shape){{
            {py}("{ctx}.final_cmd('" + $shape + "')");}}
    '''
    mel.eval(mel_code)
    _MEL_PROCS_INSTALLED = True

def get_icon():
    from dw_ressources import get_resource_path
    return get_resource_path("vertex_alpha_icon.png")

# ---------------------------------------------------------------------------
# Artisan paint controller — stored in __main__ for MEL access
# ---------------------------------------------------------------------------

class ChannelPaintController:
    """Manages the artisan paint session for one VertexColorSet channel.

    Stored in ``__main__`` under the context name so the MEL callbacks
    can call its methods.  Follows the same pattern as the proven
    GenericPaint reference implementation.

    The channel is captured at construction time (the source's active map);
    the whole session paints that channel only, RGB(A) siblings are preserved.
    """

    def __init__(self, source: 'VertexColorSet') -> None:
        self.source = source
        self.mesh = source.mesh_name
        self.color_set = source.color_set
        self.channel = source.channel
        self._channel_idx = _CHANNELS[self.channel][1]
        self._channel_flag = _CHANNELS[self.channel][0]

        # Read current channel values as our working buffer (numpy array for fast ops)
        self._values = np.array(source.get_weights(), dtype=np.float64)

        self._stamp_hits = {}
        self._dirty_verts = set()
        self._stroke_completed = False
        # Neighbour cache delegated to MeshDataFactory (shared, already built)
        self._neighbour_cache = {}
        self._batch_mode = False
        # Vertex selection mask — None means all vertices are paintable
        self._vtx_mask: Optional[Set[int]] = None

    def on_cmd(self) -> None:
        """Context activated — refresh channel cache."""
        self._values = np.array(self.source.get_weights(), dtype=np.float64)

    def off_cmd(self) -> None:
        """Context deactivated."""

    def before_stroke_cmd(self) -> None:
        """Click — before first stamp projection."""
        self._stamp_hits = {}
        self._stroke_completed = False
        self._vtx_mask = self._read_selection_mask()

    def _read_selection_mask(self) -> Optional[Set[int]]:
        """Read current vertex selection on this mesh.

        Returns a set of vertex indices if a component selection exists,
        or None if nothing is selected (all vertices are paintable).
        """
        sel_all = cmds.ls(sl=True, fl=True) or []
        vtx_components = [s for s in sel_all if '.' in s]
        if not vtx_components:
            return None
        vtx = cmds.polyListComponentConversion(vtx_components, toVertex=True)
        vtx = cmds.ls(vtx, fl=True) or []
        if not vtx:
            return None
        # Filter to vertices belonging to this mesh (namespace-safe)
        mesh_base = self.mesh.split('|')[-1]
        indices: Set[int] = set()
        for v in vtx:
            if mesh_base in v:
                m = re.search(r'\[(\d+)\]', v)
                if m:
                    indices.add(int(m.group(1)))
        return indices if indices else None

    def init_cmd(self, shape: str) -> str:
        """First stamp hits a shape — must return '-path 1' for artisan."""
        return '-path 1'

    def set_value_cmd(self, shape_id: int, v_id: int,
                      value: float, shape_long: str) -> None:
        """Per vertex per stamp — just accumulate, don't write to Maya yet."""
        self._stamp_hits[v_id] = value

    def during_stroke_cmd(self) -> None:
        """After each stamp during a drag — apply and flush dirty verts."""
        self._apply_stamp()
        self._flush_dirty()

    def after_stroke_cmd(self) -> None:
        """Click/drag release — mark stroke as complete for undo."""
        self._stroke_completed = True

    def final_cmd(self, shape: str = '') -> None:
        """Called on release — apply remaining stamp and flush."""
        self._apply_stamp()
        self._flush_dirty()

    def _apply_stamp(self) -> None:
        """Apply accumulated stamp hits to the in-memory channel buffer."""
        if not self._stamp_hits:
            return

        # Detect current operation mode
        oper = 'additive'
        try:
            oper = cmds.artUserPaintCtx(_CTX_NAME, q=True, selectedattroper=True)
        except Exception:
            pass

        if oper == 'smooth':
            self._apply_smooth()
            return

        artisan_value = 1.0
        try:
            artisan_value = cmds.artUserPaintCtx(_CTX_NAME, q=True, value=True)
        except Exception:
            pass

        for v_id, opacity in self._stamp_hits.items():
            if self._vtx_mask is not None and v_id not in self._vtx_mask:
                continue
            if 0 <= v_id < len(self._values):
                old = self._values[v_id]
                effective_opacity = 1.0 if (abs(artisan_value) < 1e-6 and opacity == 0.0) else opacity
                # No 0-1 clamp: colorSets can hold out-of-range data
                # (negative debug values, HDR) and painting must not eat it.
                self._values[v_id] = old + (artisan_value - old) * effective_opacity
                self._dirty_verts.add(v_id)

        self._stamp_hits.clear()

    def _apply_smooth(self) -> None:
        """Smooth the channel values for hit vertices using neighbour averaging."""
        if not self._neighbour_cache:
            self._build_neighbour_cache()

        opacity = 1.0
        try:
            opacity = cmds.artUserPaintCtx(_CTX_NAME, q=True, opacity=True)
        except Exception:
            pass

        hit_verts = list(self._stamp_hits.keys())
        # numpy copy is faster than list() for the snapshot
        snapshot = self._values.copy()

        for v_id in hit_verts:
            if self._vtx_mask is not None and v_id not in self._vtx_mask:
                continue
            if 0 <= v_id < len(self._values):
                neighbours = self._neighbour_cache.get(v_id, [])
                avg = float(np.mean(snapshot[neighbours])) if neighbours else float(snapshot[v_id])
                old = float(snapshot[v_id])
                # No 0-1 clamp — see _apply_stamp
                self._values[v_id] = old + (avg - old) * opacity
                self._dirty_verts.add(v_id)

        self._stamp_hits.clear()

    def _build_neighbour_cache(self) -> None:
        """Delegate neighbour map to MeshDataFactory (shared, cached across sessions)."""
        md = MeshDataFactory.get(self.mesh)
        cached = md.neighbors
        if cached:
            self._neighbour_cache = cached
            return

        # MeshData cache was empty (mesh not in cache yet) — build via API directly
        # and let MeshDataFactory hold it for future calls.
        import maya.api.OpenMaya as om2
        try:
            it_vtx = om2.MItMeshVertex(md._dag)
            cache = {}
            while not it_vtx.isDone():
                cache[it_vtx.index()] = list(it_vtx.getConnectedVertices())
                it_vtx.next()
            # Store back so MeshData.neighbors is populated
            md._neighbors = cache
            self._neighbour_cache = cache
        except Exception as e:
            logger.warning(f"API neighbour cache failed: {e}. Falling back to cmds.")
            n = len(self._values)
            mesh = self.mesh
            cache = {}
            for i in range(n):
                edges = cmds.polyListComponentConversion(f'{mesh}.vtx[{i}]', toEdge=True) or []
                edges = cmds.ls(edges, fl=True) or []
                neighbours = set()
                for edge in edges:
                    verts = cmds.polyListComponentConversion(edge, toVertex=True) or []
                    for v in cmds.ls(verts, fl=True) or []:
                        vid = int(v.split('[')[-1].rstrip(']'))
                        if vid != i:
                            neighbours.add(vid)
                cache[i] = list(neighbours)
            md._neighbors = cache
            self._neighbour_cache = cache

    def _flush_dirty(self) -> None:
        """Write only the changed vertices to Maya (incremental update)."""
        if not self._dirty_verts:
            return

        if self._batch_mode:
            self._dirty_verts.clear()
            return

        mesh = self.mesh
        color_set = self.color_set
        preview_active = self.source._preview_active
        dirty_list = list(self._dirty_verts)
        idx = self._channel_idx

        try:
            import maya.api.OpenMaya as om2
            fn_mesh = MeshDataFactory.get(mesh)._fn_mesh

            # Write the painted channel to the original colorSet.
            # Unset vertices read as the empty value, never the -1 sentinel.
            unset = om2.MColor((_UNSET_VALUE,) * 4)
            colors = fn_mesh.getVertexColors(color_set, unset)
            new_colors = om2.MColorArray()
            for i in dirty_list:
                c = colors[i] if i < len(colors) else unset
                rgba = [c.r, c.g, c.b, c.a]
                rgba[idx] = float(self._values[i])
                new_colors.append(om2.MColor(rgba))

            cmds.polyColorSet(mesh, currentColorSet=True, colorSet=color_set)
            fn_mesh.setVertexColors(new_colors, dirty_list)

            # Update B&W preview — query allColorSets once
            if preview_active:
                existing = cmds.polyColorSet(mesh, q=True, allColorSets=True) or []
                preview_set_exists = _PREVIEW_SET in existing
                if preview_set_exists:
                    cmds.polyColorSet(mesh, currentColorSet=True, colorSet=_PREVIEW_SET)
                    preview_colors = om2.MColorArray()
                    for i in dirty_list:
                        v = float(self._values[i])
                        preview_colors.append(om2.MColor((v, v, v, 1.0)))
                    fn_mesh.setVertexColors(preview_colors, dirty_list)
                # Restore: stay on preview set if active, else original
                target_set = _PREVIEW_SET if preview_set_exists else color_set
                cmds.polyColorSet(mesh, currentColorSet=True, colorSet=target_set)
            else:
                cmds.polyColorSet(mesh, currentColorSet=True, colorSet=color_set)

        except Exception as e:
            logger.warning(f"API flush failed, falling back to cmds. Error: {e}")

            cmds.polyColorSet(mesh, currentColorSet=True, colorSet=color_set)
            flag = self._channel_flag
            for i in dirty_list:
                cmds.polyColorPerVertex(
                    f'{mesh}.vtx[{i}]',
                    colorDisplayOption=True, representation=4,
                    **{flag: float(self._values[i])},
                )

            if preview_active:
                existing = cmds.polyColorSet(mesh, q=True, allColorSets=True) or []
                preview_set_exists = _PREVIEW_SET in existing
                if preview_set_exists:
                    cmds.polyColorSet(mesh, currentColorSet=True, colorSet=_PREVIEW_SET)
                    for i in dirty_list:
                        v = float(self._values[i])
                        cmds.polyColorPerVertex(
                            f'{mesh}.vtx[{i}]',
                            r=v, g=v, b=v, a=1.0,
                            colorDisplayOption=True, representation=4,
                        )
                target_set = _PREVIEW_SET if preview_set_exists else color_set
                cmds.polyColorSet(mesh, currentColorSet=True, colorSet=target_set)

        self._dirty_verts.clear()


class VertexColorSet(WeightSource):
    """Treat each vertex-color channel of a colorSet as a per-vertex weight map.

    Exposes four maps — ``alpha`` (default), ``red``, ``green``, ``blue`` —
    selected via :meth:`use_map`.  Writing one channel never touches the
    other three.

    Args:
        mesh_name:  Transform name of the mesh.
        color_set:  Name of the colorSet to operate on.
                    Defaults to the mesh's current colorSet.

    Example::

        node = VertexColorSet('pSphere1')
        node.get_weights()                  # alpha per vertex (default map)
        node.use_map('red').get_weights()   # red per vertex
        node.set_weights([1.0] * node.vtx_count)
    """

    def __init__(self, mesh_name: str, color_set: str = '') -> None:
        if not color_set:
            current = cmds.polyColorSet(mesh_name, q=True, currentColorSet=True) or []
            color_set = current[0] if current else 'colorSet1'
        # node_name is synthetic — there is no Maya node, we use the colorSet name
        super().__init__(f'{mesh_name}@{color_set}', mesh_name)
        self._color_set = color_set
        self._preview_active = False
        self._batch_mode = False
        # Default to alpha so pre-RGB scripts keep working without use_map()
        self._current_map = 'alpha'

    # ------------------------------------------------------------------
    # Identity helpers
    # ------------------------------------------------------------------

    @property
    def color_set(self) -> str:
        """The colorSet this source operates on."""
        return self._color_set

    @property
    def channel(self) -> str:
        """The active channel name (``red``/``green``/``blue``/``alpha``)."""
        return self._require_map()

    @property
    def vtx_count(self) -> int:
        """Vertex count via MeshDataFactory (cached, avoids cmds.polyEvaluate every call)."""
        return MeshDataFactory.get(self._mesh_name).vertex_count or cmds.polyEvaluate(self._mesh_name, vertex=True)


    # ------------------------------------------------------------------
    # WeightSource abstract interface
    # ------------------------------------------------------------------

    def available_maps(self) -> List[str]:
        """One map per channel — alpha first (the historical default)."""
        return ['alpha', 'red', 'green', 'blue']

    def get_artisan_name(self) -> str:
        """This source paints through ``artUserPaintCtx``, not ``artAttrContext``."""
        return _CTX_NAME

    def _resolve_attr(self, map_name: str) -> str:
        # Not used — we override get/set directly.
        return ''

    def _paint(self) -> None:
        """Open an interactive artisan brush that paints only the active channel.

        Uses ``artUserPaintCtx`` with the proven callback pattern:
        initializeCmd returns ``-path 1``, setValueCommand receives per-vertex
        opacity, and finalizeCmd flushes changes to the real colorSet.
        """
        import __main__

        # 1. Install MEL procs
        install_mel_procs()

        # 2. Create controller and store in __main__ under context name
        controller = ChannelPaintController(self)
        __main__.__dict__[_CTX_NAME] = controller

        # 3. Ensure the correct colorSet is active
        cmds.polyColorSet(self._mesh_name, currentColorSet=True,
                          colorSet=self._color_set)

        # 4. Create context if it doesn't exist
        if not cmds.artUserPaintCtx(_CTX_NAME, query=True, exists=True):
            cmds.artUserPaintCtx(_CTX_NAME)

        # 5. Configure the context with all callbacks
        cmds.artUserPaintCtx(
            _CTX_NAME,
            edit=True,
            value=0,
            opacity=1.0,
            radius=5,
            fullpaths=True,
            accopacity=False,
            stampProfile='solid',
            selectedattroper='absolute',
            wst='userPaint',
            image1=get_icon(),
            initializeCmd=f'{_CTX_NAME}_init_cmd',
            toolOnProc=f'{_CTX_NAME}_on_cmd',
            toolOffProc=f'{_CTX_NAME}_off_cmd',
            beforeStrokeCmd=f'{_CTX_NAME}_before_stroke_cmd',
            setValueCommand=f'{_CTX_NAME}_set_value_cmd',
            duringStrokeCmd=f'{_CTX_NAME}_during_stroke_cmd',
            afterStrokeCmd=f'{_CTX_NAME}_after_stroke_cmd',
            finalizeCmd=f'{_CTX_NAME}_final_cmd',
        )

        # 6. Select the mesh and activate the context
        cmds.select(self._mesh_name, replace=True)
        cmds.setToolTo(_CTX_NAME)

        logger.info(f"Paint brush active on '{self._color_set}' channel '{self.channel}'.")

    # ------------------------------------------------------------------
    # get / set weights — active channel only
    # ------------------------------------------------------------------

    def get_weights(self) -> WeightList:
        """Read the active channel's per-vertex values from the colorSet.

        Unset vertices (Maya's -1 sentinel) read as ``_UNSET_VALUE`` (0.0).
        """
        n = self.vtx_count
        flag, idx = _CHANNELS[self.channel]
        values = [_UNSET_VALUE] * n

        try:
            import maya.api.OpenMaya as om2
            fn_mesh = MeshDataFactory.get(self._mesh_name)._fn_mesh
            colors = fn_mesh.getVertexColors(self._color_set,
                                             om2.MColor((_UNSET_VALUE,) * 4))
            if len(colors) == n:
                return [c[idx] for c in colors]
        except Exception as e:
            logger.warning(f"API get_weights failed: {e}. Falling back to cmds.")

        # Ensure we read from the real colorSet, not the B&W preview
        cmds.polyColorSet(self._mesh_name, currentColorSet=True, colorSet=self._color_set)

        try:
            raw = cmds.polyColorPerVertex(
                f'{self._mesh_name}.vtx[0:{n - 1}]',
                query=True, colorDisplayOption=True,
                **{flag: True}
            ) or []
            if len(raw) == n:
                values = [float(v) for v in raw]
            elif raw:
                values = self._face_vertex_to_vertex(raw, n)
            # No sentinel mapping here: cmds cannot tell an unset vertex from
            # a stored -1, and stored negatives must be preserved (the API
            # path above is the primary one and does distinguish them).
        except Exception as e:
            logger.warning(f"get_weights '{self.channel}' failed: {e}")

        return values

    def set_weights(self, weights: WeightList, **kwargs) -> None:
        """Write the active channel per vertex, leaving the other channels untouched.

        Args:
            weights: One float per vertex.
            **kwargs:
                id_group (bool): If True, group identical weight values to optimize cmds calls.
                maya_api (bool): If True, use OpenMaya API for best performance (default).
                decimals (int): When using id_group, round weights to this many decimals to improve grouping.

        Raises:
            ValueError: If length does not match vtx_count.
        """
        id_group = kwargs.get('id_group', False)
        maya_api = kwargs.get('maya_api', True)
        decimals = kwargs.get('decimals', 3)

        n = self.vtx_count
        if len(weights) != n:
            raise ValueError(
                f"Weight count {len(weights)} != vertex count {n} "
                f"on '{self.node_name}'"
            )

        flag = _CHANNELS[self.channel][0]

        cmds.polyColorSet(self._mesh_name, currentColorSet=True,
                          colorSet=self._color_set)

        # Batch write: use OpenMaya MFnMesh for speed when available
        try:
            if not maya_api:
                raise RuntimeError("maya_api is False, falling back to cmds.")
            self._set_weights_api(weights)
        except Exception as e:
            if maya_api:
                logger.warning(f"OpenMaya API failed, falling back to cmds. Error: {e}")

            # Fallback to cmds per-vertex
            if id_group:
                from dw_maya.dw_maya_utils.dw_maya_components import create_maya_ranges
                from collections import defaultdict

                weight_groups = defaultdict(list)
                for i, w in enumerate(weights):
                    weight_groups[round(w, decimals)].append(i)

                for w_val, indices in weight_groups.items():
                    ranges = create_maya_ranges(indices)
                    for r in ranges:
                        cmds.polyColorPerVertex(
                            f'{self._mesh_name}.vtx[{r}]',
                            colorDisplayOption=True,
                            representation=4,
                            **{flag: float(w_val)},
                        )
            else:
                for i, w in enumerate(weights):
                    cmds.polyColorPerVertex(
                        f'{self._mesh_name}.vtx[{i}]',
                        colorDisplayOption=True,
                        representation=4,
                        **{flag: float(w)},
                    )

        # Refresh preview if active (skip during batch mode)
        if self._preview_active and not self._batch_mode:
            self._update_preview(weights)

        # Sync artisan controller if active
        self._sync_artisan_controller(weights)

    def _set_weights_api(self, weights: WeightList) -> None:
        """Write the active channel using OpenMaya API for better performance."""
        import maya.api.OpenMaya as om2

        fn_mesh = MeshDataFactory.get(self._mesh_name)._fn_mesh
        color_set = self._color_set
        idx = _CHANNELS[self.channel][1]
        unset = om2.MColor((_UNSET_VALUE,) * 4)
        try:
            colors = fn_mesh.getVertexColors(color_set, unset)
        except Exception:
            raise RuntimeError("No existing color data — fallback to cmds")

        n = len(weights)
        vertex_list = list(range(n))
        new_colors = om2.MColorArray()
        for i in range(n):
            c = colors[i] if i < len(colors) else unset
            rgba = [c.r, c.g, c.b, c.a]
            rgba[idx] = float(weights[i])
            new_colors.append(om2.MColor(rgba))

        fn_mesh.setVertexColors(new_colors, vertex_list)

    def _sync_artisan_controller(self, weights: WeightList) -> None:
        """Update the artisan paint controller cache if it targets this channel."""
        import __main__
        controller = __main__.__dict__.get(_CTX_NAME)
        if controller and isinstance(controller, ChannelPaintController):
            if controller.source is self and controller.channel == self.channel:
                controller._values = np.array(weights, dtype=np.float64)

    # ------------------------------------------------------------------
    # Channel preview — B&W visualisation
    # ------------------------------------------------------------------

    def enable_preview(self) -> None:
        """Create a temp colorSet where R=G=B=<active channel> and display it.

        The mesh's ``displayColors`` attribute is turned on so the viewport
        shows the active channel as a greyscale image.
        """
        values = self.get_weights()

        # Ensure the preview colorSet exists
        existing = cmds.polyColorSet(self._mesh_name, q=True, allColorSets=True) or []
        if _PREVIEW_SET not in existing:
            cmds.polyColorSet(self._mesh_name, create=True, colorSet=_PREVIEW_SET,
                              representation='RGBA')

        cmds.polyColorSet(self._mesh_name, currentColorSet=True,
                          colorSet=_PREVIEW_SET)

        self._update_preview(values)

        cmds.setAttr(f'{self._mesh_name}.displayColors', 1)
        self._preview_active = True
        logger.info(f"Channel preview enabled on '{self._mesh_name}' ({self.channel}).")

    def disable_preview(self) -> None:
        """Remove the temp colorSet and restore the original display."""
        existing = cmds.polyColorSet(self._mesh_name, q=True, allColorSets=True) or []
        if _PREVIEW_SET in existing:
            cmds.polyColorSet(self._mesh_name, delete=True, colorSet=_PREVIEW_SET)

        # Restore original colorSet
        cmds.polyColorSet(self._mesh_name, currentColorSet=True,
                          colorSet=self._color_set)
        self._preview_active = False
        logger.info(f"Channel preview disabled on '{self._mesh_name}'.")

    def _update_preview(self, values: WeightList) -> None:
        """Refresh the preview colorSet with current channel values."""
        n = len(values)
        existing = cmds.polyColorSet(self._mesh_name, q=True, allColorSets=True) or []
        if _PREVIEW_SET not in existing:
            return

        cmds.polyColorSet(self._mesh_name, currentColorSet=True, colorSet=_PREVIEW_SET)

        try:
            import maya.api.OpenMaya as om2
            fn_mesh = MeshDataFactory.get(self._mesh_name)._fn_mesh
            colors = om2.MColorArray()
            vertex_list = list(range(n))
            for i in range(n):
                v = float(values[i])
                colors.append(om2.MColor((v, v, v, 1.0)))
            fn_mesh.setVertexColors(colors, vertex_list)
        except Exception:
            for i, a in enumerate(values):
                v = float(a)
                cmds.polyColorPerVertex(
                    f'{self._mesh_name}.vtx[{i}]',
                    r=v, g=v, b=v, a=1.0,
                    colorDisplayOption=True, representation=4,
                )
    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _face_vertex_to_vertex(self, fv_values: list, n: int) -> WeightList:
        """Average per-face-vertex channel values to per-vertex."""
        accum = [0.0] * n
        counts = [0] * n
        # Build a vtx-to-faceVertex mapping
        for i in range(n):
            faces = cmds.polyListComponentConversion(
                f'{self._mesh_name}.vtx[{i}]', toVertexFace=True
            ) or []
            faces = cmds.ls(faces, fl=True) or []
            for _ in faces:
                if i < len(fv_values):
                    accum[i] += fv_values[i]
                    counts[i] += 1
        result = []
        for i in range(n):
            if counts[i] > 0:
                result.append(accum[i] / counts[i])
            else:
                result.append(1.0)
        return result


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def create_alpha_map(mesh: str, color_set: str = '', default_value: float = 0.0) -> 'VertexColorSet':
    """Create a new colorSet on *mesh* and fill its alpha with *default_value*.

    Args:
        mesh:          Transform or shape name.
        color_set:     Name for the new colorSet.  Defaults to ``'alphaMap'``.
        default_value: Initial alpha value for all vertices (0.0 = black).

    Returns:
        A ready-to-use :class:`VertexColorSet` instance (alpha map active).
    """
    if not color_set:
        color_set = 'alphaMap'

    # Resolve to transform
    if cmds.objectType(mesh) == 'mesh':
        parents = cmds.listRelatives(mesh, parent=True, fullPath=True) or [mesh]
        mesh = parents[0]

    # Create the colorSet if it doesn't exist
    existing = cmds.polyColorSet(mesh, q=True, allColorSets=True) or []
    if color_set not in existing:
        cmds.polyColorSet(mesh, create=True, colorSet=color_set, representation='RGBA')
        logger.info(f"Created colorSet '{color_set}' on '{mesh}'.")
    else:
        logger.info(f"ColorSet '{color_set}' already exists on '{mesh}', reusing.")

    source = VertexColorSet(mesh, color_set=color_set)
    n = source.vtx_count
    source.use_map('alpha').set_weights([float(default_value)] * n)
    return source