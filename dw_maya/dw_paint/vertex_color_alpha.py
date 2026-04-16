"""WeightSource wrapper for vertex color alpha channel.

Maya does not expose the alpha channel of a colorSet as a paintable scalar
map.  This module treats the alpha values as a standard ``WeightSource``
so bq_slimfast (and any other consumer) can read, write, smooth, remap,
copy/paste, and visualise the alpha without touching the RGB channels.

Features:
    - Read/write alpha per vertex (polyColorPerVertex).
    - Preview mode: copies alpha → RGB on a temp colorSet for B&W viewport feedback.
    - Interactive artisan painting via artUserPaintCtx (paint alpha in real-time).
    - Compatible with apply_operation (flood, smooth, vector, radial …).

Classes:
    VertexColorAlpha — WeightSource for vertex color alpha.

Functions:
    install_mel_procs — Register the MEL callbacks needed by artUserPaintCtx.

Example::

    from dw_maya.dw_paint.vertex_color_alpha import VertexColorAlpha
    src = VertexColorAlpha('pSphere1', color_set='colorSet1')
    src.use_map('alpha')
    weights = src.get_weights()
    src.set_weights([w * 0.5 for w in weights])

Author: DrWeeny
"""

from __future__ import annotations

from typing import List

from maya import cmds

from dw_maya.dw_paint.protocol import WeightSource, WeightList
from dw_logger import get_logger

logger = get_logger()

# Name of the temporary colorSet used for B&W preview
_PREVIEW_SET = '_alpha_preview_bw'
# artUserPaintCtx context name (singleton)
_CTX_NAME = 'dwAlphaPaintCtx'

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


# ---------------------------------------------------------------------------
# Artisan paint controller — stored in __main__ for MEL access
# ---------------------------------------------------------------------------

class AlphaPaintController:
    """Manages the artisan paint session for a VertexColorAlpha source.

    Stored in ``__main__`` as ``dwAlphaPaintCtx_obj`` so the MEL callbacks
    can call its methods.  Follows the same pattern as the proven
    GenericPaint reference implementation.
    """

    def __init__(self, source: 'VertexColorAlpha') -> None:
        self.source = source
        self.mesh = source.mesh_name
        self.color_set = source.color_set

        # Read current alpha values as our working buffer
        self._alphas = source.get_weights()

        # Per-stamp accumulator: {vertex_id: opacity}
        self._stamp_hits = {}
        # Vertices changed since last flush — for incremental updates
        self._dirty_verts = set()
        self._stroke_completed = False
        # Neighbour cache for smooth: {v_id: [neighbour_ids]}
        self._neighbour_cache = {}

    def on_cmd(self) -> None:
        """Context activated — refresh alpha cache."""
        self._alphas = self.source.get_weights()

    def off_cmd(self) -> None:
        """Context deactivated."""

    def before_stroke_cmd(self) -> None:
        """Click — before first stamp projection."""
        self._stamp_hits = {}
        self._stroke_completed = False

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
        """Apply accumulated stamp hits to the in-memory alpha buffer."""
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
            if 0 <= v_id < len(self._alphas):
                old = self._alphas[v_id]
                if abs(artisan_value) < 1e-6:
                    effective_opacity = 1.0 if opacity == 0.0 else opacity
                else:
                    effective_opacity = opacity
                new = old + (artisan_value - old) * effective_opacity
                self._alphas[v_id] = max(0.0, min(1.0, new))
                self._dirty_verts.add(v_id)

        self._stamp_hits.clear()

    def _apply_smooth(self) -> None:
        """Smooth the alpha values for hit vertices using neighbour averaging."""
        if not self._neighbour_cache:
            self._build_neighbour_cache()

        opacity = 1.0
        try:
            opacity = cmds.artUserPaintCtx(_CTX_NAME, q=True, opacity=True)
        except Exception:
            pass

        hit_verts = list(self._stamp_hits.keys())
        # Snapshot current values so smoothing reads from unmodified data
        snapshot = list(self._alphas)

        for v_id in hit_verts:
            if 0 <= v_id < len(self._alphas):
                neighbours = self._neighbour_cache.get(v_id, [])
                if neighbours:
                    avg = sum(snapshot[n] for n in neighbours) / len(neighbours)
                else:
                    avg = snapshot[v_id]
                old = snapshot[v_id]
                new = old + (avg - old) * opacity
                self._alphas[v_id] = max(0.0, min(1.0, new))
                self._dirty_verts.add(v_id)

        self._stamp_hits.clear()

    def _build_neighbour_cache(self) -> None:
        """Build a per-vertex neighbour map using polyInfo edgeToVertex."""
        n = len(self._alphas)
        mesh = self.mesh
        cache = {}
        for i in range(n):
            edges = cmds.polyListComponentConversion(
                f'{mesh}.vtx[{i}]', toEdge=True
            ) or []
            edges = cmds.ls(edges, fl=True) or []
            neighbours = set()
            for e in edges:
                verts = cmds.polyListComponentConversion(e, toVertex=True) or []
                verts = cmds.ls(verts, fl=True) or []
                for v in verts:
                    # Extract vertex id from 'mesh.vtx[id]'
                    vid = int(v.split('[')[-1].rstrip(']'))
                    if vid != i:
                        neighbours.add(vid)
            cache[i] = list(neighbours)
        self._neighbour_cache = cache

    def _flush_dirty(self) -> None:
        """Write only the changed vertices to Maya (incremental update)."""
        if not self._dirty_verts:
            return

        mesh = self.mesh
        color_set = self.color_set
        preview_active = self.source._preview_active

        # Write alpha to the original colorSet
        cmds.polyColorSet(mesh, currentColorSet=True, colorSet=color_set)
        for i in self._dirty_verts:
            cmds.polyColorPerVertex(
                f'{mesh}.vtx[{i}]',
                a=float(self._alphas[i]),
                colorDisplayOption=True, representation=4,
            )

        # Update B&W preview if active
        if preview_active:
            existing = cmds.polyColorSet(mesh, q=True, allColorSets=True) or []
            if _PREVIEW_SET in existing:
                cmds.polyColorSet(mesh, currentColorSet=True, colorSet=_PREVIEW_SET)
                for i in self._dirty_verts:
                    v = float(self._alphas[i])
                    cmds.polyColorPerVertex(
                        f'{mesh}.vtx[{i}]',
                        r=v, g=v, b=v, a=1.0,
                        colorDisplayOption=True, representation=4,
                    )

        count = len(self._dirty_verts)
        self._dirty_verts.clear()


