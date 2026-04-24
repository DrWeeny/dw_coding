"""PySide6 UI for the Slimfast weight painting tool.

Replaces the legacy Maya cmds UI (bq_slimfast_py3.py) with a proper
PySide6 QWidget.  All Maya logic is delegated to the controller so the
UI itself contains zero cmds calls and is testable without a Maya session.

Usage (run inside Maya):
    from dw_maya.dw_paint.slimfast_widget import SlimfastWidget
    SlimfastWidget.show_docked()   # dock to Maya's right panel
    # or
    SlimfastWidget.show_window()   # floating window

Classes:
    SliderWithButton   — QSlider + QDoubleSpinBox + QPushButton composite
    SlimfastController — all Maya logic, no PySide6 imports
    SlimfastWidget     — PySide6 QWidget, signals connect to controller

Version: 2.0.0
Author:  DrWeeny
"""

from __future__ import annotations

from typing import List, Optional, Tuple
from functools import partial

from maya import cmds, mel
import maya.OpenMayaUI as omui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt, Signal, Slot
    from shiboken6 import wrapInstance
except ImportError:
    # Fallback for older Maya versions shipping PySide2
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Qt, Signal, Slot
    from shiboken2 import wrapInstance
from dw_utils import data_hub
import dw_maya.dw_paint
import dw_maya.dw_pyqt_utils.dw_btn_storage
from dw_maya.dw_pyqt_utils.wgt_slider import RangeSliderWithSpinbox, RangeSlider, SliderWithButton
from dw_maya.dw_paint.protocol import WeightSource
from dw_maya.dw_paint.vertex_color_alpha import create_alpha_map, VertexColorAlpha
from dw_maya.dw_decorators.dw_keep_selection import keep_selection
from dw_maya.dw_decorators import singleUndoChunk, timeIt
from dw_maya.dw_paint.weight_source import (
    resolve_weight_sources,
    paint_weight_source,
    apply_operation,
)
from dw_maya.dw_nucleus_utils import NClothMap
import dw_maya.dw_maya_utils
from dw_maya.dw_maya_utils.dw_maya_components import selectBorder, extract_id
import dw_maya.dw_nucleus_utils.dw_core
import dw_maya.dw_nucleus_utils.dw_nucleus_paint
from dw_logger import get_logger
from dw_maya.dw_paint.artisan_maya import (
    CTX_ALPHA,
    get_artisan_clamp as _artisan_get_clamp,
    set_artisan_clamp as _artisan_set_clamp,
    set_artisan_color_range as _artisan_set_color_range,
    set_artisan_value as _artisan_set_value,
    flood_smooth_vtx_map,
)

import traceback

