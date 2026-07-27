"""Minimal draggable ramp/curve editor widget.

Classes:
    RampCurveWidget — 0-1 x 0-1 piecewise curve editor with per-point
                      handle type (linear / smooth).

Example::

    ramp = RampCurveWidget()
    ramp.curveChanged.connect(lambda pts: print(pts))
    control_points = ramp.control_points
    # [(0.0, 0.0, 'linear'), (0.5, 0.8, 'smooth'), (1.0, 1.0, 'linear')]

Author: DrWeeny
"""

try:
    from PySide6 import QtCore, QtGui, QtWidgets

    def _qt_exec(obj, *args, **kwargs):
        return obj.exec(*args, **kwargs)
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

    def _qt_exec(obj, *args, **kwargs):
        return obj.exec_(*args, **kwargs)

from typing import List, Optional, Tuple, Union

# Minimum x-distance kept between two neighbouring points (prevents a
# degenerate/duplicate x that would make the curve ambiguous).
_MIN_X_GAP = 0.01
_POINT_RADIUS = 5
_HIT_RADIUS = 9
_CURVE_SAMPLES_PER_SEGMENT = 24  # only used for 'smooth' segments

# (x, y, interp) — interp is 'linear' | 'smooth', applied to the segment
# starting at this point.
ControlPoint = Tuple[float, float, str]


def _ease(t: float) -> float:
    """Smoothstep ease (3t^2 - 2t^3) — matches dw_paint.utils.falloff's 'smooth'."""
    return t * t * (3 - 2 * t)


