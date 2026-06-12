"""
picker.py
---------
One-shot viewport vertex-weight picker (eyedropper).

Maya's ``artAttrCtx -pickValue`` flag has no completion callback, so a
caller can't tell whether the user picked a value or pressed Escape without
polling (QTimer / scriptJob / mouse-enter tricks). Swapping the active tool
for a ``draggerContext`` solves that, but ``setToolTo`` changes
``currentCtx()`` and drops the artAttrCtx-family viewport weight overlay.

This module instead installs a one-shot ``QApplication`` event filter that
catches the next viewport mouse press directly — Maya's current tool, and
therefore the weight-map overlay, is never touched. A ray is cast through
the click point using OpenMaya API2; if it hits the target mesh, the nearest
vertex of the hit face is resolved.

Functions:
    pick_vertex_weight: Activate the eyedropper for a mesh + weight list.

Author: DrWeeny
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from maya import cmds
import maya.api.OpenMaya as om2
import maya.api.OpenMayaUI as omui2

try:
    from PySide6 import QtCore, QtWidgets
    from shiboken6 import wrapInstance, getCppPointer
except ImportError:
    # Fallback for older Maya versions shipping PySide2
    from PySide2 import QtCore, QtWidgets
    from shiboken2 import wrapInstance, getCppPointer

from dw_maya.dw_paint.artisan_maya import get_artisan_radius, set_artisan_radius
from dw_maya.dw_paint.core.mesh_data import MeshDataFactory
from dw_logger import get_logger

logger = get_logger()

_MAX_RAY_DISTANCE = 1000000.0
_HINT_POSITION = 'topCenter'


def pick_vertex_weight(mesh_name: str,
                        weights: Sequence[float],
                        on_picked: Callable[[int, float], None],
                        on_cancel: Optional[Callable[[], None]] = None) -> None:
    """Activate a one-shot eyedropper for *mesh_name*'s vertex weights.

    Installs a global event filter that intercepts the next mouse press.
    A left-click inside a Maya viewport casts a ray through the click point;
    if it hits *mesh_name*, the nearest vertex of the hit face is resolved and
    ``on_picked(vertex_index, weight)`` is called with the matching entry
    from *weights*. Any other outcome (miss, non-left click, click outside a
    viewport, Escape) calls *on_cancel*. Maya's current tool is never changed,
    so the artisan viewport overlay stays visible throughout.

    Args:
        mesh_name: Transform or shape name of the mesh to pick from.
        weights:   Per-vertex weights, indexed by vertex id (e.g. the result
                   of ``WeightSource.get_weights()``).
        on_picked: Called with ``(vertex_index, weight_value)`` on a hit.
        on_cancel: Called with no arguments on miss / non-left-click / error.
    """
    app = QtWidgets.QApplication.instance()
    if app is None:
        logger.error("pick_vertex_weight: no QApplication instance")
        if on_cancel:
            on_cancel()
        return
    _ViewportPickFilter(app, mesh_name, weights, on_picked, on_cancel)


class _ViewportPickFilter(QtCore.QObject):
    """One-shot ``QApplication`` event filter for the next viewport click."""

    def __init__(self,
                 app: QtWidgets.QApplication,
                 mesh_name: str,
                 weights: Sequence[float],
                 on_picked: Callable[[int, float], None],
                 on_cancel: Optional[Callable[[], None]]) -> None:
        super().__init__(app)
        self._app = app
        self._mesh_name = mesh_name
        self._weights = weights
        self._on_picked = on_picked
        self._on_cancel = on_cancel
        app.installEventFilter(self)
        self._original_radius = _show_pick_hint()

    def eventFilter(self, obj, event) -> bool:
        event_type = event.type()
        if event_type == QtCore.QEvent.MouseButtonPress:
            return self._handle_press(event)
        if event_type == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
            self._stop()
            if self._on_cancel:
                self._on_cancel()
            return True
        return False

    def _stop(self) -> None:
        _clear_pick_hint(self._original_radius)
        self._app.removeEventFilter(self)
        self.deleteLater()

    def _handle_press(self, event) -> bool:
        """Resolve the click; return ``True`` to consume the event."""
        if event.button() != QtCore.Qt.LeftButton:
            self._stop()
            if self._on_cancel:
                self._on_cancel()
            return False

        view, x, y = _resolve_viewport(_event_global_pos(event))
        if view is None:
            self._stop()
            if self._on_cancel:
                self._on_cancel()
            return False

        self._stop()
        try:
            vtx_index = _closest_vertex_under_cursor(view, self._mesh_name, x, y)
        except Exception as e:
            logger.error(f"pick_vertex_weight: raycast on '{self._mesh_name}' failed: {e}")
            vtx_index = None

        if vtx_index is None or vtx_index >= len(self._weights):
            if self._on_cancel:
                self._on_cancel()
        else:
            self._on_picked(vtx_index, self._weights[vtx_index])
        return True


def _show_pick_hint() -> Optional[float]:
    """Switch to a crosshair cursor, collapse the brush gizmo, and show a viewport hint.

    Shrinking the brush radius to ``0`` while picking makes it visually
    obvious that the click won't paint. Returns the original radius (or
    ``None`` if it couldn't be read) so :func:`_clear_pick_hint` can restore it.
    """
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CrossCursor)
    original_radius = get_artisan_radius()
    if original_radius is not None:
        set_artisan_radius(0.0)
    try:
        cmds.inViewMessage(
            assistMessage='Click on the mesh to pick a weight value  (Esc to cancel)',
            position=_HINT_POSITION, fade=False)
    except Exception:
        pass
    return original_radius


def _clear_pick_hint(original_radius: Optional[float]) -> None:
    """Restore the cursor, brush radius, and clear the viewport hint."""
    QtWidgets.QApplication.restoreOverrideCursor()
    if original_radius is not None:
        set_artisan_radius(original_radius)
    try:
        cmds.inViewMessage(clear=_HINT_POSITION)
    except Exception:
        pass


def _event_global_pos(event) -> QtCore.QPoint:
    """Return *event*'s global position as a ``QPoint`` (PySide2/6 compat)."""
    if hasattr(event, 'globalPosition'):
        return event.globalPosition().toPoint()
    return event.globalPos()