logger = get_logger()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _maya_main_window() -> QtWidgets.QMainWindow:
    """Return Maya's main QMainWindow so we can parent to it."""
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QMainWindow)

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
        """Paste clipboard weights to the active source."""
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
        self._active.set_weights(self._clipboard)
        logger.info(f"Pasted weights to '{self._active.node_name}'.")

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
                                 min_value:float=0,
                                 max_value:float=1,
                                 key_mod:int=0) -> None:
        """Select vertices near 0 (from_zero=True) or near 1 (False)."""
        if not self._require_active():
            return
        weights = self._active.get_weights()
        indices = [i for i, w in enumerate(weights) if w <= max_value if w >= min_value]

        mesh = self._active.mesh_name
        if not indices:
            cmds.select(clear=True)
            logger.info("No vertices match the weight criteria.")
            return

        mel.eval(f'doMenuComponentSelection("{mesh}", "vertex")')
        ranges = dw_maya.dw_maya_utils.create_maya_ranges(indices)
        vtx_list = [f'{mesh}.vtx[{r}]' for r in ranges]
        self.select_by_mod(vtx_list, key_mod)

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

    def border_selection(self) -> None:
        """Select border vertices of the current component selection."""
        selectBorder()

    @singleUndoChunk
    def apply_vector_weights(self, direction: str, falloff: str = 'linear',
                              invert: bool = False, mode: str = 'vector') -> None:
        """Distribute weights by projection along a world-space direction.

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
            apply_operation(self._active, 'vector',
                            direction=dir_arg, falloff=falloff, invert=invert, mode=mode)
        except Exception as e:
            logger.error(f"Vector weights failed: {e}")

    @singleUndoChunk
    def apply_radial_weights(self,
                              falloff: str = 'linear',
                              invert: bool = False,
                              center: tuple = None,
                              radius: float = None) -> None:
        """Distribute weights by radial distance from a centre point.

        When *center* or *radius* are ``None``, they are resolved in this order:
        1. Current soft-selection radius (Maya ``softSelectFalloffCurve`` / ``softSelectDistance``).
        2. Bounding-box centre / max extent of the current vertex selection.

        Args:
            falloff: Curve type — ``'linear'``, ``'quadratic'``, ``'smooth'``, ``'smooth2'``.
            invert:  Invert the result.
            center:  Explicit ``(x, y, z)`` world-space centre.  Auto if ``None``.
            radius:  Explicit max radius.  Auto if ``None``.
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
            apply_operation(self._active, 'radial',
                            falloff=falloff, invert=invert,
                            center=resolved_center, radius=resolved_radius)
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
                         tgt_ws: 'WeightSource') -> None:
        """Transfer weights from a source mesh to the target WeightSource.

        Uses nearest-neighbour interpolation in world space, so source and
        target may have completely different topologies.

        Args:
            src_weights: Per-vertex weight list from the source mesh.
            src_mesh:    Source mesh (transform or shape) name in the scene.
            tgt_ws:      Target WeightSource to receive the transferred weights.
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

            src_pos = _get_world_positions(src_mesh)
            tgt_pos = _get_world_positions(tgt_ws.mesh_name)

            src_arr = np.array(src_weights, dtype=np.float64)

            # Nearest-neighbour query
            try:
                from scipy.spatial import KDTree
                tree = KDTree(src_pos)
                _, nn_idx = tree.query(tgt_pos)
            except ImportError:
                # Brute-force fallback (slower but no scipy dependency)
                nn_idx = []
                for tp in tgt_pos:
                    dists = np.sum((src_pos - tp) ** 2, axis=1)
                    nn_idx.append(int(np.argmin(dists)))
                nn_idx = np.array(nn_idx)

            new_weights = src_arr[nn_idx].tolist()
            tgt_ws.set_weights(new_weights)
            logger.info(
                f"transfer_weights: {len(new_weights)} weights transferred "
                f"from '{src_mesh}' → '{tgt_ws.node_name}'"
            )
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


# ---------------------------------------------------------------------------
# Qt signals relay (needed because controller has no QObject parent)
# ---------------------------------------------------------------------------

class SlimfastSignals(QtCore.QObject):
    """Qt signals emitted by SlimfastController."""

    #: Emitted when the source list changes.
    #: Payload: (node_labels: list[str], map_lists: list[list[str]])
    sources_changed = Signal(list, list)
    #: Emitted when the active mesh changes. Payload: mesh name string.
    mesh_changed = Signal(str)
    #: Emitted when the active WeightSource changes. Payload: WeightSource or None.
    active_changed = Signal(object)
    maps_changed = Signal(int)



# ---------------------------------------------------------------------------
# Reusable collapsible section widget
# ---------------------------------------------------------------------------

class CollapsibleSection(QtWidgets.QWidget):
    """A titled toggle button that shows/hides a content widget.

    Args:
        title:    Label shown on the toggle button.
        parent:   Optional parent widget.

    Example::

        section = CollapsibleSection('▶  Advanced ops')
        section.content_layout.addWidget(some_widget)
    """

    def __init__(self, title: str = '', parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        self._toggle_btn = QtWidgets.QToolButton()
        self._toggle_btn.setStyleSheet(
            'QToolButton { border: none; color: #aaaaaa; font-weight: bold; '
            'text-align: left; padding: 2px 4px; }'
            'QToolButton:hover { color: #dddddd; }'
        )
        self._toggle_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._toggle_btn.setArrowType(Qt.RightArrow)
        self._toggle_btn.setText(title)
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(False)

        # Horizontal rule beside the button
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        line.setStyleSheet('color: #555555;')

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 2, 0, 2)
        header.setSpacing(4)
        header.addWidget(self._toggle_btn)
        header.addWidget(line, stretch=1)

        self._content = QtWidgets.QWidget()
        self._content.setVisible(False)
        self.content_layout = QtWidgets.QVBoxLayout(self._content)
        self.content_layout.setContentsMargins(8, 4, 0, 4)
        self.content_layout.setSpacing(4)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(header)
        root.addWidget(self._content)

        self._toggle_btn.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self._toggle_btn.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self._content.setVisible(checked)


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class SlimfastWidget(QtWidgets.QWidget):
    """PySide6 replacement for the legacy Slimfast cmds UI."""

    _instance: Optional['SlimfastWidget'] = None
    _HUB_KEY = "slimfast.storage_buttons"

    # Minimum seconds between two automatic clamp-sync reads on mouse-enter.
    _CLAMP_SYNC_INTERVAL: float = 2.0

    # QProperty so external scripts / shelf buttons can read/write smooth iterations
    smooth_iterations_changed = Signal(int)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent or _maya_main_window())
        self.setWindowTitle('Slimfast 2.0')
        self.setWindowFlags(Qt.Window)
        self.setMinimumWidth(280)

        self._org = "DrWeeny"
        self._appname = "SlimfastWidget"

        self._signals = SlimfastSignals(self)
        self._ctrl = SlimfastController(self._signals)

        # Tracks the last active source type key so we can persist smooth mode
        # before switching to a new source type.
        self._src_type_key: str = 'deformer'

        self._build_ui()
        self._connect_signals()

        # Restore persisted preferences
        settings = QtCore.QSettings(self._org, self._appname)
        saved_iter = settings.value('smooth_iterations', 40, type=int)
        self.set_smooth_iterations(saved_iter)
        # Restore smooth mode preference (global — not per source type)
        saved_smooth = settings.value('smooth_mode', 0, type=int)
        self._smooth_mode.blockSignals(True)
        self._smooth_mode.setCurrentIndex(saved_smooth)
        self._smooth_mode.blockSignals(False)
        # Restore selection mode (Value vs Range)
        sel_value_mode = settings.value('sel_value_mode', False, type=bool)
        if sel_value_mode:
            self._sel_mode_check.setChecked(True)  # triggers _on_sel_mode_toggled

        # Restore storage buttons from in-session DataHub cache
        self._restore_storage_from_hub()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # Build content groups first (storage panel must exist before menu bar
        # wires its QAction, because setChecked() fires the toggled signal).
        deformer_grp = self._build_deformer_group()
        weights_grp = self._build_weights_group()
        smooth_grp = self._build_smooth_group()
        select_grp = self._build_select_group()
        self._advanced_section = self._build_advanced_section()
        self._transfer_section = self._build_transfer_section()
        self._remap_section = self._build_remap_section()
        self._storage_panel = self._build_storage_panel()

        # Menu bar — View > Storage expanded (reads QSettings for initial state)
        self._menu_bar = self._build_menu_bar()
        root.addWidget(self._menu_bar)

        # Main horizontal split: left tool groups | right storage column
        main_area = QtWidgets.QHBoxLayout()
        main_area.setSpacing(6)
        main_area.setContentsMargins(0, 0, 0, 0)

        left_col = QtWidgets.QVBoxLayout()
        left_col.setSpacing(4)
        left_col.addWidget(deformer_grp)
        left_col.addWidget(weights_grp)
        left_col.addWidget(smooth_grp)
        left_col.addWidget(select_grp)
        left_col.addWidget(self._advanced_section)
        left_col.addWidget(self._transfer_section)
        left_col.addWidget(self._remap_section)
        left_col.addStretch()
        main_area.addLayout(left_col, stretch=1)
        main_area.addWidget(self._storage_panel)

        root.addLayout(main_area)

    def _build_menu_bar(self) -> QtWidgets.QMenuBar:
        """Build top menu bar with a Pref menu to toggle the storage panel and sections."""
        menu_bar = QtWidgets.QMenuBar(self)
        view_menu = menu_bar.addMenu('Pref')

        settings = QtCore.QSettings('DrWeeny', 'SlimfastWidget')

        # --- Storage panel ---
        self._storage_action = QtWidgets.QAction('Storage expanded', self)
        self._storage_action.setCheckable(True)
        expanded = settings.value('storage_expanded', True, type=bool)
        self._storage_panel.setVisible(bool(expanded))
        self._storage_action.setChecked(bool(expanded))
        self._storage_action.toggled.connect(self._on_storage_toggled)
        view_menu.addAction(self._storage_action)

        view_menu.addSeparator()

        # --- Advanced ops section ---
        self._adv_section_action = QtWidgets.QAction('Show Advanced ops', self)
        self._adv_section_action.setCheckable(True)
        adv_visible = settings.value('adv_section_visible', False, type=bool)
        self._advanced_section.setVisible(bool(adv_visible))
        self._adv_section_action.setChecked(bool(adv_visible))
        self._adv_section_action.toggled.connect(self._advanced_section.setVisible)
        view_menu.addAction(self._adv_section_action)

        # --- Transfer section ---
        self._transfer_section_action = QtWidgets.QAction('Show Transfer', self)
        self._transfer_section_action.setCheckable(True)
        tr_visible = settings.value('transfer_section_visible', False, type=bool)
        self._transfer_section.setVisible(bool(tr_visible))
        self._transfer_section_action.setChecked(bool(tr_visible))
        self._transfer_section_action.toggled.connect(self._transfer_section.setVisible)
        view_menu.addAction(self._transfer_section_action)

        # --- Remap section ---
        self._remap_section_action = QtWidgets.QAction('Show Remap / Fit', self)
        self._remap_section_action.setCheckable(True)
        remap_visible = settings.value('remap_section_visible', False, type=bool)
        self._remap_section.setVisible(bool(remap_visible))
        self._remap_section_action.setChecked(bool(remap_visible))
        self._remap_section_action.toggled.connect(self._remap_section.setVisible)
        view_menu.addAction(self._remap_section_action)

        view_menu.addSeparator()

        # --- Visible modes submenu ---
        modes_menu = view_menu.addMenu('Visible modes')
        _mode_labels = {
            'all':       'All',
            'deformer':  'Deformer',
            'nucleus':   'nCloth',
            'vtxColor':  'vtxAlpha',
        }
        self._mode_visibility_actions = {}
        for mode_key, btn in self._mode_btns.items():
            action = QtWidgets.QAction(_mode_labels.get(mode_key, mode_key), self)
            action.setCheckable(True)
            visible = settings.value(f'mode_visible_{mode_key}', True, type=bool)
            btn.setVisible(bool(visible))
            action.setChecked(bool(visible))
            action.toggled.connect(partial(self._on_mode_visibility_changed, mode_key))
            modes_menu.addAction(action)
            self._mode_visibility_actions[mode_key] = action

        # --- Create menu ---
        create_menu = menu_bar.addMenu('Create')
        act_new_alpha = QtWidgets.QAction('New vertex alpha map…', self)
        act_new_alpha.triggered.connect(self._on_create_alpha_map)
        create_menu.addAction(act_new_alpha)

        return menu_bar

    def _build_advanced_section(self) -> CollapsibleSection:
        """Build the collapsible 'Advanced ops' section (vector / radial weights)."""
        section = CollapsibleSection('Advanced ops')
        lay = section.content_layout

        # Make the advanced section visually distinct with a QGroupBox
        group_box = QtWidgets.QGroupBox()
        group_box.setStyleSheet("QGroupBox { margin-top: 1ex; border: 1px solid #444; border-radius: 4px; padding: 4px; }")
        grp_lay = QtWidgets.QVBoxLayout(group_box)
        grp_lay.setContentsMargins(4, 8, 4, 4)
        grp_lay.setSpacing(4)
        lay.addWidget(group_box)

        # Build everything inside the group_box
        lay = grp_lay

        # --- Mode selector ---
        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel('Mode'))
        self._adv_mode_combo = QtWidgets.QComboBox()
        self._adv_mode_combo.addItems(['vector', 'radial'])
        mode_row.addWidget(self._adv_mode_combo)
        mode_row.addStretch()
        lay.addLayout(mode_row)

        # --- Falloff ---
        falloff_row = QtWidgets.QHBoxLayout()
        falloff_row.addWidget(QtWidgets.QLabel('Falloff'))
        self._adv_falloff_combo = QtWidgets.QComboBox()
        self._adv_falloff_combo.addItems(['linear', 'quadratic', 'smooth', 'smooth2'])
        falloff_row.addWidget(self._adv_falloff_combo)
        falloff_row.addStretch()
        lay.addLayout(falloff_row)

        # ---- Vector sub-widget ----------------------------------------
        self._adv_vector_widget = QtWidgets.QWidget()
        vec_lay = QtWidgets.QVBoxLayout(self._adv_vector_widget)
        vec_lay.setContentsMargins(0, 0, 0, 0)
        vec_lay.setSpacing(4)

        # Direction mode (vector / projection / distance / normal)
        vmode_row = QtWidgets.QHBoxLayout()
        vmode_row.addWidget(QtWidgets.QLabel('Type'))
        self._adv_vec_mode_combo = QtWidgets.QComboBox()
        self._adv_vec_mode_combo.addItems(['vector', 'projection', 'distance', 'normal'])
        vmode_row.addWidget(self._adv_vec_mode_combo)
        vmode_row.addStretch()
        vec_lay.addLayout(vmode_row)

        # Axis radio buttons (hidden in normal mode)
        self._adv_axis_widget = QtWidgets.QWidget()
        axis_lay = QtWidgets.QVBoxLayout(self._adv_axis_widget)
        axis_lay.setContentsMargins(0, 0, 0, 0)
        axis_lay.setSpacing(2)

        axis_row = QtWidgets.QHBoxLayout()
        axis_row.addWidget(QtWidgets.QLabel('Direction'))
        self._adv_axis_group = QtWidgets.QButtonGroup(self)
        for axis in ('x+', 'x-', 'y+', 'y-', 'z+', 'z-'):
            btn = QtWidgets.QRadioButton(axis)
            btn.setProperty('axis', axis)
            if axis == 'y+':
                btn.setChecked(True)
            self._adv_axis_group.addButton(btn)
            axis_row.addWidget(btn)
        axis_lay.addLayout(axis_row)

        custom_row = QtWidgets.QHBoxLayout()
        self._adv_custom_check = QtWidgets.QCheckBox('Custom')
        self._adv_custom_vec = QtWidgets.QLineEdit('0,1,0')
        self._adv_custom_vec.setPlaceholderText('x, y, z')
        self._adv_custom_vec.setEnabled(False)
        self._adv_custom_check.toggled.connect(self._adv_custom_vec.setEnabled)
        self._adv_custom_check.toggled.connect(
            partial(self._toggle_axis_buttons, enable=False)
        )
        custom_row.addWidget(self._adv_custom_check)
        custom_row.addWidget(self._adv_custom_vec, stretch=1)
        axis_lay.addLayout(custom_row)
        vec_lay.addWidget(self._adv_axis_widget)

        # Hide axis controls in 'normal' mode
        self._adv_vec_mode_combo.currentTextChanged.connect(
            lambda m: self._adv_axis_widget.setVisible(m != 'normal')
        )
        lay.addWidget(self._adv_vector_widget)

        # ---- Radial sub-widget ----------------------------------------
        self._adv_radial_widget = QtWidgets.QWidget()
        rad_lay = QtWidgets.QVBoxLayout(self._adv_radial_widget)
        rad_lay.setContentsMargins(0, 0, 0, 0)
        rad_lay.setSpacing(4)
        self._adv_radial_widget.setVisible(False)

        # Center picker row
        center_row = QtWidgets.QHBoxLayout()
        center_row.addWidget(QtWidgets.QLabel('Center'))
        self._adv_center_x = QtWidgets.QDoubleSpinBox()
        self._adv_center_y = QtWidgets.QDoubleSpinBox()
        self._adv_center_z = QtWidgets.QDoubleSpinBox()
        for sp in (self._adv_center_x, self._adv_center_y, self._adv_center_z):
            sp.setRange(-99999.0, 99999.0)
            sp.setDecimals(3)
            sp.setFixedWidth(68)
            center_row.addWidget(sp)
        pick_btn = QtWidgets.QPushButton('◎')
        pick_btn.setFixedWidth(24)
        pick_btn.setToolTip('Set center from current selection bounding box')
        pick_btn.clicked.connect(self._on_pick_radial_center)
        center_row.addWidget(pick_btn)
        rad_lay.addLayout(center_row)

        # Radius row
        radius_row = QtWidgets.QHBoxLayout()
        radius_row.addWidget(QtWidgets.QLabel('Radius'))
        self._adv_radius_spin = QtWidgets.QDoubleSpinBox()
        self._adv_radius_spin.setRange(0.0, 99999.0)
        self._adv_radius_spin.setDecimals(3)
        self._adv_radius_spin.setValue(0.0)
        self._adv_radius_spin.setSpecialValueText('auto')
        self._adv_radius_spin.setToolTip('0 = auto from soft-selection or bounding box')
        radius_row.addWidget(self._adv_radius_spin)
        ss_btn = QtWidgets.QPushButton('Soft sel')
        ss_btn.setFixedWidth(56)
        ss_btn.setToolTip('Read radius from current soft-selection distance')
        ss_btn.clicked.connect(self._on_read_soft_select_radius)
        radius_row.addWidget(ss_btn)
        radius_row.addStretch()
        rad_lay.addLayout(radius_row)

        lay.addWidget(self._adv_radial_widget)

        # ---- Shared controls ------------------------------------------
        self._adv_invert_check = QtWidgets.QCheckBox('Invert')
        lay.addWidget(self._adv_invert_check)

        self._adv_apply_btn = QtWidgets.QPushButton('Apply')
        self._adv_apply_btn.setStyleSheet(
            'QPushButton { background-color: #505060; color: white; }'
            'QPushButton:hover { background-color: #606070; }'
        )
        self._adv_apply_btn.clicked.connect(self._on_advanced_apply)
        lay.addWidget(self._adv_apply_btn)

        # Show/hide sub-widgets based on mode
        self._adv_mode_combo.currentTextChanged.connect(self._on_adv_mode_changed)

        return section

    def _build_transfer_section(self) -> 'CollapsibleSection':
        """Build the collapsible 'Transfer weights' section.

        The user stores a source mesh's weights in the embedded slot button,
        then switches to a different mesh/deformer as the active target and
        clicks Transfer.  Cross-topology nearest-neighbour interpolation is
        used so source and target may have completely different vertex counts.

        Returns:
            A CollapsibleSection ready to be added to the left column.
        """
        section = CollapsibleSection('Transfer weights')
        lay = section.content_layout

        # -- Source slot (embedded VtxStorageButton) -----------------------
        src_row = QtWidgets.QHBoxLayout()
        src_label = QtWidgets.QLabel('Source')
        src_label.setFixedWidth(48)
        src_row.addWidget(src_label)

        self._transfer_src_btn = dw_maya.dw_pyqt_utils.dw_btn_storage.VtxStorageButton()
        self._transfer_src_btn.setFixedSize(44, 44)
        self._transfer_src_btn.setText('Src')
        self._transfer_src_btn.setToolTip(
            'Right-click → Store  to capture the source mesh weights.\n'
            'Then switch to the target deformer and click Transfer.'
        )
        src_row.addWidget(self._transfer_src_btn)

        set_src_btn = QtWidgets.QPushButton('← Active')
        set_src_btn.setFixedWidth(60)
        set_src_btn.setToolTip('Set this slot\'s source from the currently active deformer')
        set_src_btn.clicked.connect(self._on_transfer_set_source)
        src_row.addWidget(set_src_btn)
        src_row.addStretch()
        lay.addLayout(src_row)

        # -- Target label (reflects active source) -------------------------
        tgt_row = QtWidgets.QHBoxLayout()
        tgt_lbl = QtWidgets.QLabel('Target')
        tgt_lbl.setFixedWidth(48)
        tgt_row.addWidget(tgt_lbl)
        self._transfer_tgt_label = QtWidgets.QLabel('— (active source) —')
        self._transfer_tgt_label.setStyleSheet('color: #aaaaaa; font-size: 11px;')
        tgt_row.addWidget(self._transfer_tgt_label, stretch=1)
        lay.addLayout(tgt_row)

        # -- Transfer button -----------------------------------------------
        transfer_btn = QtWidgets.QPushButton('Transfer ▶')
        transfer_btn.setFixedHeight(28)
        transfer_btn.setStyleSheet(
            'QPushButton { background-color: #405060; color: white; }'
            'QPushButton:hover { background-color: #506070; }'
        )
        transfer_btn.clicked.connect(self._on_transfer_apply)
        lay.addWidget(transfer_btn)

        return section

    def _build_remap_section(self) -> CollapsibleSection:
        """Build the collapsible 'Remap / Fit' section.

        Remaps current weights from [old_min, old_max] to [new_min, new_max].

        Returns:
            A CollapsibleSection ready to be added to the left column.
        """
        section = CollapsibleSection('Remap / Fit')
        lay = section.content_layout

        # Old range row
        old_row = QtWidgets.QHBoxLayout()
        old_row.addWidget(QtWidgets.QLabel('Old'))
        self._remap_old_min = QtWidgets.QDoubleSpinBox()
        self._remap_old_max = QtWidgets.QDoubleSpinBox()
        for sp in (self._remap_old_min, self._remap_old_max):
            sp.setRange(-99.0, 99.0)
            sp.setDecimals(3)
            sp.setFixedWidth(68)
        self._remap_old_min.setValue(0.0)
        self._remap_old_max.setValue(1.0)
        old_row.addWidget(QtWidgets.QLabel('min'))
        old_row.addWidget(self._remap_old_min)
        old_row.addWidget(QtWidgets.QLabel('max'))
        old_row.addWidget(self._remap_old_max)
        old_row.addStretch()
        lay.addLayout(old_row)

        # New range row
        new_row = QtWidgets.QHBoxLayout()
        new_row.addWidget(QtWidgets.QLabel('New'))
        self._remap_new_min = QtWidgets.QDoubleSpinBox()
        self._remap_new_max = QtWidgets.QDoubleSpinBox()
        for sp in (self._remap_new_min, self._remap_new_max):
            sp.setRange(-99.0, 99.0)
            sp.setDecimals(3)
            sp.setFixedWidth(68)
        self._remap_new_min.setValue(0.0)
        self._remap_new_max.setValue(1.0)
        new_row.addWidget(QtWidgets.QLabel('min'))
        new_row.addWidget(self._remap_new_min)
        new_row.addWidget(QtWidgets.QLabel('max'))
        new_row.addWidget(self._remap_new_max)
        new_row.addStretch()
        lay.addLayout(new_row)

        remap_btn = QtWidgets.QPushButton('Apply Remap')
        remap_btn.setFixedHeight(26)
        remap_btn.setStyleSheet(
            'QPushButton { background-color: #504040; color: white; }'
            'QPushButton:hover { background-color: #705050; }'
        )
        remap_btn.clicked.connect(self._on_remap_apply)
        lay.addWidget(remap_btn)

        return section

    def _build_storage_panel(self) -> QtWidgets.QWidget:
        """Compact square-button storage column (no title, top-right position)."""
        panel = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setSpacing(4)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setAlignment(QtCore.Qt.AlignTop)

        # Dynamic area — storage buttons are inserted here
        self._storage_layout = QtWidgets.QVBoxLayout()
        self._storage_layout.setSpacing(4)
        self._storage_layout.setContentsMargins(0, 0, 0, 0)
        self._storage_layout.setAlignment(QtCore.Qt.AlignTop)
        layout.addLayout(self._storage_layout)
        self._storage_buttons = []

        # [+] square button — always stays at the top
        self._add_storage_btn = QtWidgets.QPushButton('+')
        self._add_storage_btn.setFixedSize(20, 20)
        self._add_storage_btn.setToolTip(
            'Add a storage slot\n'
            'Left-click a slot to restore  |  Right-click for options'
        )
        self._add_storage_btn.clicked.connect(self._on_add_storage)
        layout.insertWidget(0, self._add_storage_btn)

        layout.addStretch()
        return panel

    def _build_deformer_group(self) -> QtWidgets.QGroupBox:
        grp = QtWidgets.QGroupBox('')
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        # --- Mode toggle + Refresh ---
        # Wrap radio buttons if there are too many using custom FlowLayout
        from dw_maya.dw_pyqt_utils.flow_layout import FlowLayout
        mode_wgt = QtWidgets.QWidget()
        mode_lay = FlowLayout(mode_wgt, margin=0, spacing=4)
        self._mode_group = QtWidgets.QButtonGroup(self)
        self._mode_btns = {}  # mode_key -> QRadioButton, for Pref menu visibility
        for label, mode in [('All', 'all'), ('Deformer', 'deformer'),
                             ('nCloth', 'nucleus'), ('vtxAlpha', 'vtxColor')]:
            btn = QtWidgets.QRadioButton(label)
            btn.setProperty('mode', mode)
            if mode == 'all':
                btn.setChecked(True)
            self._mode_group.addButton(btn)
            mode_lay.addWidget(btn)
            self._mode_btns[mode] = btn
        lay.addWidget(mode_wgt)

        # --- Mesh label + refresh button ---
        mesh_row = QtWidgets.QHBoxLayout()
        self._mesh_label = QtWidgets.QLabel('Nothing selected')
        self._mesh_label.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft)
        font = self._mesh_label.font()
        font.setBold(True)
        self._mesh_label.setFont(font)
        mesh_row.addWidget(self._mesh_label, stretch=1)

        refresh_btn = QtWidgets.QPushButton('↺')
        refresh_btn.setFixedSize(24, 24)
        refresh_btn.setToolTip('Update list from selection')
        refresh_btn.clicked.connect(self._on_refresh)
        mesh_row.addWidget(refresh_btn)
        lay.addLayout(mesh_row)

        # --- Single flat combo: one row per (source × map) pair ---
        # Each item stores (source_index, map_name) in QtCore.Qt.UserRole.
        # Non-default maps (blendshape targets, nucleus maps) are shown as
        # "nodeName › mapName"; single-map deformers just show "nodeName".
        self._source_combo = QtWidgets.QComboBox()
        self._source_combo.setMinimumWidth(220)
        self._source_combo.setToolTip('Select deformer / map to paint')
        lay.addWidget(self._source_combo)

        # --- BlendShape target combo (show only for blendShape nodes) ---
        self._bs_target_combo = QtWidgets.QComboBox()
        self._bs_target_combo.setMinimumWidth(220)
        self._bs_target_combo.setToolTip('BlendShape target map')
        self._bs_target_combo.hide()
        lay.addWidget(self._bs_target_combo)

        # --- Map type badge (nucleus only) ---
        self._map_type_label = QtWidgets.QLabel()
        self._map_type_label.setAlignment(QtCore.Qt.AlignCenter)
        self._map_type_label.setStyleSheet('font-size: 11px;')
        self._map_type_label.hide()
        lay.addWidget(self._map_type_label)

        # --- Copy / Paste ---
        cp_row = QtWidgets.QHBoxLayout()
        self._copy_btn = QtWidgets.QPushButton('Copy weights')
        self._paste_btn = QtWidgets.QPushButton('Paste weights')
        cp_row.addWidget(self._copy_btn)
        cp_row.addWidget(self._paste_btn)
        lay.addLayout(cp_row)


        # --- Envelope spinbox ---
        env_row = QtWidgets.QHBoxLayout()
        env_row.addWidget(QtWidgets.QLabel('envelope'))
        self._envelope_slider = QtWidgets.QDoubleSpinBox()
        self._envelope_slider.setRange(0.0, 1.0)
        self._envelope_slider.setDecimals(2)
        self._envelope_slider.setSingleStep(0.01)
        self._envelope_slider.setFixedWidth(70)
        env_row.addWidget(self._envelope_slider)
        env_row.addStretch()
        lay.addLayout(env_row)

        # --- Paint button ---
        self._paint_btn = QtWidgets.QPushButton('▶  Paint')
        self._paint_btn.setFixedHeight(32)
        self._paint_btn.setStyleSheet(
            'QPushButton { background-color: #a8a820; color: #1a1a00; font-weight: bold; }'
            'QPushButton:hover { background-color: #c8c830; }'
        )
        lay.addWidget(self._paint_btn)

        # --- Display range warning (shown only when weights outside 0-1) ---
        self._display_range_widget = QtWidgets.QWidget()
        dr_lay = QtWidgets.QVBoxLayout(self._display_range_widget)
        dr_lay.setContentsMargins(0, 2, 0, 0)
        dr_lay.setSpacing(2)

        dr_header = QtWidgets.QHBoxLayout()
        dr_label = QtWidgets.QLabel('⚠  Display range')
        dr_label.setStyleSheet('color: #e8a020; font-size: 11px;')
        dr_label.setToolTip(
            'Weights outside [0, 1] detected.\n'
            'The artisan color range will be set automatically on Paint.\n'
            'Adjust manually here if needed.'
        )
        dr_header.addWidget(dr_label)
        dr_header.addStretch()
        self._display_range_fit_btn = QtWidgets.QPushButton('Fit')
        self._display_range_fit_btn.setFixedSize(34, 18)
        self._display_range_fit_btn.setStyleSheet(
            'QPushButton { background-color: #3a3a2a; color: #cccc88; font-size: 10px; }'
            'QPushButton:hover { background-color: #4a4a32; }'
        )
        self._display_range_fit_btn.setToolTip('Fit range to actual weight min/max')
        dr_header.addWidget(self._display_range_fit_btn)
        dr_lay.addLayout(dr_header)

        self._display_range_slider = RangeSliderWithSpinbox(limit_min=0.0, limit_max=1.0, decimals=1)
        self._display_range_slider.setToolTip('Artisan colorrangelower / colorrangeupper — pushed on Paint')
        dr_lay.addWidget(self._display_range_slider)
        self._display_range_widget.hide()
        lay.addWidget(self._display_range_widget)

        # --- Alpha preview toggle (visible only for VertexColorAlpha sources) ---
        self._alpha_preview_btn = QtWidgets.QPushButton('👁  Alpha B&W preview')
        self._alpha_preview_btn.setCheckable(True)
        self._alpha_preview_btn.setFixedHeight(24)
        self._alpha_preview_btn.setStyleSheet(
            'QPushButton { background-color: #443355; color: #ccaaee; }'
            'QPushButton:hover { background-color: #554466; }'
            'QPushButton:checked { background-color: #775599; color: white; }'
        )
        self._alpha_preview_btn.setToolTip(
            'Toggle greyscale preview of the alpha channel in the viewport'
        )
        self._alpha_preview_btn.toggled.connect(self._on_alpha_preview_toggled)
        self._alpha_preview_btn.hide()
        lay.addWidget(self._alpha_preview_btn)

        return grp

    def _build_weights_group(self) -> QtWidgets.QGroupBox:
        grp = QtWidgets.QGroupBox('Weights')
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        set_row = QtWidgets.QHBoxLayout()
        self._set0_btn = QtWidgets.QPushButton('Set to 0')
        self._set0_btn.setStyleSheet('background-color: #282828; color: #aaaaaa;')
        self._set1_btn = QtWidgets.QPushButton('Set to 1')
        self._set1_btn.setStyleSheet('background-color: #bbbbbb; color: #111111;')
        set_row.addWidget(self._set0_btn)
        set_row.addWidget(self._set1_btn)
        lay.addLayout(set_row)

        # --- Operation mode radio buttons ---
        op_row = QtWidgets.QHBoxLayout()
        self._op_group = QtWidgets.QButtonGroup(self)
        for label, op in [('Replace', 'replace'), ('Add', 'add'), ('Multiply', 'multiply')]:
            btn = QtWidgets.QRadioButton(label)
            btn.setProperty('op', op)
            if op == 'replace':
                btn.setChecked(True)
            self._op_group.addButton(btn)
            op_row.addWidget(btn)
        op_row.addStretch()
        lay.addLayout(op_row)

        self._weight_slider = SliderWithButton(label='weight',
                                               btn_label='Set',
                                               default=0.5,
                                               decimals=2,
                                               step=0.01,
                                               label_width=48)
        lay.addWidget(self._weight_slider)

        # --- Clamp Widget ---
        clamp_row = QtWidgets.QHBoxLayout()
        clamp_row.setContentsMargins(0, 0, 0, 0)
        clamp_row.setSpacing(4)
        clamp_lbl = QtWidgets.QLabel('Clamp')
        clamp_lbl.setFixedWidth(40)

        self._clamp_min_check = QtWidgets.QCheckBox()
        self._clamp_min_check.setToolTip('Enable Min Clamp')

        self._clamp_slider = RangeSliderWithSpinbox(limit_min=0.0, limit_max=1.0, decimals=3)
        self._clamp_slider.setToolTip('Clamp Range')

        self._clamp_max_check = QtWidgets.QCheckBox()
        self._clamp_max_check.setToolTip('Enable Max Clamp')

        clamp_row.addWidget(clamp_lbl)
        clamp_row.addWidget(self._clamp_min_check)
        clamp_row.addWidget(self._clamp_slider, stretch=1)
        clamp_row.addWidget(self._clamp_max_check)
        lay.addLayout(clamp_row)

        return grp

    def _build_smooth_group(self) -> QtWidgets.QGroupBox:
        grp = QtWidgets.QGroupBox('Smooth  (paint tool must be active)')
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        # Warning label shown only for VertexColorAlpha (slow path)
        self._smooth_warn_label = QtWidgets.QLabel(
            '⚠'
        )
        self._smooth_warn_label.setToolTip("vertex alpha smooth is slow (~8 s per call)")
        self._smooth_warn_label.setStyleSheet('color: #e8a838; font-size: 11px;')
        self._smooth_warn_label.setWordWrap(True)
        self._smooth_warn_label.hide()
        lay.addWidget(self._smooth_warn_label)

        quick_row = QtWidgets.QHBoxLayout()
        for n in (2, 5, 10, 20):
            btn = QtWidgets.QPushButton(str(n))
            btn.setFixedWidth(44)
            btn.clicked.connect(partial(self._on_smooth, n))
            quick_row.addWidget(btn)
        quick_row.addStretch()
        lay.addLayout(quick_row)

        iter_row = QtWidgets.QHBoxLayout()
        iter_row.addWidget(QtWidgets.QLabel('iterations'))
        self._iter_spinbox = QtWidgets.QSpinBox()
        self._iter_spinbox.setRange(1, 200)
        self._iter_spinbox.setValue(25)
        self._iter_spinbox.setFixedWidth(52)
        iter_row.addWidget(self._iter_spinbox)

        self._iter_slider = QtWidgets.QSlider(Qt.Horizontal)
        self._iter_slider.setRange(1, 200)
        self._iter_slider.setValue(25)
        iter_row.addWidget(self._iter_slider, stretch=1)

        self._iter_slider.valueChanged.connect(self._iter_spinbox.setValue)
        self._iter_spinbox.valueChanged.connect(self._iter_slider.setValue)

        flood_btn = QtWidgets.QPushButton('Apply')
        flood_btn.setToolTip('Apply smooth N times to all vertices')
        flood_btn.clicked.connect(self._on_smooth_flood)
        iter_row.addWidget(flood_btn)
        lay.addLayout(iter_row)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel('via'))
        self._smooth_mode = QtWidgets.QComboBox()
        self._smooth_mode.addItems(['artisan (viewport)', 'numpy (selection-aware)'])
        self._smooth_mode.setToolTip(
            'artisan: flood all vertices via Maya brush (viewport feedback, no selection)\n'
            'numpy: topology smooth, respects vertex selection, applies clamp'
        )
        mode_row.addWidget(self._smooth_mode)
        mode_row.addStretch()
        lay.addLayout(mode_row)

        # Indeterminate busy bar — shown while smooth is computing
        self._smooth_busy_bar = QtWidgets.QProgressBar()
        self._smooth_busy_bar.setRange(0, 0)   # indeterminate
        self._smooth_busy_bar.setFixedHeight(6)
        self._smooth_busy_bar.setTextVisible(False)
        self._smooth_busy_bar.hide()
        lay.addWidget(self._smooth_busy_bar)

        return grp

    def _build_select_group(self) -> QtWidgets.QGroupBox:
        grp = QtWidgets.QGroupBox('Select vertices')
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        # ── Row 1 : All / Invert / Border ────────────────────────────────
        all_row = QtWidgets.QHBoxLayout()
        self._sel_all_btn = QtWidgets.QPushButton('All')
        self._sel_all_btn.setToolTip('Select all vertices of the active mesh')
        self._invert_btn = QtWidgets.QPushButton('Invert')
        self._invert_btn.setToolTip('Invert current vertex selection (always active)')
        self._border_btn = QtWidgets.QPushButton('Border')
        self._border_btn.setToolTip('Select border vertices')
        all_row.addWidget(self._sel_all_btn)
        all_row.addWidget(self._invert_btn)
        all_row.addWidget(self._border_btn)
        lay.addLayout(all_row)

        # ── Mode toggle ───────────────────────────────────────────────────
        mode_row = QtWidgets.QHBoxLayout()
        self._sel_mode_check = QtWidgets.QCheckBox('Value mode')
        self._sel_mode_check.setToolTip(
            'Unchecked = Range [lo, hi]\n'
            'Checked   = single Value ± tolerance'
        )
        mode_row.addWidget(self._sel_mode_check)
        mode_row.addStretch()
        lay.addLayout(mode_row)

        # ── Row 2a : Range mode — RangeSlider + Fit ──────────────────────
        #   [spin_min][══slider══][spin_max]  [⇥]
        self._range_slider_row_widget = QtWidgets.QWidget()
        slider_row = QtWidgets.QHBoxLayout(self._range_slider_row_widget)
        slider_row.setContentsMargins(0, 0, 0, 0)
        slider_row.setSpacing(3)

        self._range_sel = RangeSliderWithSpinbox(limit_min=0.0, limit_max=1.0, decimals=2)
        slider_row.addWidget(self._range_sel, stretch=1)

        self._range_fit_btn = QtWidgets.QPushButton('⇥')
        self._range_fit_btn.setFixedWidth(22)
        self._range_fit_btn.setFixedHeight(22)
        self._range_fit_btn.setToolTip('Fit limits to current min/max weights')
        slider_row.addWidget(self._range_fit_btn)
        lay.addWidget(self._range_slider_row_widget)

        # ── Row 2b : Range mode actions — Select / min / max ─────────────
        self._range_action_row_widget = QtWidgets.QWidget()
        range_action_row = QtWidgets.QHBoxLayout(self._range_action_row_widget)
        range_action_row.setContentsMargins(0, 0, 0, 0)
        range_action_row.setSpacing(3)

        self._sel_range_btn = QtWidgets.QPushButton('Select')
        self._sel_range_btn.setToolTip(
            'Select vertices in range (Shift=add, Ctrl=deselect, Ctrl+Shift=toggle)'
        )
        range_action_row.addWidget(self._sel_range_btn)

        self._sel_snap_min_btn = QtWidgets.QPushButton('min')
        self._sel_snap_min_btn.setFixedWidth(34)
        self._sel_snap_min_btn.setToolTip('Snap both handles to the lower limit')
        self._sel_snap_min_btn.setStyleSheet(
            'background-color: #282828; color: #aaaaaa; font-size: 10px;'
        )
        range_action_row.addWidget(self._sel_snap_min_btn)

        self._sel_snap_max_btn = QtWidgets.QPushButton('max')
        self._sel_snap_max_btn.setFixedWidth(34)
        self._sel_snap_max_btn.setToolTip('Snap both handles to the upper limit')
        self._sel_snap_max_btn.setStyleSheet(
            'background-color: #bbbbbb; color: #111111; font-size: 10px;'
        )
        range_action_row.addWidget(self._sel_snap_max_btn)
        lay.addWidget(self._range_action_row_widget)

        # ── Row 2c : Value mode — Select / value spinbox / ± tol ─────────
        #   [Select]  [0.50 ↕]  ±  [0.00 ↕]
        self._value_row_widget = QtWidgets.QWidget()
        value_row = QtWidgets.QHBoxLayout(self._value_row_widget)
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(3)

        self._sel_value_btn = QtWidgets.QPushButton('Select')
        self._sel_value_btn.setToolTip(
            'Select vertices equal to value ± tolerance\n'
            '(Shift=add, Ctrl=deselect, Ctrl+Shift=toggle)'
        )
        value_row.addWidget(self._sel_value_btn)

        self._sel_value_spin = QtWidgets.QDoubleSpinBox()
        self._sel_value_spin.setRange(-9999.0, 9999.0)
        self._sel_value_spin.setDecimals(2)
        self._sel_value_spin.setSingleStep(0.01)
        self._sel_value_spin.setValue(0.5)
        self._sel_value_spin.setFixedWidth(62)
        self._sel_value_spin.setToolTip('Target value')
        value_row.addWidget(self._sel_value_spin)

        # Tolerance slider + Select button in one composite widget
        self._sel_tol_slider = SliderWithButton(
            label='±',
            min_val=0.0,
            max_val=1.0,
            default=0.0,
            decimals=2,
            step=0.01,
            has_button=False)

        self._sel_tol_slider.setToolTip(
            'Tolerance (0 = exact match)\n'
            'Select vertices equal to value ± tolerance\n'
            '(Shift=add, Ctrl=deselect, Ctrl+Shift=toggle)'
        )
        value_row.addWidget(self._sel_tol_slider, stretch=1)

        lay.addWidget(self._value_row_widget)
        self._value_row_widget.hide()   # Range mode by default

        return grp

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        # Controller → UI
        self._signals.sources_changed.connect(self._on_sources_changed)
        self._signals.mesh_changed.connect(self._mesh_label.setText)
        self._signals.active_changed.connect(self._on_active_changed)

        # Mode toggle
        self._mode_group.buttonClicked.connect(self._on_mode_changed)

        # Flat source combo + blendShape target combo
        self._source_combo.currentIndexChanged.connect(self._on_source_combo_changed)
        self._bs_target_combo.currentIndexChanged.connect(self._on_bs_target_changed)

        # Deformer group
        self._copy_btn.clicked.connect(self._ctrl.copy_weights)
        self._paste_btn.clicked.connect(self._ctrl.paste_weights)
        self._paint_btn.clicked.connect(self._on_paint_clicked)
        self._envelope_slider.valueChanged.connect(self._on_envelope_changed)

        # Display range slider — live-push to artisan color range
        self._display_range_slider.range_changed.connect(
            lambda lo, hi: self._ctrl.set_artisan_color_range(lo, hi)
        )
        self._display_range_fit_btn.clicked.connect(self._refresh_display_range)

        # Weights group — Set 0/1 share the same op mode as the slider
        self._set0_btn.clicked.connect(partial(self._on_set_weight, 0.0))
        self._set1_btn.clicked.connect(partial(self._on_set_weight, 1.0))
        self._weight_slider.button_clicked.connect(self._on_set_weight)
        self._weight_slider.sliderReleased.connect(
            lambda: self._ctrl.set_artisan_value(self._weight_slider.value)
        )
        self._weight_slider.value_changed.connect(self._on_weight_slider_changed)

        # Clamp section
        self._clamp_slider.range_changed.connect(self._set_artisan_clamp)
        self._clamp_min_check.stateChanged.connect(self._set_artisan_clamp)
        self._clamp_max_check.stateChanged.connect(self._set_artisan_clamp)

        # Select group
        self._sel_all_btn.clicked.connect(self._on_select_all)
        self._invert_btn.clicked.connect(self._on_invert_selection)
        self._border_btn.clicked.connect(self._ctrl.border_selection)
        self._sel_range_btn.clicked.connect(self._on_select_by_range)
        self._sel_value_btn.clicked.connect(self._on_select_by_value)
        self._sel_snap_min_btn.clicked.connect(self._range_sel.snap_to_min)
        self._sel_snap_max_btn.clicked.connect(self._range_sel.snap_to_max)
        self._range_fit_btn.clicked.connect(self._on_range_fit)
        self._sel_mode_check.toggled.connect(self._on_sel_mode_toggled)


    # ------------------------------------------------------------------
    # QProperty — smooth iterations
    # ------------------------------------------------------------------

    def get_smooth_iterations(self) -> int:
        """Return the current smooth iteration count."""
        return self._iter_spinbox.value()

    def set_smooth_iterations(self, value: int) -> None:
        """Set the smooth iteration count (clamped to 1–200).

        Args:
            value: Number of smooth iterations.

        Example::

            widget.smooth_iterations = 10
        """
        self._iter_spinbox.setValue(max(1, min(200, value)))

    smooth_iterations = QtCore.Property(
        int,
        get_smooth_iterations,
        set_smooth_iterations,
        notify=smooth_iterations_changed,
    )

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_transfer_set_source(self) -> None:
        """Pre-fill the transfer source slot from the currently active deformer."""
        source = self._ctrl.active_source
        active_map = self._ctrl.active_map
        if source and active_map:
            self._transfer_src_btn.current_weight_node = f'{source.node_name}.{active_map}'
            self._transfer_src_btn.weight_source = source
            logger.debug(f"Transfer source set to {source.node_name}.{active_map}")
        else:
            logger.warning("No active source to set as transfer source.")

    @Slot()
    def _on_transfer_apply(self) -> None:
        """Execute the cross-topology weight transfer."""
        src_weights = self._transfer_src_btn.stored_weights
        if isinstance(src_weights, (list, tuple)):
            if isinstance(src_weights[0], (list, tuple)):
                src_weights = src_weights[0]

        if not src_weights:
            QtWidgets.QMessageBox.warning(
                self, 'Transfer',
                'Source slot is empty.\n'
                'Right-click the Src button and choose "Store weights", '
                'then come back and click Transfer.'
            )
            return
        src_ws = self._transfer_src_btn.weight_source
        if src_ws is None:
            QtWidgets.QMessageBox.warning(
                self, 'Transfer',
                'Source slot has no associated deformer.\n'
                'Use "← Active" to capture the source first.'
            )
            return
        tgt_ws = self._ctrl.active_source
        if tgt_ws is None:
            QtWidgets.QMessageBox.warning(
                self, 'Transfer',
                'No active target deformer.\n'
                'Select the target mesh, refresh, and pick a deformer.'
            )
            return
        self._ctrl.transfer_weights(src_weights, src_ws.mesh_name, tgt_ws)

    @Slot()
    def _on_remap_apply(self) -> None:
        """Apply remap/fit weight operation using the spinbox ranges."""
        self._ctrl.remap_weights(
            old_min=self._remap_old_min.value(),
            old_max=self._remap_old_max.value(),
            new_min=self._remap_new_min.value(),
            new_max=self._remap_new_max.value(),
        )

    @Slot(bool)
    def _on_storage_toggled(self, checked: bool) -> None:
        """Show or hide the storage panel and persist the user preference."""
        self._storage_panel.setVisible(checked)
        settings = QtCore.QSettings('DrWeeny', 'SlimfastWidget')
        settings.setValue('storage_expanded', checked)

    # ------------------------------------------------------------------
    # Session persistence for storage buttons  (DataHub — lives in-process)
    # ------------------------------------------------------------------
    def _save_storage_to_hub(self):
        """Serialise all storage button states into DataHubPub."""
        hub = data_hub.DataHubPub.Get()
        snapshot = [btn.to_dict() for btn in self._storage_buttons]
        hub.publish(self._HUB_KEY, snapshot, overwrite=True, notify=False)
        logger.debug(f"_save_storage_to_hub: saved {len(snapshot)} buttons")

    def _restore_storage_from_hub(self):
        """Re-create storage buttons from a previously saved DataHub snapshot."""
        hub = data_hub.DataHubPub.Get()
        snapshot = hub.retrieve(self._HUB_KEY)
        if not snapshot:
            return
        logger.debug(f"_restore_storage_from_hub: restoring {len(snapshot)} buttons")
        for data in snapshot:
            self._on_add_storage()                   # creates + appends a fresh button
            btn = self._storage_buttons[-1]
            btn.from_dict(data)                       # restores storage + label

    @Slot()
    def _on_add_storage(self) -> None:
        """Create a new VtxStorageButton slot below the existing ones."""
        btn = dw_maya.dw_pyqt_utils.dw_btn_storage.VtxStorageButton()
        slot_num = len(self._storage_buttons) + 1
        btn.setText(str(slot_num))
        btn.setFixedSize(40, 40)
        btn.setToolTip(f'Slot {slot_num}\nRight-click for options')

        # Pre-link to the currently active source so Store works immediately
        source = self._ctrl.active_source
        active_map = self._ctrl.active_map
        if source and active_map:
            btn.current_weight_node = f'{source.node_name}.{active_map}'
            btn.weight_source = source

        btn.remove_requested.connect(partial(self._on_remove_storage, btn))
        self._storage_layout.addWidget(btn)
        self._storage_buttons.append(btn)

    @Slot()
    def _on_remove_storage(self, btn: 'dw_maya.dw_pyqt_utils.dw_btn_storage.VtxStorageButton') -> None:
        """Remove a storage slot from the panel."""
        if btn in self._storage_buttons:
            self._storage_buttons.remove(btn)
            self._storage_layout.removeWidget(btn)
            btn.deleteLater()

    @Slot()
    def _on_refresh(self) -> None:
        self._ctrl.refresh()

    @Slot()
    def _on_pick_mesh(self) -> None:
        """Select the active mesh transform in the viewport."""
        source = self._ctrl.active_source
        if source:
            try:
                cmds.select(source.mesh_name, replace=True)
            except Exception as e:
                logger.warning(f"Could not select mesh: {e}")
        else:
            logger.warning("No active source — refresh first.")

    def _on_create_alpha_map(self) -> None:
        """Open a dialog to create a new vertex color alpha map on the selected mesh."""
        sel = cmds.ls(selection=True, transforms=True) or []
        if not sel:
            QtWidgets.QMessageBox.warning(
                self, 'Create alpha map',
                'Please select a mesh transform first.'
            )
            return

        mesh = sel[0]

        # Ask for the colorSet name
        name, ok = QtWidgets.QInputDialog.getText(
            self, 'New vertex alpha map',
            f'ColorSet name on "{mesh}":',
            QtWidgets.QLineEdit.Normal,
            'alphaMap',
        )
        if not ok or not name.strip():
            return

        # Ask for default fill value (0 = black, 1 = white)
        items = ['0.0  (black / empty)', '1.0  (white / full)']
        item, ok2 = QtWidgets.QInputDialog.getItem(
            self, 'Default value', 'Initial fill:', items, 0, False
        )
        if not ok2:
            return
        default_val = 0.0 if item.startswith('0') else 1.0

        try:
            create_alpha_map(mesh, color_set=name.strip(), default_value=default_val)
            logger.info(f"Alpha map '{name}' created on '{mesh}'.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, 'Create alpha map', str(e))
            return

        # Refresh so the new map appears in the source list
        self._on_refresh()

    def _on_mode_visibility_changed(self, mode_key: str, visible: bool) -> None:
        """Show/hide a mode radio button and fall back to 'All' if needed.

        If the currently checked button is being hidden, we automatically
        switch to the 'All' button so the tool stays functional.

        Args:
            mode_key: Mode identifier string (e.g. ``'nucleus'``).
            visible:  Whether the button should be visible.
        """
        btn = self._mode_btns.get(mode_key)
        if btn is None:
            return
        btn.setVisible(visible)
        # If the active button is hidden, fall back to 'All'
        if not visible and btn.isChecked():
            all_btn = self._mode_btns.get('all')
            if all_btn and all_btn.isVisible():
                all_btn.setChecked(True)
                self._ctrl.set_mode('all')

    @Slot(bool)
    def _on_alpha_preview_toggled(self, checked: bool) -> None:
        """Toggle B&W alpha preview on the active VertexColorAlpha source."""
        from dw_maya.dw_paint.vertex_color_alpha import VertexColorAlpha
        source = self._ctrl.active_source
        if not isinstance(source, VertexColorAlpha):
            return
        if checked:
            source.enable_preview()
        else:
            source.disable_preview()

    # ------------------------------------------------------------------
    # Source-type helpers
    # ------------------------------------------------------------------

    def _current_source_type_key(self) -> str:
        """Return a stable key for the currently active source type.

        Returns:
            ``'vtxColor'``, ``'nucleus'`` or ``'deformer'``.
        """
        src = self._ctrl.active_source
        if isinstance(src, VertexColorAlpha):
            return 'vtxColor'
        if isinstance(src, NClothMap):
            return 'nucleus'
        return 'deformer'

    def _current_op(self) -> str:
        """Return the currently selected weight operation mode."""
        checked = self._op_group.checkedButton()
        if checked:
            return checked.property('op') or 'replace'
        return 'replace'

    def _get_artisan_clamp(self) -> None:
        """Read standard Maya Paint context limits and update UI.

        Signals are blocked while the widgets are updated so that
        ``_set_artisan_clamp`` is NOT re-triggered (which would push the values
        back to the context creating a feedback loop).  After the widgets are
        set we explicitly call ``set_clamp_state`` on the controller so that
        subsequent numpy operations (flood, smooth) see the same values.
        """
        result = self._ctrl.get_artisan_clamp()
        if not result:
            return

        clamp_mode, lower_v, upper_v = result

        self._clamp_min_check.blockSignals(True)
        self._clamp_max_check.blockSignals(True)
        self._clamp_slider.blockSignals(True)

        self._clamp_min_check.setChecked(clamp_mode in ('lower', 'both'))
        self._clamp_max_check.setChecked(clamp_mode in ('upper', 'both'))
        self._clamp_slider.set_range(lower_v, upper_v)

        self._clamp_min_check.blockSignals(False)
        self._clamp_max_check.blockSignals(False)
        self._clamp_slider.blockSignals(False)

        # Sync controller stored state so numpy ops use the same limits
        self._ctrl.set_clamp_state(clamp_mode, lower_v, upper_v)


    def _set_artisan_clamp(self, *args) -> None:
        """Push UI limits down to Maya current Paint Context via controller."""
        if self._clamp_min_check.isChecked() and self._clamp_max_check.isChecked():
            clamp_mode = 'both'
        elif self._clamp_min_check.isChecked():
            clamp_mode = 'lower'
        elif self._clamp_max_check.isChecked():
            clamp_mode = 'upper'
        else:
            clamp_mode = 'none'

        cl = self._clamp_slider.low
        cu = self._clamp_slider.high

        self._ctrl.set_artisan_clamp(clamp_mode, cl, cu)

    @Slot(float)
    def _on_weight_slider_changed(self, value: float) -> None:
        """Sync artisan brush value live as the slider / spinbox moves.

        Called on every ``value_changed`` emission from the weight slider
        (both handle drag and spinbox edit).  We only push to the artisan
        context — the numpy flood is intentionally deferred to button click
        so we don't flood on every tick.
        """
        self._ctrl.set_artisan_value(value)

    @Slot()
    def _on_set_weight(self, value: float = None) -> None:
        """Relay value and op mode to the controller.

        Also syncs the artisan brush value so that the live paint tool and the
        UI buttons stay coherent — clicking "Set 0.3" makes the artisan brush
        also paint at 0.3 on the next stroke.

        Args:
            value: Explicit value (used by Set 0 / Set 1).
                   Falls back to the slider value when omitted.
        """
        if value is None:
            value = self._weight_slider.value
        self._ctrl.set_weight(value, self._current_op())
        # Keep artisan brush in sync with the last-used value
        self._ctrl.set_artisan_value(value)

    @Slot()
    def _on_set_weight(self, value: float = None) -> None:
        """Relay value and op mode to the controller.

        Args:
            value: Explicit value (used by Set 0 / Set 1).
                   Falls back to the slider value when omitted.
        """
        if value is None:
            value = self._weight_slider.value
        self._ctrl.set_weight(value, self._current_op())

    @Slot(int)
    def _on_tol_slider_changed(self, int_val: int) -> None:
        self._tol_spinbox.blockSignals(True)
        self._tol_spinbox.setValue(int_val / 100.0)
        self._tol_spinbox.blockSignals(False)

    @Slot(float)
    def _on_tol_spinbox_changed(self, float_val: float) -> None:
        self._tol_slider.blockSignals(True)
        self._tol_slider.setValue(int(float_val * 100))
        self._tol_slider.blockSignals(False)

    @Slot(int)
    def _on_bs_target_changed(self, index: int) -> None:
        """Activate the blendShape map selected in the secondary combo."""
        map_name = self._bs_target_combo.itemData(index)
        if map_name:
            self._ctrl.select_map(map_name)

    @Slot()
    def _on_invert_selection(self) -> None:
        self._ctrl.invert_selection()

    @Slot(QtWidgets.QAbstractButton)
    def _on_mode_changed(self, btn: QtWidgets.QAbstractButton) -> None:
        self._ctrl.set_mode(btn.property('mode'))

    # Colour palette per backend type
    _SOURCE_COLORS = {
        'nCloth':             '#4ecdc4',
        'nRigid':             '#4ecdc4',
        'blendShape':         '#e8a838',
        'skinCluster':        '#a0c8ff',
        'cluster':            '#cccccc',
        'softMod':            '#cccccc',
        'wire':               '#cccccc',
        'VertexColorAlpha':   '#cc88dd',
        'vtxColor':           '#cc88dd',
    }

    @Slot(list, list)
    def _on_sources_changed(self, node_labels: list, map_lists: list) -> None:
        """Rebuild the flat source combo from (node_labels, map_lists).

        Layout rules:
        - Single-map deformers (cluster, softMod, wire, …) → one row.
        - BlendShape → one row; available target maps go into _bs_target_combo
          which is shown/hidden by _on_source_combo_changed.
        - NClothMap → one row per map (nucleus maps are numerous).
        - A disabled separator row separates deformer and nucleus groups.

        UserRole  stores (source_idx, default_map_name).
        UserRole+1 stores (node_type, all_maps_list) for downstream logic.
        """
        self._source_model = QtGui.QStandardItemModel()

        if not node_labels:
            empty = QtGui.QStandardItem('— no sources —')
            empty.setEnabled(False)
            self._source_model.appendRow(empty)
            self._source_combo.blockSignals(True)
            self._source_combo.setModel(self._source_model)
            self._source_combo.blockSignals(False)
            self._bs_target_combo.hide()
            return

        nucleus_types = {'nCloth', 'nRigid'}

        def _type_from_label(lbl: str) -> str:
            if lbl.startswith('['):
                return lbl[1:lbl.index(']')]
            return ''

        types = [_type_from_label(lbl) for lbl in node_labels]
        has_deformer = any(t not in nucleus_types for t in types)
        separator_inserted = False
        first_selectable_row = None

        for source_idx, (label, maps, node_type) in enumerate(
                zip(node_labels, map_lists, types)):

            node_name = label.split('] ', 1)[-1] if '] ' in label else label
            color = self._SOURCE_COLORS.get(node_type, '#cccccc')

            # Separator before first nucleus entry
            if node_type in nucleus_types and not separator_inserted and has_deformer:
                sep = QtGui.QStandardItem('─── nCloth / nRigid ───')
                sep.setEnabled(False)
                sep.setForeground(QtGui.QBrush(QtGui.QColor('#555555')))
                self._source_model.appendRow(sep)
                separator_inserted = True

            if node_type == 'blendShape':
                # One row — target maps are handled by _bs_target_combo
                item = QtGui.QStandardItem(node_name)
                item.setData((source_idx, maps[0] if maps else 'weightList'), QtCore.Qt.UserRole)
                item.setData((node_type, maps), QtCore.Qt.UserRole + 1)
                item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
                self._source_model.appendRow(item)
                if first_selectable_row is None:
                    first_selectable_row = self._source_model.rowCount() - 1

            elif node_type in nucleus_types:
                # Nucleus: one row per map (many maps, no secondary combo)
                for map_name in maps:
                    display = f'{node_name}  › {map_name}'
                    item = QtGui.QStandardItem(display)
                    item.setData((source_idx, map_name), QtCore.Qt.UserRole)
                    item.setData((node_type, maps), QtCore.Qt.UserRole + 1)
                    item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
                    self._source_model.appendRow(item)
                    if first_selectable_row is None:
                        first_selectable_row = self._source_model.rowCount() - 1

            else:
                # Single-map deformer: one row, just the node name
                map_name = maps[0] if maps else 'weightList'
                item = QtGui.QStandardItem(node_name)
                item.setData((source_idx, map_name), QtCore.Qt.UserRole)
                item.setData((node_type, maps), QtCore.Qt.UserRole + 1)
                item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
                self._source_model.appendRow(item)
                if first_selectable_row is None:
                    first_selectable_row = self._source_model.rowCount() - 1

        self._source_combo.blockSignals(True)
        self._source_combo.setModel(self._source_model)
        if first_selectable_row is not None:
            self._source_combo.setCurrentIndex(first_selectable_row)
        self._source_combo.blockSignals(False)

        # Activate first entry — also handles BS combo show/hide
        if first_selectable_row is not None:
            self._on_source_combo_changed(first_selectable_row)

    @Slot(object)
    def _on_active_changed(self, source: Optional[WeightSource]) -> None:
        has_source = source is not None
        for w in (self._paint_btn, self._copy_btn, self._paste_btn,
                  self._set0_btn, self._set1_btn, self._weight_slider):
            w.setEnabled(has_source)

        # Keep storage buttons in sync with the currently active source/map
        # Only update current_weight_node (the "restore target").
        # Do NOT overwrite weight_source — it belongs to stored data.
        active_map = self._ctrl.active_map
        for btn in self._storage_buttons:
            if source and active_map:
                btn.current_weight_node = f'{source.node_name}.{active_map}'
            else:
                btn.current_weight_node = None

        # Update transfer section target label
        if source and active_map:
            self._transfer_tgt_label.setText(f'{source.node_name} › {active_map}')
        else:
            self._transfer_tgt_label.setText('— (active source) —')

        # --- Map type badge (nucleus only) ---
        if isinstance(source, NClothMap):
            _MAP_TYPE_INFO = {
                0: ('● None  (map disabled)', '#888888'),
                1: ('● PerVertex', '#4ecdc4'),
                2: ('● Texture', '#ddcc44'),
            }
            try:
                active_map = self._ctrl.active_map
                mt = source.map_type(active_map) if active_map else 0
                text, color = _MAP_TYPE_INFO.get(mt, (f'● type={mt}', '#aaaaaa'))
                self._map_type_label.setText(text)
                self._map_type_label.setStyleSheet(f'color: {color}; font-size: 11px;')
                self._map_type_label.show()
            except Exception:
                self._map_type_label.hide()
        else:
            self._map_type_label.hide()

        # --- Envelope spinbox ---
        if has_source and not isinstance(source, NClothMap):
            env_attr = f'{source.node_name}.envelope'
            if cmds.objExists(env_attr):
                try:
                    val = cmds.getAttr(env_attr)
                    self._envelope_slider.blockSignals(True)
                    self._envelope_slider.setValue(val)
                    self._envelope_slider.blockSignals(False)
                    self._envelope_slider.setEnabled(True)
                except Exception:
                    self._envelope_slider.setEnabled(False)
            else:
                self._envelope_slider.setEnabled(False)
        else:
            self._envelope_slider.setEnabled(False)

        # --- Alpha preview button (VertexColorAlpha only) ---
        if isinstance(source, VertexColorAlpha):
            self._alpha_preview_btn.show()
        else:
            # Disable preview if switching away from a vtxColor source
            if self._alpha_preview_btn.isChecked():
                self._alpha_preview_btn.setChecked(False)
            self._alpha_preview_btn.hide()

        # --- Display range banner ---
        self._refresh_display_range()

    def _refresh_display_range(self) -> None:
        """Read weight range from the active source and update the display range widget.

        - If weights are strictly inside [0, 1]: hide the banner and pre-set the
          slider to [0, 1] so Paint will reset Maya's color range to defaults.
        - If any weight falls outside [0, 1]: show the banner pre-filled with
          the detected ``(min, max)`` rounded to 1 decimal.
        """
        result = self._ctrl.get_weight_range()
        if result is None:
            self._display_range_widget.hide()
            return

        lo, hi = result
        is_normal = (lo >= 0.0 and hi <= 1.0)

        # Always keep the slider calibrated so _on_paint_clicked can read it
        self._display_range_slider.blockSignals(True)
        if is_normal:
            self._display_range_slider.set_limits(0.0, 1.0)
            self._display_range_slider.set_range(0.0, 1.0)
        else:
            # No padding — padding causes integer-precision drift in the slider
            # when the limits shift: int(to_norm(0.0) * 99) can round away from 0
            # producing a spurious -0.1 offset when the max handle is dragged.
            # The spinboxes already accept any typed value via auto-extend.
            self._display_range_slider.set_limits(
                min(lo, 0.0), max(hi, 1.0)
            )
            self._display_range_slider.set_range(lo, hi)
        self._display_range_slider.blockSignals(False)

        self._display_range_widget.setVisible(not is_normal)

    @Slot()
    def _on_paint_clicked(self) -> None:
        """Open the paint tool then apply the display colour range.

        ``paint()`` must run first so that the artisan context exists before
        we try to edit its ``colorrangelower`` / ``colorrangeupper`` flags.
        The display range slider is always read, even when the banner is
        hidden (it is pre-seeded to ``[0, 1]`` for normal-range maps so that
        stale Maya values left over from a previous session are reset).
        """
        self._ctrl.paint()
        lo = self._display_range_slider.low
        hi = self._display_range_slider.high
        self._ctrl.set_artisan_color_range(lo, hi)

    @Slot(int)
    def _on_source_combo_changed(self, combo_index: int) -> None:
        """Decode (source_idx, map_name) from the selected row and activate both.

        Also shows/hides and populates _bs_target_combo for blendShape nodes.
        """
        if combo_index < 0:
            return
        model = self._source_combo.model()
        if model is None:
            return
        item = model.item(combo_index)
        if item is None or not item.isEnabled():
            return
        data = item.data(QtCore.Qt.UserRole)
        if data is None:
            return
        source_idx, map_name = data
        # select_source already calls select_map(maps[0]) internally,
        # so only call select_map if we need a different map than the default.
        self._ctrl.select_source(source_idx)
        active_maps = self._ctrl.active_source.available_maps() if self._ctrl.active_source else []
        if active_maps and map_name != active_maps[0]:
            self._ctrl.select_map(map_name)

        # Show/populate blendShape target combo when needed
        extra = item.data(QtCore.Qt.UserRole + 1)
        node_type = extra[0] if extra else ''
        maps = extra[1] if extra else []
        if node_type == 'blendShape' and maps:
            self._bs_target_combo.blockSignals(True)
            self._bs_target_combo.clear()
            for m in maps:
                label = 'base weights' if m == 'weightList' else m
                self._bs_target_combo.addItem(label, m)
            self._bs_target_combo.blockSignals(False)
            self._bs_target_combo.show()
        else:
            self._bs_target_combo.hide()

    @Slot(object)
    def _on_active_changed(self, source: Optional[WeightSource]) -> None:
        has_source = source is not None
        for w in (self._paint_btn, self._copy_btn, self._paste_btn,
                  self._set0_btn, self._set1_btn, self._weight_slider):
            w.setEnabled(has_source)

        # Keep storage buttons in sync with the currently active source/map
        # Only update current_weight_node (the "restore target").
        # Do NOT overwrite weight_source — it belongs to stored data.
        active_map = self._ctrl.active_map
        for btn in self._storage_buttons:
            if source and active_map:
                btn.current_weight_node = f'{source.node_name}.{active_map}'
            else:
                btn.current_weight_node = None

        # Update transfer section target label
        if source and active_map:
            self._transfer_tgt_label.setText(f'{source.node_name} › {active_map}')
        else:
            self._transfer_tgt_label.setText('— (active source) —')

        # --- Map type badge (nucleus only) ---
        if isinstance(source, NClothMap):
            _MAP_TYPE_INFO = {
                0: ('● None  (map disabled)', '#888888'),
                1: ('● PerVertex', '#4ecdc4'),
                2: ('● Texture', '#ddcc44'),
            }
            try:
                active_map = self._ctrl.active_map
                mt = source.map_type(active_map) if active_map else 0
                text, color = _MAP_TYPE_INFO.get(mt, (f'● type={mt}', '#aaaaaa'))
                self._map_type_label.setText(text)
                self._map_type_label.setStyleSheet(f'color: {color}; font-size: 11px;')
                self._map_type_label.show()
            except Exception:
                self._map_type_label.hide()
        else:
            self._map_type_label.hide()

        # --- Envelope spinbox ---
        if has_source and not isinstance(source, NClothMap):
            env_attr = f'{source.node_name}.envelope'
            if cmds.objExists(env_attr):
                try:
                    val = cmds.getAttr(env_attr)
                    self._envelope_slider.blockSignals(True)
                    self._envelope_slider.setValue(val)
                    self._envelope_slider.blockSignals(False)
                    self._envelope_slider.setEnabled(True)
                except Exception:
                    self._envelope_slider.setEnabled(False)
            else:
                self._envelope_slider.setEnabled(False)
        else:
            self._envelope_slider.setEnabled(False)

        # --- Alpha preview button (VertexColorAlpha only) ---
        from dw_maya.dw_paint.vertex_color_alpha import VertexColorAlpha
        if isinstance(source, VertexColorAlpha):
            self._alpha_preview_btn.show()
        else:
            # Disable preview if switching away from a vtxColor source
            if self._alpha_preview_btn.isChecked():
                self._alpha_preview_btn.setChecked(False)
            self._alpha_preview_btn.hide()

        # --- Smooth mode: save previous type pref, restore for new type ---
        settings = QtCore.QSettings('DrWeeny', 'SlimfastWidget')
        # Persist smooth mode for the type we are leaving
        settings.setValue(f'smooth_mode_{self._src_type_key}',
                          self._smooth_mode.currentIndex())

        # Determine new type key and load its saved preference
        new_key = self._current_source_type_key()
        self._src_type_key = new_key
        # Default: vtxColor → numpy (index 1); others → artisan (index 0)
        default_mode = 1 if new_key == 'vtxColor' else 0
        saved_mode = settings.value(f'smooth_mode_{new_key}', default_mode, type=int)
        self._smooth_mode.blockSignals(True)
        self._smooth_mode.setCurrentIndex(saved_mode)
        self._smooth_mode.blockSignals(False)

        # Warning visibility
        self._smooth_warn_label.setVisible(new_key == 'vtxColor')

    @Slot(float)
    def _on_envelope_changed(self, value: float) -> None:
        source = self._ctrl.active_source
        if source and not isinstance(source, NClothMap):
            env_attr = f'{source.node_name}.envelope'
            if cmds.objExists(env_attr):
                try:
                    cmds.setAttr(env_attr, value)
                except Exception as e:
                    logger.warning(f"Could not set envelope: {e}")

    def _on_smooth(self, iterations: int) -> None:
        self._smooth_busy_bar.show()
        QtWidgets.QApplication.processEvents()
        try:
            if self._smooth_mode.currentIndex() == 0:
                try:
                    self._ctrl.smooth_artisan(iterations)
                except RuntimeError as e:
                    QtWidgets.QMessageBox.warning(self, 'Smooth', str(e))
            else:
                self._ctrl.smooth(iterations)
        finally:
            self._smooth_busy_bar.hide()

    def _on_smooth_flood(self) -> None:
        self._on_smooth(self._iter_spinbox.value())

    @Slot()
    def _on_advanced_apply(self) -> None:
        """Apply the selected advanced weight distribution operation."""
        mode = self._adv_mode_combo.currentText()
        falloff = self._adv_falloff_combo.currentText()
        invert = self._adv_invert_check.isChecked()

        if mode == 'vector':
            vec_mode = self._adv_vec_mode_combo.currentText()
            if vec_mode == 'normal':
                direction = 'y+'  # unused but required
            elif self._adv_custom_check.isChecked():
                direction = self._adv_custom_vec.text().strip()
            else:
                checked = self._adv_axis_group.checkedButton()
                direction = checked.property('axis') if checked else 'y+'
            self._ctrl.apply_vector_weights(direction, falloff=falloff,
                                            invert=invert, mode=vec_mode)
        elif mode == 'radial':
            cx = self._adv_center_x.value()
            cy = self._adv_center_y.value()
            cz = self._adv_center_z.value()
            center = (cx, cy, cz) if any((cx, cy, cz)) else None
            radius = self._adv_radius_spin.value() or None
            self._ctrl.apply_radial_weights(falloff=falloff, invert=invert,
                                            center=center, radius=radius)

    @Slot(str)
    def _on_adv_mode_changed(self, mode: str) -> None:
        """Show the relevant sub-widget for the selected advanced mode."""
        self._adv_vector_widget.setVisible(mode == 'vector')
        self._adv_radial_widget.setVisible(mode == 'radial')

    def _toggle_axis_buttons(self, checked: bool, enable: bool = False) -> None:
        """Enable or disable axis radio buttons (used when custom vector is active)."""
        for btn in self._adv_axis_group.buttons():
            btn.setEnabled(not checked)

    @Slot()
    def _on_pick_radial_center(self) -> None:
        """Fill center spinboxes from the current selection bounding box."""
        cx, cy, cz = self._ctrl.get_selection_center()
        self._adv_center_x.setValue(cx)
        self._adv_center_y.setValue(cy)
        self._adv_center_z.setValue(cz)

    @Slot()
    def _on_read_soft_select_radius(self) -> None:
        """Read the soft-selection distance and put it in the radius spinbox."""
        r = self._ctrl.get_soft_select_radius()
        if r > 0.0:
            self._adv_radius_spin.setValue(r)
        else:
            logger.warning("Soft selection is disabled or radius is 0.")

    def _on_select_all(self) -> None:
        self._ctrl.select_all(0)

    def _on_select_by_range(self) -> None:
        """Select vertices within [low, high] of the range slider."""
        mods = QtWidgets.QApplication.keyboardModifiers()
        self._ctrl.select_vertices_by_range(
            self._range_sel.low, self._range_sel.high,
            self._qt_mods_to_maya(mods)
        )

    def _on_select_by_value(self) -> None:
        """Select vertices equal to value ± tolerance."""
        mods = QtWidgets.QApplication.keyboardModifiers()
        val = self._sel_value_spin.value()
        tol = self._sel_tol_slider.value
        self._ctrl.select_vertices_by_range(val - tol, val + tol,
                                            self._qt_mods_to_maya(mods))

    def _on_range_fit(self) -> None:
        """Fit the range slider limits to the actual min/max of current weights."""
        w_min, w_max = self._ctrl.get_weight_range()
        if w_max <= w_min:
            w_max = w_min + 0.001
        self._range_sel.set_limits(w_min, w_max)
        self._range_sel.set_range(w_min, w_max)

    def _on_sel_mode_toggled(self, value_mode: bool) -> None:
        """Switch between Range and Value selection mode, persist to QSettings."""
        self._range_slider_row_widget.setVisible(not value_mode)
        self._range_action_row_widget.setVisible(not value_mode)
        self._value_row_widget.setVisible(value_mode)
        settings = QtCore.QSettings(self._org, self._appname)
        settings.setValue('sel_value_mode', value_mode)

    def _on_select_zero(self) -> None:
        mods = QtWidgets.QApplication.keyboardModifiers()
        self._ctrl.select_vertices_by_weight(
            from_zero=True,
            tolerance=self._tol_spinbox.value(),
            key_mod=self._qt_mods_to_maya(mods)
        )

    def _on_select_one(self) -> None:
        mods = QtWidgets.QApplication.keyboardModifiers()
        self._ctrl.select_vertices_by_weight(
            from_zero=False,
            tolerance=self._tol_spinbox.value(),
            key_mod=self._qt_mods_to_maya(mods)
        )

    @staticmethod
    def _qt_mods_to_maya(mods: QtCore.Qt.KeyboardModifiers) -> int:
        shift = bool(mods & QtCore.Qt.ShiftModifier)
        ctrl = bool(mods & QtCore.Qt.ControlModifier)
        if ctrl and shift:
            return 5
        if ctrl:
            return 4
        if shift:
            return 1
        return 0

    # ------------------------------------------------------------------
    # Help dialog
    # ------------------------------------------------------------------
    def enterEvent(self, event) -> None:
        """Called when mouse enters the widget bounding box.

        Soft-syncs the clamp UI from Maya's current artisan context, but
        throttled to at most once every ``_CLAMP_SYNC_INTERVAL`` seconds so
        the round-trip to Maya is cheap even when the cursor crosses the
        window border quickly.
        """
        super().enterEvent(event)
        import time
        now = time.monotonic()
        if now - getattr(self, '_last_clamp_sync', 0.0) >= self._CLAMP_SYNC_INTERVAL:
            self._last_clamp_sync = now
            self._get_artisan_clamp()

    def closeEvent(self, event) -> None:
        """Persist smooth iteration count and section/mode visibilities on close."""
        settings = QtCore.QSettings(self._org, self._appname)
        settings.setValue('smooth_iterations', self.get_smooth_iterations())
        # Global smooth mode preference (artisan vs numpy)
        settings.setValue('smooth_mode', self._smooth_mode.currentIndex())
        settings.setValue('adv_section_visible', self._advanced_section.isVisible())
        settings.setValue('transfer_section_visible', self._transfer_section.isVisible())
        settings.setValue('remap_section_visible', self._remap_section.isVisible())
        for mode_key, btn in self._mode_btns.items():
            settings.setValue(f'mode_visible_{mode_key}', btn.isVisible())
        self._save_storage_to_hub()
        super().closeEvent(event)

    def _show_help(self) -> None:
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle('Slimfast — help')
        msg.setText(
            "<b>Slimfast 2.0</b> — weight painting tool<br><br>"
            "<b>Mode toggle:</b> switch between deformer, nCloth, or both<br>"
            "<b>↺ Refresh:</b> re-scan selection for weight sources<br>"
            "<b>BlendShape:</b> a second combo appears for target maps<br>"
            "<b>Copy / Paste:</b> transfer weights between sources<br>"
            "<b>Paint:</b> open Maya artisan for the active source<br>"
            "<b>Set 0 / 1:</b> flood all vertices<br>"
            "<b>Weight slider → Set:</b> flood current selection<br>"
            "<b>Smooth:</b> artisan path needs paint tool active;<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;numpy path works any time<br>"
            "<b>Select ALL:</b> select all vertices of the active mesh<br>"
            "<b>Invert:</b> invert current component selection (always active)<br>"
            "<b>Weight = 0/1:</b><br>"
            "&nbsp;&nbsp;click = select<br>"
            "&nbsp;&nbsp;Ctrl+click = deselect<br>"
            "&nbsp;&nbsp;Shift+click = toggle<br>"
            "&nbsp;&nbsp;Ctrl+Shift+click = add<br>"
        )
        msg.exec()

    # ------------------------------------------------------------------
    # Class-level show helpers
    # ------------------------------------------------------------------

    @classmethod
    def _instance_alive(cls) -> bool:
        """Check if the singleton widget is still a valid C++ object."""
        if cls._instance is None:
            return False
        try:
            cls._instance.isVisible()
            return True
        except RuntimeError:
            cls._instance = None
            return False

    @classmethod
    def show_window(cls) -> 'SlimfastWidget':
        """Show as a floating window, reusing an existing instance."""
        if not cls._instance_alive():
            cls._instance = cls()
        cls._instance.show()
        cls._instance.raise_()
        cls._instance.activateWindow()
        return cls._instance

    @classmethod
    def show_docked(cls) -> 'SlimfastWidget':
        """Dock into Maya's right-side panel area."""
        widget = cls.show_window()
        # Maya's docking API wraps the widget in a workspaceControl
        try:
            ctrl_name = 'SlimfastWorkspaceControl'
            if cmds.workspaceControl(ctrl_name, exists=True):
                cmds.deleteUI(ctrl_name)
            cmds.workspaceControl(
                ctrl_name,
                label='Slimfast 2.0',
                retain=False,
                floating=False,
                dockToMainWindow=('right', False),
            )
            # Reparent our widget inside the workspace control
            workspace_ptr = omui.MQtUtil.findControl(ctrl_name)
            workspace_widget = wrapInstance(int(workspace_ptr), QtWidgets.QWidget)
            workspace_layout = workspace_widget.layout()
            if workspace_layout is None:
                workspace_layout = QtWidgets.QVBoxLayout(workspace_widget)
            workspace_layout.setContentsMargins(0, 0, 0, 0)
            workspace_layout.addWidget(widget)
        except Exception as e:
            logger.warning(f"Could not dock Slimfast: {e}. Showing as floating window.")
        return widget

if __name__ == '__main__':
    _instance = SlimfastWidget.show_window()