class RampCurveWidget(QtWidgets.QWidget):
    """Piecewise curve editor over a 0-1 x 0-1 grid, with per-point handle type.

    Left-click empty space to add a point (default handle: linear). Drag a
    point to move it (endpoints are locked to x=0 / x=1, only their y is
    draggable). Double-click a point to remove it (endpoints cannot be
    removed). Right-click a point for a context menu to switch its handle
    type between Linear and Smooth, or delete it.
    """

    curveChanged = QtCore.Signal(list)  # emits control_points on every change

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(90)
        self.setMinimumWidth(120)
        self.setMouseTracking(True)
        self.setToolTip(
            'Click = add point | Drag = move | Double-click = remove\n'
            'Right-click a point = handle type (Linear / Smooth) or delete'
        )
        # Sorted by x. Endpoints always present at x=0 and x=1.
        self._points: List[ControlPoint] = [(0.0, 0.0, 'linear'), (1.0, 1.0, 'linear')]
        self._drag_index: Optional[int] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def control_points(self) -> List[ControlPoint]:
        """Current control points, sorted by x, as ``(x, y, interp)`` triples."""
        return list(self._points)

    @control_points.setter
    def control_points(self,
                       points: List[Union[Tuple[float, float], ControlPoint]]) -> None:
        if not points:
            return
        pts = sorted(
            ((float(p[0]), float(p[1]), p[2] if len(p) > 2 else 'linear') for p in points),
            key=lambda p: p[0],
        )
        pts[0] = (0.0, pts[0][1], pts[0][2])
        pts[-1] = (1.0, pts[-1][1], pts[-1][2])
        self._points = pts
        self.update()

    def reset(self) -> None:
        """Reset to the default linear ramp (0,0) -> (1,1)."""
        self._points = [(0.0, 0.0, 'linear'), (1.0, 1.0, 'linear')]
        self.update()
        self.curveChanged.emit(self.control_points)

    # ------------------------------------------------------------------
    # Coordinate mapping (widget px <-> 0-1 curve space, y flipped)
    # ------------------------------------------------------------------

    def _to_widget(self, x: float, y: float) -> QtCore.QPointF:
        w = self.width()
        h = self.height()
        return QtCore.QPointF(x * w, h - y * h)

    def _to_curve(self, pos: QtCore.QPointF) -> Tuple[float, float]:
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        x = min(max(pos.x() / w, 0.0), 1.0)
        y = min(max(1.0 - pos.y() / h, 0.0), 1.0)
        return x, y

    def _point_at(self, pos: QtCore.QPointF) -> Optional[int]:
        for i, (x, y, _interp) in enumerate(self._points):
            wp = self._to_widget(x, y)
            if (wp - pos).manhattanLength() <= _HIT_RADIUS:
                return i
        return None

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        painter.fillRect(self.rect(), QtGui.QColor(30, 30, 30))

        # Grid
        grid_pen = QtGui.QPen(QtGui.QColor(60, 60, 60))
        painter.setPen(grid_pen)
        for frac in (0.25, 0.5, 0.75):
            y = self.height() * (1.0 - frac)
            painter.drawLine(QtCore.QPointF(0, y), QtCore.QPointF(self.width(), y))
            x = self.width() * frac
            painter.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, self.height()))

        # Curve — straight segment for 'linear', sampled ease curve for 'smooth'
        curve_pen = QtGui.QPen(QtGui.QColor(200, 200, 80), 2)
        painter.setPen(curve_pen)
        path = QtGui.QPainterPath()
        path.moveTo(self._to_widget(*self._points[0][:2]))
        for i in range(len(self._points) - 1):
            x0, y0, interp = self._points[i]
            x1, y1, _next_interp = self._points[i + 1]
            if interp == 'smooth':
                for s in range(1, _CURVE_SAMPLES_PER_SEGMENT + 1):
                    t = s / _CURVE_SAMPLES_PER_SEGMENT
                    x = x0 + t * (x1 - x0)
                    y = y0 + _ease(t) * (y1 - y0)
                    path.lineTo(self._to_widget(x, y))
            else:
                path.lineTo(self._to_widget(x1, y1))
        painter.drawPath(path)

        # Points — smooth handles drawn in a distinct color from linear ones
        for x, y, interp in self._points:
            wp = self._to_widget(x, y)
            color = QtGui.QColor(140, 210, 230) if interp == 'smooth' else QtGui.QColor(230, 230, 140)
            painter.setBrush(color)
            painter.setPen(QtGui.QPen(QtGui.QColor(20, 20, 20)))
            painter.drawEllipse(wp, _POINT_RADIUS, _POINT_RADIUS)

        painter.end()

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        pos = event.position() if hasattr(event, 'position') else event.localPos()
        idx = self._point_at(pos)

        if event.button() == QtCore.Qt.RightButton:
            if idx is not None:
                self._show_point_menu(idx, event.globalPosition().toPoint()
                                      if hasattr(event, 'globalPosition')
                                      else event.globalPos())
            return

        if idx is not None:
            self._drag_index = idx
            return

        # Add a new point at the click location
        x, y = self._to_curve(pos)
        self._insert_point(x, y)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        pos = event.position() if hasattr(event, 'position') else event.localPos()
        idx = self._point_at(pos)
        self._remove_point(idx)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._drag_index is None:
            return
        pos = event.position() if hasattr(event, 'position') else event.localPos()
        x, y = self._to_curve(pos)

        n = len(self._points)
        if self._drag_index == 0:
            x = 0.0
        elif self._drag_index == n - 1:
            x = 1.0
        else:
            lo = self._points[self._drag_index - 1][0] + _MIN_X_GAP
            hi = self._points[self._drag_index + 1][0] - _MIN_X_GAP
            x = min(max(x, lo), hi) if lo <= hi else self._points[self._drag_index][0]

        interp = self._points[self._drag_index][2]
        self._points[self._drag_index] = (x, y, interp)
        self.update()
        self.curveChanged.emit(self.control_points)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._drag_index = None

    # ------------------------------------------------------------------
    # Context menu — handle type / delete
    # ------------------------------------------------------------------

    def _show_point_menu(self, idx: int, global_pos: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        act_linear = menu.addAction('Linear')
        act_smooth = menu.addAction('Smooth')
        act_linear.setCheckable(True)
        act_smooth.setCheckable(True)
        current_interp = self._points[idx][2]
        act_linear.setChecked(current_interp == 'linear')
        act_smooth.setChecked(current_interp == 'smooth')

        is_endpoint = idx == 0 or idx == len(self._points) - 1
        act_delete = None
        if not is_endpoint:
            menu.addSeparator()
            act_delete = menu.addAction('Delete point')

        chosen = _qt_exec(menu, global_pos)
        if chosen is act_linear:
            self._set_point_interp(idx, 'linear')
        elif chosen is act_smooth:
            self._set_point_interp(idx, 'smooth')
        elif act_delete is not None and chosen is act_delete:
            self._remove_point(idx)

    def _set_point_interp(self, idx: int, interp: str) -> None:
        x, y, _old = self._points[idx]
        self._points[idx] = (x, y, interp)
        self.update()
        self.curveChanged.emit(self.control_points)

    # ------------------------------------------------------------------
    # Point list maintenance
    # ------------------------------------------------------------------

    def _insert_point(self, x: float, y: float) -> None:
        # Keep clear of existing points on x to avoid a degenerate segment.
        for px, _py, _interp in self._points:
            if abs(px - x) < _MIN_X_GAP:
                return
        self._points.append((x, y, 'linear'))
        self._points.sort(key=lambda p: p[0])
        self.update()
        self.curveChanged.emit(self.control_points)

    def _remove_point(self, idx: Optional[int]) -> None:
        if idx is None or idx == 0 or idx == len(self._points) - 1:
            return  # endpoints are locked
        del self._points[idx]
        self.update()
        self.curveChanged.emit(self.control_points)