class VertexColorAlpha(WeightSource):
    """Treat vertex-color alpha as a per-vertex weight map.

    Args:
        mesh_name:  Transform name of the mesh.
        color_set:  Name of the colorSet to operate on.
                    Defaults to the mesh's current colorSet.

    Example::

        node = VertexColorAlpha('pSphere1')
        node.get_weights()          # alpha per vertex
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

    # ------------------------------------------------------------------
    # Identity helpers
    # ------------------------------------------------------------------

    @property
    def color_set(self) -> str:
        """The colorSet this source operates on."""
        return self._color_set

    @property
    def vtx_count(self) -> int:
        return cmds.polyEvaluate(self._mesh_name, vertex=True)

    # ------------------------------------------------------------------
    # WeightSource abstract interface
    # ------------------------------------------------------------------

    def available_maps(self) -> List[str]:
        """Only one map: ``'alpha'``."""
        return ['alpha']

    def _resolve_attr(self, map_name: str) -> str:
        # Not used — we override get/set directly.
        return ''

    def paint(self) -> None:
        """Open an interactive artisan brush that paints only the alpha channel.

        Uses ``artUserPaintCtx`` with the proven callback pattern:
        initializeCmd returns ``-path 1``, setValueCommand receives per-vertex
        opacity, and finalizeCmd flushes changes to the real colorSet.
        """
        import __main__

        # 1. Install MEL procs
        install_mel_procs()

        # 2. Create controller and store in __main__ under context name
        controller = AlphaPaintController(self)
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
            value=1.0,
            opacity=1.0,
            fullpaths=True,
            accopacity=False,
            stampProfile='gaussian',
            selectedattroper='additive',
            wst='userPaint',
            image1='userPaint.png',
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

        logger.info(f"Alpha paint brush active on '{self._color_set}'.")

    # ------------------------------------------------------------------
    # get / set weights — alpha channel only
    # ------------------------------------------------------------------

    def get_weights(self) -> WeightList:
        """Read per-vertex alpha values from the colorSet.

        Returns:
            List of floats (one per vertex), range [0, 1].
        """
        n = self.vtx_count
        alphas = [1.0] * n

        try:
            colors = cmds.polyColorPerVertex(
                f'{self._mesh_name}.vtx[0:{n - 1}]',
                query=True, a=True,
                colorDisplayOption=True
            ) or []
            if len(colors) == n:
                alphas = [float(a) for a in colors]
            elif colors:
                # Maya sometimes returns per-face-vertex — average to per-vertex
                alphas = self._face_vertex_to_vertex(colors, n)
        except Exception as e:
            logger.warning(f"get_weights alpha failed: {e}")

        return alphas

    def set_weights(self, weights: WeightList) -> None:
        """Write per-vertex alpha values, leaving RGB untouched.

        Args:
            weights: One float per vertex.

        Raises:
            ValueError: If length does not match vtx_count.
        """
        n = self.vtx_count
        if len(weights) != n:
            raise ValueError(
                f"Weight count {len(weights)} != vertex count {n} "
                f"on '{self.node_name}'"
            )

        cmds.polyColorSet(self._mesh_name, currentColorSet=True,
                          colorSet=self._color_set)

        for i, a in enumerate(weights):
            cmds.polyColorPerVertex(
                f'{self._mesh_name}.vtx[{i}]',
                a=float(a),
                colorDisplayOption=True,
                representation=4,  # RGBA
            )

        # Refresh preview if active
        if self._preview_active:
            self._update_preview(weights)

    # ------------------------------------------------------------------
    # Alpha preview — B&W visualisation
    # ------------------------------------------------------------------

    def enable_preview(self) -> None:
        """Create a temp colorSet where R=G=B=alpha and display it.

        The mesh's ``displayColors`` attribute is turned on so the viewport
        shows the alpha channel as a greyscale image.
        """
        n = self.vtx_count
        alphas = self.get_weights()

        # Ensure the preview colorSet exists
        existing = cmds.polyColorSet(self._mesh_name, q=True, allColorSets=True) or []
        if _PREVIEW_SET not in existing:
            cmds.polyColorSet(self._mesh_name, create=True, colorSet=_PREVIEW_SET,
                              representation='RGBA')

        cmds.polyColorSet(self._mesh_name, currentColorSet=True,
                          colorSet=_PREVIEW_SET)

        self._update_preview(alphas)

        cmds.setAttr(f'{self._mesh_name}.displayColors', 1)
        self._preview_active = True
        logger.info(f"Alpha preview enabled on '{self._mesh_name}'.")

    def disable_preview(self) -> None:
        """Remove the temp colorSet and restore the original display."""
        existing = cmds.polyColorSet(self._mesh_name, q=True, allColorSets=True) or []
        if _PREVIEW_SET in existing:
            cmds.polyColorSet(self._mesh_name, delete=True, colorSet=_PREVIEW_SET)

        # Restore original colorSet
        cmds.polyColorSet(self._mesh_name, currentColorSet=True,
                          colorSet=self._color_set)
        self._preview_active = False
        logger.info(f"Alpha preview disabled on '{self._mesh_name}'.")

    def _update_preview(self, alphas: WeightList) -> None:
        """Refresh the preview colorSet with current alpha values."""
        n = len(alphas)
        existing = cmds.polyColorSet(self._mesh_name, q=True, allColorSets=True) or []
        if _PREVIEW_SET not in existing:
            return

        cmds.polyColorSet(self._mesh_name, currentColorSet=True,
                          colorSet=_PREVIEW_SET)

        for i, a in enumerate(alphas):
            v = float(a)
            cmds.polyColorPerVertex(
                f'{self._mesh_name}.vtx[{i}]',
                r=v, g=v, b=v, a=1.0,
                colorDisplayOption=True,
                representation=4,
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _face_vertex_to_vertex(self, fv_values: list, n: int) -> WeightList:
        """Average per-face-vertex alpha values to per-vertex."""
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

def create_alpha_map(mesh: str, color_set: str = '', default_value: float = 0.0) -> 'VertexColorAlpha':
    """Create a new colorSet on *mesh* and fill its alpha with *default_value*.

    Args:
        mesh:          Transform or shape name.
        color_set:     Name for the new colorSet.  Defaults to ``'alphaMap'``.
        default_value: Initial alpha value for all vertices (0.0 = black).

    Returns:
        A ready-to-use :class:`VertexColorAlpha` instance.
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

    source = VertexColorAlpha(mesh, color_set=color_set)
    n = source.vtx_count
    source.set_weights([float(default_value)] * n)
    return source

