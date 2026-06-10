from maya import cmds, mel
from typing import List, Optional, Tuple

from dw_maya.dw_decorators.dw_keep_selection import keep_selection
from dw_maya.dw_decorators import singleUndoChunk, timeIt
from dw_maya.dw_paint.weight_source import (
    resolve_weight_sources,
    paint_weight_source,
    apply_operation,
)

import dw_maya.dw_maya_utils
from dw_maya.dw_paint.artisan_maya import (
    CTX_ALPHA,
    get_artisan_clamp as _artisan_get_clamp,
    set_artisan_clamp as _artisan_set_clamp,
    set_artisan_color_range as _artisan_set_color_range,
    set_artisan_value as _artisan_set_value,
    flood_smooth_vtx_map,
)
from dw_maya.dw_nucleus_utils import NClothMap
from dw_maya.dw_maya_utils.dw_maya_components import extract_id, select_border, select_border_recursive
from dw_maya.dw_paint.protocol import WeightSource
from dw_logger import get_logger

logger = get_logger()

import traceback


# ---------------------------------------------------------------------------
# Controller — all Maya logic, zero PySide6
# ---------------------------------------------------------------------------

class SlimfastController:
    """Encapsulates all Maya logic for the Slimfast tool.

    The UI only calls methods on this controller and connects to its
    signals — it never imports cmds or calls Maya directly.

    Args:
        signals: A QObject subclass that carries Qt signals (injected by
                 SlimfastWidget so we stay decoupled from PySide6 here).
    """

    def __init__(self, signals: 'SlimfastSignals'):
        self._signals = signals
        self._sources: List[WeightSource] = []
        self._active: Optional[WeightSource] = None
        self._active_map: Optional[str] = None
        self._clipboard: Optional[List[float]] = None
        self._mesh: Optional[str] = None
        self._mode: str = 'all'

        # Artisan clamp state — kept in sync with set_artisan_clamp so that
        # bulk numpy operations (flood, smooth) can apply the same limits.
        self._clamp_mode: str = 'none'   # 'none' | 'lower' | 'upper' | 'both'
        self._clamp_lower: float = 0.0
        self._clamp_upper: float = 1.0

        # optimisation for live slider selection
        self._live_selection_cache = None
        self._cached_weights = None
        self._cached_mesh = None

    # ------------------------------------------------------------------
    # Source / map management
    # ------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        """Switch between 'deformer', 'nucleus', and 'all' backends."""
        self._mode = mode
        self.refresh()

    def refresh(self) -> None:
        """Re-resolve weight sources from the current Maya selection."""
        sel = cmds.filterExpand(selectionMask=[12, 31, 32, 34]) or []
        if not sel:
            self._sources = []
            self._active = None
            self._active_map = None
            self._mesh = None
            self._signals.sources_changed.emit([], [])
            logger.warning("Select a polyMesh and refresh.")
            return

        mesh = sel[0].split('.')[0]
        self._mesh = mesh

        try:
            self._sources = resolve_weight_sources(mesh, mode=self._mode)
        except Exception as e:
            logger.error(f"Failed to resolve weight sources for '{mesh}': {e}")
            self._sources = []

        node_labels = [self._source_label(s) for s in self._sources]
        map_lists = [s.available_maps() for s in self._sources]
        self._signals.sources_changed.emit(node_labels, map_lists)
        self._signals.mesh_changed.emit(mesh)

        if self._sources:
            self.select_source(0)
        else:
            self._active = None
            self._active_map = None
            self._signals.active_changed.emit(None)

    def select_source(self, index: int) -> None:
        """Set the active WeightSource by list index and auto-select its first map."""
        if 0 <= index < len(self._sources):
            self._active = self._sources[index]
            maps = self._active.available_maps()
            if maps:
                self.select_map(maps[0])
            else:
                self._active_map = None
                self._signals.active_changed.emit(self._active)
        else:
            self._active = None
            self._active_map = None
            self._signals.active_changed.emit(None)

    def select_map(self, map_name: str) -> None:
        """Activate a map on the current source node."""
        if self._active is None:
            return
        try:
            self._active.use_map(map_name)
            self._active_map = map_name
            self._signals.active_changed.emit(self._active)
        except ValueError as e:
            logger.warning(str(e))

    def _source_label(self, source: WeightSource) -> str:
        """Human-readable label for a WeightSource node."""
        from dw_maya.dw_paint.vertex_color_alpha import VertexColorAlpha
        if isinstance(source, VertexColorAlpha):
            return f"[vtxColor] {source.color_set}"
        try:
            node_type = cmds.nodeType(source.node_name)
        except Exception:
            node_type = '?'
        return f"[{node_type}] {source.node_name}"

    def _require_active(self) -> bool:
        if self._active is None or self._active_map is None:
            logger.warning("No weight source / map selected — refresh the list.")
            return False
        return True

    @property
    def active_source(self) -> Optional[WeightSource]:
        """The currently active WeightSource, or None."""
        return self._active

    @property
    def active_map(self) -> Optional[str]:
        """The currently active map name, or None."""
        return self._active_map

    # ------------------------------------------------------------------
    # Weight operations — all uniform, no type branching
    # ------------------------------------------------------------------

    def paint(self) -> None:
        """Open artisan for the active source and map.

        Face and edge selections are automatically converted to vertices
        before the artisan tool opens, so the user can make a face selection
        and click Paint without an extra step.
        """
        if not self._require_active():
            return
        try:
            self._convert_selection_to_vtx()
            self._active.paint()
        except Exception as e:
            logger.error(f"Paint failed: {e}")

    def _resolve_paint_ctx(self) -> Optional[str]:
        """Return the Artisan context name that matches *self._active*.

        Delegates to :meth:`~WeightSource.get_artisan_name` on the active
        source so each subclass is responsible for its own ctx name — no
        ``isinstance`` branching needed here.

        Returns:
            The context name string, or ``None`` when no source is active.
        """
        if self._active is None:
            return None
        return self._active.get_artisan_name()

    def get_artisan_clamp(self) -> Optional[Tuple[str, float, float]]:
        """Read clamp settings from the context resolved for *self._active*.

        Delegates to :func:`~artisan_maya.get_artisan_clamp` so all
        context-routing logic stays in the dedicated module.
        """
        ctx = self._resolve_paint_ctx()
        if ctx is None:
            return None
        result = _artisan_get_clamp(ctx)
        if result is None:
            logger.debug(f"Cannot read Artisan context limits for ctx='{ctx}'")
        return result

    def set_clamp_state(self, clamp_mode: str, cl: float, cu: float) -> None:
        """Persist the clamp state without pushing it back to the artisan context.

        Called by the UI after it has synchronised its widgets from the artisan
        context (``get_artisan_clamp``).  We only need to update the stored
        state so that subsequent numpy operations (flood, smooth) pick it up
        correctly — we must NOT re-push to the context or we create a feedback loop.

        Args:
            clamp_mode: ``'none'`` | ``'lower'`` | ``'upper'`` | ``'both'``.
            cl:         Lower clamp value.
            cu:         Upper clamp value.
        """
        self._clamp_mode = clamp_mode
        self._clamp_lower = cl
        self._clamp_upper = cu

    def set_artisan_clamp(self, clamp_mode: str, min_value: float, max_value: float) -> None:
        """Push clamp settings to the context resolved for *self._active*.

        Persists the values for numpy bulk operations (flood, smooth) then
        delegates the Maya ctx update to :func:`~artisan_maya.set_artisan_clamp`.
        """
        # persist for numpy operations
        self._clamp_mode = clamp_mode
        self._clamp_lower = min_value
        self._clamp_upper = max_value

        ctx = self._resolve_paint_ctx()
        if ctx is None:
            return
        _artisan_set_clamp(clamp_mode, min_value, max_value, ctx)

    def _get_clamp_kwargs(self) -> dict:
        """Return ``clamp_min`` / ``clamp_max`` kwargs for :func:`apply_operation` flood calls.

        When clamp mode is ``'none'`` we explicitly override :func:`_op_flood`'s
        restrictive defaults (``clamp_min=0.0, clamp_max=1.0``) with unbounded
        floats so that weight values outside ``[0, 1]`` are not silently clipped.
        """
        if self._clamp_mode == 'none':
            return {'clamp_min': float('-inf'), 'clamp_max': float('inf')}
        kw: dict = {}
        if self._clamp_mode in ('lower', 'both'):
            kw['clamp_min'] = self._clamp_lower
        if self._clamp_mode in ('upper', 'both'):
            kw['clamp_max'] = self._clamp_upper
        return kw

    def _clamp_weights_post(self, mask: Optional[List[int]] = None) -> None:
        """Post-process: re-read, clamp, and write back weights when clamp is active.

        Used after smooth operations whose underlying numpy path does not
        natively support clamp kwargs.

        Args:
            mask: Optional list of vertex indices to restrict the clamp to.
                  When ``None`` all vertices are clamped.
        """
        if self._clamp_mode == 'none' or self._active is None:
            return
        cl = self._clamp_lower if self._clamp_mode in ('lower', 'both') else None
        cu = self._clamp_upper if self._clamp_mode in ('upper', 'both') else None
        if cl is None and cu is None:
            return
        weights = list(self._active.get_weights())
        indices = mask if mask is not None else range(len(weights))
        for i in indices:
            w = weights[i]
            if cl is not None and w < cl:
                weights[i] = cl
            if cu is not None and w > cu:
                weights[i] = cu
        self._active.set_weights(weights)

    def _convert_selection_to_vtx(self) -> None:
        """Convert any face / edge selection to vertices in-place.

        Vertices and transform selections are left untouched.
        """
        sel = cmds.ls(sl=True, fl=True) or []
        if not sel:
            return
        faces = cmds.filterExpand(sel, selectionMask=34) or []
        edges = cmds.filterExpand(sel, selectionMask=32) or []
        if faces or edges:
            vtx = cmds.polyListComponentConversion(sel, toVertex=True)
            vtx = cmds.ls(vtx, fl=True) or []
            if vtx:
                cmds.select(vtx, replace=True)
                logger.debug(
                    f"paint: converted {len(faces)} face(s) + {len(edges)} edge(s)"
                    f" → {len(vtx)} vertices"
                )

    @keep_selection
    @singleUndoChunk
    def set_weight(self, value: float, op: str = 'replace') -> None:
        """Set a scalar weight on the current vertex selection.

        Args:
            value: Weight value to apply.
            op: Operation mode — ``'replace'``, ``'add'``, or ``'multiply'``.
        """
        if not self._require_active():
            return

        sel_obj = cmds.ls(sl=True, o=True) or []
        sel_all = cmds.ls(sl=True, fl=True) or []
        logger.debug(f"set_weight — selection: {sel_all}, op={op}")
        if len(sel_all) > len(sel_obj):
            sel = [i for i in sel_all if "." in i]
        else:
            sel = sel_obj
        if sel:
            vtx = cmds.polyListComponentConversion(sel, toVertex=True)
            vtx = cmds.ls(vtx, fl=True) or []
            if vtx:
                indices = extract_id(vtx)
                apply_operation(self._active, 'flood', value=value, op=op,
                                mask=indices, **self._get_clamp_kwargs())
                logger.debug(f"set_weight — applied {op} on {len(indices)} vertices")
                return
        apply_operation(self._active, 'flood', value=value, op=op,
                        **self._get_clamp_kwargs())
        logger.debug(f"set_weight — applied {op} on all vertices")

    def get_weight_range(self) -> Optional[Tuple[float, float]]:
        """Return ``(min, max)`` of the current map's weights, rounded to 1 decimal.

        Returns ``None`` when no active source / map is set or reading fails.
        """
        if not self._require_active():
            return 0, 1
        try:
            weights = self._active.get_weights()
            if not weights:
                return 0, 1
            lo = round(min(weights)) if round(min(weights)) > 1 else 0
            hi = round(max(weights), 1)
            return (lo, hi)
        except Exception as e:
            logger.debug(f"get_weight_range failed: {traceback.format_exc()}")
            return None

    def set_artisan_color_range(self, lo: float, hi: float) -> None:
        """Push display range to the active artisan context.

        Delegates to :func:`~artisan_maya.set_artisan_color_range`.
        Silently skipped for vertex-alpha (``dwAlphaPaintCtx``).
        """
        ctx = self._resolve_paint_ctx()
        if ctx is None:
            return
        try:
            _artisan_set_color_range(lo, hi, ctx)
        except Exception as e:
            logger.debug(f"set_artisan_color_range failed: {e}")

    def _get_vtx_mask(self) -> Optional[List[int]]:
        """Retourne les indices de la sélection vertex courante, ou None si tout.

        Retourne None si seul l'objet est sélectionné (pas de composants).
        """
        sel_all = cmds.ls(sl=True, fl=True) or []
        # Uniquement les sélections composant (contiennent un '.')
        sel = [s for s in sel_all if '.' in s]
        if not sel:
            return None
        vtx = cmds.polyListComponentConversion(sel, toVertex=True)
        vtx = cmds.ls(vtx, fl=True) or []
        if vtx:
            from dw_maya.dw_maya_utils import extract_id

            return extract_id(vtx)
        return None

    @timeIt(track_stats=True)
    @singleUndoChunk
    def smooth(self, iterations: int = 1) -> None:
        """Topology-based smooth via numpy path, selection-aware."""
        if not self._require_active():
            return
        mask = self._get_vtx_mask()
        try:
            apply_operation(self._active, 'smooth', iterations=iterations, factor=0.5, mask=mask)
            self._clamp_weights_post(mask)
        except Exception as e:
            logger.error(f"Smooth failed: {e}")

    @timeIt(track_stats=True)
    @singleUndoChunk
    def smooth_artisan(self, iterations: int = 1) -> None:
        """Smooth via Maya artisan flood (all vertices, with viewport feedback).

        Unlike :meth:`smooth`, this method always takes the artisan path and
        does NOT fall back to numpy when a vertex selection is active — artisan
        smooth floods the whole mesh regardless of selection, which is the
        expected behaviour when the user explicitly chooses 'artisan' mode.
        """
        from dw_maya.dw_paint.vertex_color_alpha import VertexColorAlpha
        from dw_maya.dw_paint.artisan_maya import _CTX_ALPHA, flood_smooth_vtx_map, _CTX_NUCLEUS

        if not self._require_active():
            return

        # ── nCloth / nRigid ─────────────────────────────────────────────
        if isinstance(self._active, NClothMap):
            try:
                for _ in range(iterations):
                    flood_smooth_vtx_map(context_name=_CTX_NUCLEUS)
                logger.info(f"Nucleus artisan smooth x{iterations}.")
            except Exception as e:
                raise RuntimeError(
                    f"Click \"Paint\" before using artisan smooth. Detail: {e}"
                )

        # ── VertexColorAlpha ─────────────────────────────────────────────
        elif isinstance(self._active, VertexColorAlpha):
            ctx = _CTX_ALPHA
            if cmds.currentCtx() != ctx:
                self._active.paint()
            import __main__
            controller = __main__.__dict__.get(ctx)
            if controller:
                controller._batch_mode = True
            cmds.artUserPaintCtx(ctx, edit=True, selectedattroper='smooth')
            for _ in range(iterations):
                cmds.artUserPaintCtx(ctx, edit=True, clear=True)
            cmds.artUserPaintCtx(ctx, edit=True, selectedattroper='additive')
            if controller:
                controller._batch_mode = False
                self._active.set_weights(controller._alphas)
            self._clamp_weights_post()
            logger.info(f"Alpha artisan smooth x{iterations}.")

        # ── Standard deformers ────────────────────────────────
        else:
            try:
                mel.eval('artAttrPaintOperation artAttrCtx Smooth')
            except RuntimeError:
                raise RuntimeError('Click "Paint" before using artisan smooth.')
            for _ in range(iterations):
                cmds.artAttrCtx(cmds.currentCtx(), edit=True, clear=True)
            mel.eval('artAttrPaintOperation artAttrCtx Replace')
            logger.info(f"Artisan smooth x{iterations}.")

    def copy_weights(self) -> None:
        """Store the active source's weights in the clipboard."""
        if not self._require_active():
            return
        self._clipboard = self._active.get_weights()
        if self._clipboard:
            logger.info(
                f"Copied {len(self._clipboard)} weights from "
                f"'{self._active.node_name}' map='{self._active_map}'"
            )

    @singleUndoChunk
    def paste_weights(self) -> None:
        """Paste clipboard weights to the active source on selected vertices only."""
        if not self._require_active():
            return
        if not self._clipboard:
            logger.warning("Clipboard is empty — copy weights first.")
            return
        if len(self._clipboard) != self._active.vtx_count:
            logger.warning(
                f"Clipboard has {len(self._clipboard)} values but active "
                f"source has {self._active.vtx_count} vertices."
            )
            return

        # Get current vertex selection mask
        mask = self._get_vtx_mask()

        if mask is None:
            # No selection — paste all
            self._active.set_weights(self._clipboard)
            logger.info(f"Pasted weights to '{self._active.node_name}' (all vertices).")
        else:
            # Selection exists — paste only on selected vertices
            current_weights = list(self._active.get_weights())
            for idx in mask:
                if idx < len(self._clipboard):
                    current_weights[idx] = self._clipboard[idx]
            self._active.set_weights(current_weights)
            logger.info(f"Pasted weights to '{self._active.node_name}' ({len(mask)} selected vertices).")


    def select_by_mod(self, vtx_list:list, key_mod:int=0) -> None:
        if key_mod == 1:
            cmds.select(vtx_list, toggle=True)
        elif key_mod == 4:
            cmds.select(vtx_list, deselect=True)
        elif key_mod == 5:
            cmds.select(vtx_list, add=True)
        else:
            cmds.select(vtx_list, replace=True)

    def select_vertices_by_range(self,
                                 min_value: float = 0,
                                 max_value: float = 1,
                                 key_mod: int = 0,
                                 use_cache: bool = False) -> None:
        """Select vertices in [min_value, max_value] weight range.

        Args:
            use_cache: If True, use pre-cached weights from _on_range_press.
                       Speeds up live updates during slider drag.
        """
        if not self._require_active():
            return

        # Use cached weights during live drag, else fetch fresh
        if use_cache and self._cached_weights is not None:
            weights = self._cached_weights
            mesh = self._cached_mesh
        else:
            weights = self._active.get_weights()
            mesh = self._active.mesh_name

        # Filter vertices in range
        indices = [i for i, w in enumerate(weights)
                   if min_value <= w <= max_value]

        if not indices:
            cmds.select(clear=True)
            return

        # Build selection
        ranges = dw_maya.dw_maya_utils.create_maya_ranges(indices)
        vtx_list = [f'{mesh}.vtx[{r}]' for r in ranges]
        self.select_by_mod(vtx_list, key_mod)

    # Add these methods
    def _on_range_selection_pressed(self) -> None:
        """Called when user presses slider handle — cache weights once."""
        if not self._require_active():
            return
        self._cached_weights = self._active.get_weights()
        self._cached_mesh = self._active.mesh_name

    def _on_range_selection_released(self) -> None:
        """Called when user releases slider — clear cache."""
        self._cached_weights = None
        self._cached_mesh = None

    def select_vertices_by_weight(self,
                                  from_zero: bool = True,
                                  tolerance: float = 0.0,
                                  key_mod: int = 0) -> None:
        """Select vertices near 0 (from_zero=True) or near 1 (False)."""
        if not self._require_active():
            return
        weights = self._active.get_weights()
        if not weights:
            return
        if from_zero:
            indices = [i for i, w in enumerate(weights) if w <= tolerance]
        else:
            indices = [i for i, w in enumerate(weights) if w >= 1.0 - tolerance]

        mesh = self._active.mesh_name
        if not indices:
            cmds.select(clear=True)
            logger.info("No vertices match the weight criteria.")
            return

        mel.eval(f'doMenuComponentSelection("{mesh}", "vertex")')
        ranges = dw_maya.dw_maya_utils.create_maya_ranges(indices)
        vtx_list = [f'{mesh}.vtx[{r}]' for r in ranges]

        if key_mod == 1:
            cmds.select(vtx_list, toggle=True)
        elif key_mod == 4:
            cmds.select(vtx_list, deselect=True)
        elif key_mod == 5:
            cmds.select(vtx_list, add=True)
        else:
            cmds.select(vtx_list, replace=True)

    def select_all(self, key_mod: int = 0) -> None:
        """Select all vertices of the active mesh."""
        if not self._require_active():
            return
        mesh = self._active.mesh_name
        n = self._active.vtx_count
        mel.eval(f'doMenuComponentSelection("{mesh}", "vertex")')
        vertices = f'{mesh}.vtx[0:{n - 1}]'
        if key_mod == 1:
            cmds.select(vertices, toggle=True)
        else:
            cmds.select(vertices, replace=True)

    def border_selection(self, key_mod:int=0) -> None:
        """Select border vertices of the current component selection."""

        if key_mod == 1:
            select_border_recursive(mode="inner")
        else:
            select_border(mode="inner")

    @singleUndoChunk
    def apply_vector_weights(self, direction: str,
                             falloff: str = 'linear',
                             invert: bool = False,
                             mode: str = 'vector',
                             op: str = 'replace') -> None:
        """Distribute weights by projection along a world-space direction.

        Respects current vertex selection if active.

        Args:
         direction: Predefined axis key (``'x+'``, ``'x-'``, ``'y+'``, ``'y-'``,
                    ``'z+'``, ``'z-'``) or a ``'x,y,z'`` custom vector string.
                    Ignored when mode is ``'normal'``.
         falloff:   Curve type — ``'linear'``, ``'quadratic'``, ``'smooth'``, ``'smooth2'``.
         invert:    Invert the result.
         mode:      ``'vector'`` | ``'projection'`` | ``'distance'`` | ``'normal'``.
        """
        if not self._require_active():
            return
        if mode == 'normal':
            dir_arg = 'y+'  # ignored but required by apply_operation signature
        elif ',' in direction:
            try:
                parts = [float(v.strip()) for v in direction.split(',')]
                dir_arg = tuple(parts)
            except ValueError:
                logger.error(f"Invalid custom direction '{direction}' — use 'x,y,z' format.")
                return
        else:
            dir_arg = direction
        try:
            from dw_maya.dw_paint.operations import set_directional_weights
            mask = self._get_vtx_mask()
            # Compute new weight distribution for entire mesh
            new_weights = set_directional_weights(self._active.mesh_name,
                                                  dir_arg,
                                                  remap_range=None,
                                                  falloff=falloff,
                                                  origin=None,
                                                  invert=invert,
                                                  mode=mode)
            if new_weights is None:
                logger.warning("Vector weights operation returned no data.")
                return

            weights = list(self._active.get_weights())

            def _apply_op(a, b, op_key: str):
                if op_key == 'replace':
                    return b
                if op_key == 'add':
                    return a + b
                if op_key == 'subtract':
                    return a - b
                if op_key == 'multiply':
                    return a * b
                # default
                return b

            if mask is None:
                # apply operation to all vertices
                if op == 'replace':
                    self._active.set_weights(new_weights)
                else:
                    result = [_apply_op(a, b, op) for a, b in zip(weights, new_weights)]
                    self._active.set_weights(result)
                logger.debug("Vector weights applied to all vertices.")
            else:
                # apply only to masked indices
                result = list(weights)
                for idx in mask:
                    if idx < len(new_weights):
                        result[idx] = _apply_op(result[idx], new_weights[idx], op)
                self._active.set_weights(result)
                logger.debug(f"Vector weights applied to {len(mask)} selected vertices (op={op}).")

            # Apply clamp post-processing if needed
            self._clamp_weights_post(mask)
        except Exception as e:
            logger.error(f"Vector weights failed: {e}")

    @singleUndoChunk
    def apply_radial_weights(self,
                               falloff: str = 'linear',
                               invert: bool = False,
                               center: tuple = None,
                               radius: float = None,
                               op: str = 'replace') -> None:
        """Distribute weights by radial distance from a centre point.

        Respects current vertex selection if active.

        When *center* or *radius* are ``None``, they are resolved in this order:
        1. Current soft-selection radius (Maya ``softSelectFalloffCurve`` / ``softSelectDistance``).
        2. Bounding-box centre / max extent of the current vertex selection.

        Args:
            falloff: Curve type — ``'linear'``, ``'quadratic'``, ``'smooth'``, ``'smooth2'``.
            invert:  Invert the result.
            center:  Explicit ``(x, y, z)`` world-space centre.  Auto if ``None``.
            radius:  Explicit max radius.  Auto if ``None``.
            op:      Operation to combine with existing weights: 'replace'|'add'|'subtract'|'multiply'.
        """
        if not self._require_active():
            return

        resolved_center = center
        resolved_radius = radius

        # Auto-resolve from selection / soft selection
        if resolved_center is None or resolved_radius is None:
            sel = cmds.ls(sl=True, fl=True) or []
            vtx = cmds.filterExpand(sel, selectionMask=31) or []

            if vtx and resolved_center is None:
                positions = [cmds.xform(v, q=True, ws=True, t=True) for v in vtx]
                xs = [p[0] for p in positions]
                ys = [p[1] for p in positions]
                zs = [p[2] for p in positions]
                resolved_center = (
                    (min(xs) + max(xs)) * 0.5,
                    (min(ys) + max(ys)) * 0.5,
                    (min(zs) + max(zs)) * 0.5,
                )

            if resolved_radius is None:
                # Try soft-selection distance first
                try:
                    ss_enabled = cmds.softSelect(q=True, sse=True)
                    if ss_enabled:
                        resolved_radius = cmds.softSelect(q=True, ssd=True)
                except Exception:
                    pass

        logger.debug(f"apply_radial_weights: center={resolved_center} radius={resolved_radius}")
        try:
            mask = self._get_vtx_mask()
            from dw_maya.dw_paint.operations import set_radial_weights
            new_weights = set_radial_weights(
                self._active.mesh_name,
                center=resolved_center,
                radius=resolved_radius,
                falloff=falloff,
                invert=invert,
            )
            if new_weights is None:
                logger.warning("Radial weights operation returned no data.")
                return

            weights = list(self._active.get_weights())

            def _apply_op(a, b, op_key: str):
                if op_key == 'replace':
                    return b
                if op_key == 'add':
                    return a + b
                if op_key == 'subtract':
                    return a - b
                if op_key == 'multiply':
                    return a * b
                return b

            if mask is None:
                if op == 'replace':
                    self._active.set_weights(new_weights)
                else:
                    result = [_apply_op(a, b, op) for a, b in zip(weights, new_weights)]
                    self._active.set_weights(result)
                logger.debug("Radial weights applied to all vertices.")
            else:
                result = list(weights)
                for idx in mask:
                    if idx < len(new_weights):
                        result[idx] = _apply_op(result[idx], new_weights[idx], op)
                self._active.set_weights(result)
                logger.debug(f"Radial weights applied to {len(mask)} selected vertices (op={op}).")

            self._clamp_weights_post(mask)
            self._restore_wear_paint()
        except Exception as e:
            logger.error(f"Radial weights failed: {e}")

    def get_soft_select_radius(self) -> float:
        """Return the current Maya soft-selection radius, or 0.0 if disabled."""
        try:
            if cmds.softSelect(q=True, sse=True):
                return float(cmds.softSelect(q=True, ssd=True))
        except Exception:
            pass
        return 0.0

    def get_selection_center(self) -> tuple:
        """Return the world-space bounding-box centre of the current selection.

        Returns:
            ``(x, y, z)`` tuple, or ``(0.0, 0.0, 0.0)`` when nothing is selected.
        """
        sel = cmds.ls(sl=True, fl=True) or []
        vtx = cmds.filterExpand(sel, selectionMask=31) or []
        if not vtx:
            # Fall back to object bounding box
            objs = cmds.ls(sl=True) or []
            if objs:
                bb = cmds.exactWorldBoundingBox(*objs)
                return (
                    (bb[0] + bb[3]) * 0.5,
                    (bb[1] + bb[4]) * 0.5,
                    (bb[2] + bb[5]) * 0.5,
                )
            return (0.0, 0.0, 0.0)
        positions = [cmds.xform(v, q=True, ws=True, t=True) for v in vtx]
        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        zs = [p[2] for p in positions]
        return (
            (min(xs) + max(xs)) * 0.5,
            (min(ys) + max(ys)) * 0.5,
            (min(zs) + max(zs)) * 0.5,
        )

    @singleUndoChunk
    def transfer_weights(self,
                          src_weights: List[float],
                          src_mesh: str,
                          tgt_ws: 'WeightSource',
                          max_distance: Optional[float] = None,
                          preserve_unmapped: bool = True,
                          src_vtx_transform: list = None) -> None:
        """
        Transfer weights from a source mesh to the target WeightSource.
        Uses nearest-neighbour interpolation in world space, so source and
        target may have completely different topologies. Optionally restricts
        transfer to vertices within a maximum distance (useful for partial transfers
        like a single arm rig).

        Args:
         src_weights: Per-vertex weight list from the source mesh.
         src_mesh:    Source mesh (transform or shape) name in the scene.
         tgt_ws:      Target WeightSource to receive the transferred weights.
         max_distance: Optional maximum distance threshold. If set, only transfer
                      weights from source vertices within this distance.
                      ``None`` = no distance limit (transfer all).
         preserve_unmapped: If ``True``, keep original target weights for vertices
                           beyond max_distance. If ``False``, set them to 0.0.
         src_vtx_transform: Optional pre-computed source vertex positions.
        """
        if not src_weights:
            logger.warning("transfer_weights: source has no stored weights.")
            return
        if tgt_ws is None:
            logger.warning("transfer_weights: no active target source.")
            return

        try:
            import maya.api.OpenMaya as om2
            import numpy as np

            def _get_world_positions(mesh_name: str) -> 'np.ndarray':
                sel = om2.MSelectionList()
                sel.add(mesh_name)
                dag = sel.getDagPath(0)
                fn = om2.MFnMesh(dag)
                pts = fn.getPoints(om2.MSpace.kWorld)
                return np.array([(p.x, p.y, p.z) for p in pts], dtype=np.float64)

            if not src_vtx_transform:
                src_pos = _get_world_positions(src_mesh)
            else:
                src_pos = np.array(src_vtx_transform, dtype=np.float64)
            tgt_pos = _get_world_positions(tgt_ws.mesh_name)

            src_arr = np.array(src_weights, dtype=np.float64)
            tgt_arr = np.array(tgt_ws.get_weights(), dtype=np.float64)

            # Nearest-neighbour query
            try:
                from scipy.spatial import KDTree
                tree = KDTree(src_pos)
                _, nn_idx = tree.query(tgt_pos)
            except ImportError:
                # Brute-force fallback (slower but no scipy dependency)
                nn_idx = []
                distances = []
                for tp in tgt_pos:
                    dists = np.sqrt(np.sum((src_pos - tp) ** 2, axis=1))
                    min_dist_idx = int(np.argmin(dists))
                    nn_idx.append(min_dist_idx)
                    distances.append(dists[min_dist_idx])
                nn_idx = np.array(nn_idx)
                distances = np.array(distances)

             # Apply distance limit if specified
            new_weights = np.array(tgt_arr, dtype=np.float64)
            if max_distance is not None:
                within_distance = distances <= max_distance
                new_weights[within_distance] = src_arr[nn_idx[within_distance]]

                # Handle unmapped vertices
                if not preserve_unmapped:
                    new_weights[~within_distance] = 0.0

                transferred_count = np.sum(within_distance)
                logger.info(
                    f"transfer_weights: {transferred_count} of {len(new_weights)} vertices transferred "
                    f"from '{src_mesh}' → '{tgt_ws.node_name}' (max_distance={max_distance})"
                )
            else:
                # No distance limit — transfer all
                new_weights = src_arr[nn_idx]
                logger.info(
                    f"transfer_weights: {len(new_weights)} weights transferred "
                    f"from '{src_mesh}' → '{tgt_ws.node_name}'"
                )

            tgt_ws.set_weights(new_weights.tolist())
        except Exception as e:
            logger.error(f"transfer_weights failed: {e}")

    def invert_selection(self) -> None:
        """Invert the current vertex selection.

        Uses the active mesh when a source is loaded for a precise inversion.
        Falls back to Maya's built-in ``InvertSelection`` otherwise so the
        button is always functional.
        """
        from dw_maya.dw_maya_utils import invert_selection
        invert_selection()

    @singleUndoChunk
    def remap_weights(self, old_min: float, old_max: float,
                      new_min: float, new_max: float) -> None:
        """Remap (fit) weights from [old_min, old_max] to [new_min, new_max].

        Args:
            old_min: Source range minimum.
            old_max: Source range maximum.
            new_min: Target range minimum.
            new_max: Target range maximum.
        """
        if not self._require_active():
            return
        old_range = old_max - old_min
        new_range = new_max - new_min
        if abs(old_range) < 1e-9:
            logger.warning("remap_weights: old_min == old_max, nothing to remap.")
            return
        try:
            weights = self._active.get_weights()
            remapped = [
                new_min + (w - old_min) / old_range * new_range
                for w in weights
            ]
            remapped = [max(min(v, 1.0), 0.0) for v in remapped]
            self._active.set_weights(remapped)
            logger.info(
                f"remap_weights: [{old_min},{old_max}] → [{new_min},{new_max}] "
                f"applied to {len(remapped)} weights."
            )
        except Exception as e:
            logger.error(f"remap_weights failed: {e}")

    def set_artisan_value(self, value: float) -> None:
        """Push value to artisan context (absolute/replace mode).

        Routes to the correct artisan context based on the active source's
        node type — no manual isinstance check needed in the UI layer.

        For ``artAttrCtx``-family contexts, also extends ``minvalue`` /
        ``maxvalue`` when *value* falls outside the current slider range, and
        calls ``artAttrUpdatePaintValueSlider`` so the Tool Settings slider
        stays in sync.
        """
        from dw_maya.dw_paint.artisan_maya import set_brush_val, _CTX_ALPHA
        if not self._require_active():
            return
        if isinstance(self._active, NClothMap):
            try:
                set_brush_val(value, mod='absolute')
            except Exception as e:
                logger.debug(f"set_cfx_brush_val failed (paint tool not active?): {e}")
            return
        # ── VertexColorAlpha — artUserPaintCtx ──────────────────────────
        from dw_maya.dw_paint.vertex_color_alpha import VertexColorAlpha
        if isinstance(self._active, VertexColorAlpha):
            try:
                if cmds.artUserPaintCtx(_CTX_ALPHA, exists=True):
                    cmds.artUserPaintCtx(_CTX_ALPHA, edit=True, value=value)
            except Exception as e:
                logger.debug(f"artUserPaintCtx value update failed: {e}")
            return
        # ── Standard deformers — artAttrCtx ──────────────────
        ctx = self._resolve_paint_ctx()
        if ctx is None:
            return
        try:
            if not cmds.artAttrCtx(ctx, exists=True):
                return
            # Extend the value slider range when needed.
            # minvalue/maxvalue control the Tool Settings slider bounds only —
            # they are separate from clamplower/clampupper (the clamp checkboxes).
            cur_min = cmds.artAttrCtx(ctx, query=True, minvalue=True)
            cur_max = cmds.artAttrCtx(ctx, query=True, maxvalue=True)
            new_min = min(cur_min, value)
            new_max = max(cur_max, value)
            cmds.artAttrCtx(ctx, edit=True, value=value,
                            minvalue=new_min, maxvalue=new_max)
        except Exception as e:
            logger.debug(f"set_artisan_value failed: {e}")