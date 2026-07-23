from maya import cmds, mel
from typing import Callable, List, Optional, Tuple, Union

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
    set_artisan_operation as _artisan_set_operation,
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

        # Advanced ops — explicit vertex mask (None = whole mesh).  Captured
        # on demand via set_advanced_mask_from_selection(), independent of
        # whatever is selected in Maya at Apply-time.
        self._mask_vtx_ids: Optional[List[int]] = None

        # skinCluster flood prune threshold — skip vertices whose current weight
        # on the active influence is below this, so negligible "garbage" weights
        # are not relocated onto an unlocked sibling.  0.0 = off (default).
        # Set from the SkinPanel "Prune below" field via set_prune().
        self._prune: float = 0.0

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

    def set_mode(self,
                 mode: str,
                 refresh: bool = True) -> None:
        """Switch between 'deformer', 'nucleus', 'vtxColor' and 'all' backends.

        Args:
            mode: Backend filter passed to resolve_weight_sources.
            refresh: Re-resolve sources immediately. Pass False at UI startup
                when restoring the saved radio state before any mesh is picked.
        """
        self._mode = mode
        if refresh:
            self.refresh()

    def refresh(self) -> None:
        """Re-resolve weight sources from the current Maya selection."""
        sel = cmds.filterExpand(selectionMask=[12, 31, 32, 34]) or []
        if not sel:
            self._sources = []
            self._active = None
            self._active_map = None
            self._mesh = None
            self._signals.sources_changed.emit([], [], [])
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
        has_weight = [s.has_weight_list() for s in self._sources]

        self._signals.sources_changed.emit(node_labels, map_lists, has_weight)
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

    def source_index_for_node(self, node_name: str) -> Optional[int]:
        """Index of the resolved source matching node_name (short or long form).

        Used by external tools (DynEval paint handoff) to locate a source
        after refresh() without reaching into the private source list.
        """
        short = node_name.split('|')[-1].split(':')[-1]
        for index, source in enumerate(self._sources):
            src_node = getattr(source, 'node_name', None)
            if src_node is None:
                continue
            if src_node == node_name:
                return index
            if src_node.split('|')[-1].split(':')[-1] == short:
                return index
        return None

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
        from dw_maya.dw_paint.vertex_color import VertexColorSet
        if isinstance(source, VertexColorSet):
            return f"[vtxColor] {source.color_set}"
        try:
            node_type = cmds.nodeType(source.node_name)
        except Exception:
            node_type = '?'
        return f"[{node_type}] {source.node_name}"

    def set_prune(self, value: float) -> None:
        """Set the skinCluster flood prune threshold (0.0 = off).

        Verts whose current weight on the active influence is below *value* are
        skipped by :meth:`set_weight`'s flood, so negligible micro-weights are
        not relocated onto an unlocked sibling.  Pushed from the SkinPanel
        "Prune below" field; only affects the skinCluster flood path.
        """
        self._prune = max(0.0, float(value))

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
                    f" -> {len(vtx)} vertices"
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

        vtx: List[str] = []
        if sel:
            vtx = cmds.polyListComponentConversion(sel, toVertex=True)
            vtx = cmds.ls(vtx, fl=True) or []

        # skinCluster 'replace' flood → use Maya's own lock-aware normalisation
        # via cmds.skinPercent, restricted to the selected vertices (or the whole
        # mesh when nothing is selected).  This pushes a flooded-to-zero weight
        # back onto the unlocked parent the way painting by hand does, which the
        # generic setWeights(normalize=True) array path cannot.  Falls back below
        # for add/multiply, non-skin sources, or any failure.
        flood = getattr(self._active, 'flood', None)
        if op == 'replace' and flood is not None:
            if flood(value, components=(vtx or None), prune=self._prune):
                logger.debug(
                    f"set_weight — skinCluster flood ({value}) on "
                    f"{len(vtx) if vtx else 'all'} vertices, prune={self._prune}"
                )
                return

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
            # Round both ends to 1 decimal — do NOT snap the low end to 0, so a
            # map whose minimum is 0.1 (or 1 on a 1–10 mass map) reports its real
            # minimum and the [min] select button targets those vertices instead
            # of the w==0 ones.
            lo = round(min(weights), 1)
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

    def set_advanced_mask_from_selection(self) -> int:
        """Capture the current vertex selection as the Advanced-ops mask.

        Until :meth:`clear_advanced_mask` is called, :meth:`apply_vector_weights`
        and :meth:`apply_radial_weights` restrict their output to these
        vertices, regardless of what is selected in Maya at Apply-time.

        Returns:
            Number of vertices captured (0 if the selection is empty or
            object-level).
        """
        mask = self._get_vtx_mask()
        self._mask_vtx_ids = mask
        return len(mask) if mask else 0

    def clear_advanced_mask(self) -> None:
        """Clear the Advanced-ops vertex mask — operations apply to the whole mesh."""
        self._mask_vtx_ids = None

    def get_advanced_mask_count(self) -> Optional[int]:
        """Return the size of the Advanced-ops mask, or None when unset (whole mesh)."""
        return len(self._mask_vtx_ids) if self._mask_vtx_ids else None

    @timeIt(track_stats=True)
    @singleUndoChunk
    def smooth(self, iterations: int = 1, mode: str = 'blur') -> None:
        """Topology-based smooth via numpy path, selection-aware.

        Args:
            iterations: Number of smoothing/erosion passes.
            mode:       ``'blur'`` (neighbor mean, default) | ``'erode'``
                        (neighbor min — shrinks painted regions inward).
                        Artisan mode has no erode equivalent — ``smooth_artisan``
                        always blurs regardless of *mode*.
        """
        if not self._require_active():
            return
        mask = self._get_vtx_mask()
        try:
            apply_operation(self._active, 'smooth', iterations=iterations, factor=0.5, mask=mask, mode=mode)
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
        from dw_maya.dw_paint.vertex_color import VertexColorSet
        from dw_maya.dw_paint.artisan_maya import _CTX_ALPHA, flood_smooth_vtx_map, _CTX_NUCLEUS

        if not self._require_active():
            return

        # -- nCloth / nRigid ---------------------------------------------
        if isinstance(self._active, NClothMap):
            try:
                for _ in range(iterations):
                    flood_smooth_vtx_map(context_name=_CTX_NUCLEUS)
                logger.info(f"Nucleus artisan smooth x{iterations}.")
            except Exception as e:
                raise RuntimeError(
                    f"Click \"Paint\" before using artisan smooth. Detail: {e}"
                )

        # -- VertexColorSet — active channel -----------------------------
        elif isinstance(self._active, VertexColorSet):
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
                self._active.set_weights(controller._values)
            self._clamp_weights_post()
            logger.info(f"Vertex color artisan smooth x{iterations}.")

        # -- Standard deformers --------------------------------
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
                             falloff: Union[str, List[Tuple[float, float]]] = 'linear',
                             invert: bool = False,
                             mode: str = 'vector',
                             op: str = 'replace') -> None:
        """Distribute weights by projection along a world-space direction.

        Restricted to the Advanced-ops mask (see
        :meth:`set_advanced_mask_from_selection`) if one is set, otherwise
        applies to the whole mesh.

        Args:
         direction: Predefined axis key (``'x+'``, ``'x-'``, ``'y+'``, ``'y-'``,
                    ``'z+'``, ``'z-'``) or a ``'x,y,z'`` custom vector string.
                    Ignored when mode is ``'normal'``.
         falloff:   Curve type — ``'linear'``, ``'quadratic'``, ``'smooth'``, ``'smooth2'`` —
                    or a list of ``(x, y)`` control points for a custom ramp curve.
         invert:    Invert the result.
         mode:      ``'vector'`` | ``'projection'`` | ``'distance'`` | ``'normal'`` | ``'uv'``.
                    In ``'uv'`` mode, *direction* is ``'u'`` or ``'v'``.
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
            mask = self._mask_vtx_ids
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
                               falloff: Union[str, List[Tuple[float, float]]] = 'linear',
                               invert: bool = False,
                               center: tuple = None,
                               radius: float = None,
                               op: str = 'replace') -> None:
        """Distribute weights by radial distance from a centre point.

        Restricted to the Advanced-ops mask (see
        :meth:`set_advanced_mask_from_selection`) if one is set, otherwise
        applies to the whole mesh.

        When *center* or *radius* are ``None``, they are resolved in this order:
        1. Current soft-selection radius (Maya ``softSelectFalloffCurve`` / ``softSelectDistance``).
        2. Bounding-box centre / max extent of the current vertex selection.

        Args:
            falloff: Curve type — ``'linear'``, ``'quadratic'``, ``'smooth'``, ``'smooth2'`` —
                     or a list of ``(x, y)`` control points for a custom ramp curve.
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
            mask = self._mask_vtx_ids
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

    @singleUndoChunk
    def apply_mirror_weights(self,
                             axis: str = 'x',
                             direction: str = 'positive',
                             tolerance: float = 0.001) -> None:
        """Mirror weights across an axis, driven by one half of the mesh.

        Restricted to the Advanced-ops mask (see
        :meth:`set_advanced_mask_from_selection`) if one is set — only the
        masked vertices are overwritten with their mirrored counterpart,
        otherwise the whole mesh is mirrored.

        Vertices with no geometric counterpart within *tolerance* (a mesh
        that is not fully symmetrical on this axis) keep their existing
        weight and are reported via a logger warning.

        Args:
            axis:      ``'x'`` | ``'y'`` | ``'z'``.
            direction: ``'positive'`` | ``'negative'`` — which half drives.
            tolerance: Position-matching tolerance for pairing vertices.
        """
        if not self._require_active():
            return
        try:
            mask = self._mask_vtx_ids
            weights = list(self._active.get_weights())
            from dw_maya.dw_paint.operations import mirror_weights
            mirrored = mirror_weights(
                self._active.mesh_name, weights,
                axis=axis, tolerance=tolerance, direction=direction,
            )
            if mirrored is None:
                logger.warning("Mirror weights operation returned no data.")
                return

            if mask is None:
                self._active.set_weights(mirrored)
                logger.debug(f"Mirror weights applied to all vertices (axis={axis}, direction={direction}).")
            else:
                result = list(weights)
                for idx in mask:
                    if idx < len(mirrored):
                        result[idx] = mirrored[idx]
                self._active.set_weights(result)
                logger.debug(f"Mirror weights applied to {len(mask)} selected vertices (axis={axis}, direction={direction}).")

            self._clamp_weights_post(mask)
            self._restore_wear_paint()
        except Exception as e:
            logger.error(f"Mirror weights failed: {e}")

    def set_native_symmetry(self,
                            enabled: bool,
                            axis: str = 'x',
                            tolerance: float = 0.001) -> None:
        """Toggle Maya's native viewport symmetry display/tool.

        Purely a visual/modeling aid to sanity-check a mesh for symmetry
        breaks before running :meth:`apply_mirror_weights` — does not
        affect weight data.

        Args:
            enabled:   Turn symmetry on/off.
            axis:      ``'x'`` | ``'y'`` | ``'z'``.
            tolerance: Position-matching tolerance, mirrored from the
                       Advanced-ops mirror panel.
        """
        try:
            cmds.symmetricModelling(symmetry=enabled, about='world',
                                    axis=axis, tolerance=tolerance)
        except Exception as e:
            logger.error(f"Could not toggle native symmetry: {e}")

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
                    f"from '{src_mesh}' -> '{tgt_ws.node_name}' (max_distance={max_distance})"
                )
            else:
                # No distance limit — transfer all
                new_weights = src_arr[nn_idx]
                logger.info(
                    f"transfer_weights: {len(new_weights)} weights transferred "
                    f"from '{src_mesh}' -> '{tgt_ws.node_name}'"
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
                f"remap_weights: [{old_min},{old_max}] -> [{new_min},{new_max}] "
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
        # -- VertexColorSet — artUserPaintCtx ----------------------------
        from dw_maya.dw_paint.vertex_color import VertexColorSet
        if isinstance(self._active, VertexColorSet):
            try:
                if cmds.artUserPaintCtx(_CTX_ALPHA, exists=True):
                    cmds.artUserPaintCtx(_CTX_ALPHA, edit=True, value=value)
            except Exception as e:
                logger.debug(f"artUserPaintCtx value update failed: {e}")
            return
        # -- Standard deformers — artAttrCtx ------------------
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

    def set_artisan_operation(self, op: str) -> None:
        """Push the paint operation to the active artisan context.

        Maps the UI's Replace / Add / Multiply choice to Maya's
        Replace / Add / Scale brush operations via
        :func:`~artisan_maya.set_artisan_operation`. This is one-way
        (UI -> artisan) — the artisan context is not read back to sync the UI.
        """
        from dw_maya.dw_paint.vertex_color import VertexColorSet
        if not self._require_active():
            return
        if isinstance(self._active, VertexColorSet):
            ctx = CTX_ALPHA
        else:
            ctx = self._resolve_paint_ctx()
        if ctx is None:
            return
        try:
            _artisan_set_operation(op, ctx)
        except Exception as e:
            logger.debug(f"set_artisan_operation failed: {e}")

    def start_weight_picker(self,
                            on_picked: Callable[[int, float], None],
                            on_cancel: Optional[Callable[[], None]] = None) -> None:
        """Start a one-shot viewport eyedropper for the active map's weights.

        Reads the active map's weights up front and hands off to
        :func:`~dw_maya.dw_paint.picker.pick_vertex_weight`, which raycasts
        the next viewport click and resolves the nearest vertex — the
        artisan picker is not involved, so pick vs. cancel is always known.
        """
        if not self._require_active():
            if on_cancel:
                on_cancel()
            return
        try:
            weights = self._active.get_weights()
        except Exception as e:
            logger.error(f"start_weight_picker: failed to read weights: {e}")
            if on_cancel:
                on_cancel()
            return

        from dw_maya.dw_paint.picker import pick_vertex_weight
        pick_vertex_weight(self._active.mesh_name, weights, on_picked, on_cancel)