def _resolve_viewport(global_pos: QtCore.QPoint):
    """Return ``(M3dView, x, y)`` for the viewport under *global_pos*.

    ``x``/``y`` are in Maya's screen-space convention (origin bottom-left).
    Returns ``(None, 0, 0)`` when *global_pos* is not over a model panel.
    """
    obj = QtWidgets.QApplication.widgetAt(global_pos)
    if obj is None:
        return None, 0, 0
    # QApplication.widgetAt() comes back typed as QObject in PySide2;
    # re-wrap as QWidget so isAncestorOf() accepts it below.
    widget = wrapInstance(int(getCppPointer(obj)[0]), QtWidgets.QWidget)

    for panel in cmds.getPanel(type='modelPanel') or []:
        try:
            view = omui2.M3dView.getM3dViewFromModelPanel(panel)
        except RuntimeError:
            continue
        ptr = view.widget()
        if not ptr:
            continue
        view_widget = wrapInstance(int(ptr), QtWidgets.QWidget)
        if view_widget is widget or view_widget.isAncestorOf(widget):
            local = view_widget.mapFromGlobal(global_pos)
            return view, local.x(), view_widget.height() - local.y()
    return None, 0, 0


def _closest_vertex_under_cursor(view: 'omui2.M3dView', mesh_name: str,
                                  x: int, y: int) -> Optional[int]:
    """Raycast from viewport point *(x, y)* and return the nearest vertex on *mesh_name*.

    Returns ``None`` when the ray misses the mesh.
    """
    ray_source = om2.MPoint()
    ray_direction = om2.MVector()
    view.viewToWorld(x, y, ray_source, ray_direction)

    fn_mesh = MeshDataFactory.get(mesh_name)._fn_mesh
    hit = fn_mesh.closestIntersection(
        om2.MFloatPoint(ray_source.x, ray_source.y, ray_source.z),
        om2.MFloatVector(ray_direction.x, ray_direction.y, ray_direction.z),
        om2.MSpace.kWorld, _MAX_RAY_DISTANCE, False,
    )
    if hit is None:
        return None

    hit_point = om2.MPoint(hit[0].x, hit[0].y, hit[0].z)
    hit_face = hit[2]

    best_id, best_dist = None, None
    for vid in fn_mesh.getPolygonVertices(hit_face):
        dist = (fn_mesh.getPoint(int(vid), om2.MSpace.kWorld) - hit_point).length()
        if best_dist is None or dist < best_dist:
            best_id, best_dist = int(vid), dist
    return best_id