"""Custom Qt widgets and utilities for DCC integration.

This module pop an error window with a gif
This module provides reusable Qt widgets and utilities that work across multiple
Digital Content Creation (DCC) applications including Maya, Houdini and standalone.

Features:
   - DCC window handling for Maya/Houdini
   - Custom error dialog with image support
   - Animated hover effects for widgets
   - Thumbnail widgets with hover animations
   - Interactive plotting widgets with draggable points/lines
   - Tree widget utilities

Classes:
   ErrorWin: Custom error dialog
   RectangleHoverEffect: Widget hover animation
   ThumbWidget: Thumbnail with hover effect
   PlotPoint: Interactive plot point
   PlotLine: Interactive Bezier curve
   PlotView: Custom plotting widget

DCC Support:
   MODE values:
       0: Standalone Qt
       1: Maya + PySide6
       2: Houdini + PySide6

Example:
   >>> # Create error dialog in Maya
   >>> error = ErrorWin(parent=get_maya_window())
   >>> error.show()

   >>> # Add hover effect to widget
   >>> effect = RectangleHoverEffect(widget, parent)

Author: DrWeeny
Version: 1.0.0
"""
MODE = 0

try:
    import hou
    from PySide6 import QtWidgets, QtGui, QtCore
    MODE = 2
except:
    pass

if not MODE > 0:
    try:
        import maya.OpenMayaUI as omui
        from shiboken6 import wrapInstance
        from PySide6 import QtWidgets, QtGui, QtCore# Changed for PySide6
        MODE = 1
    except:
        pass

if MODE == 0:
    from PySide6 import QtWidgets, QtGui, QtCore

from typing import Optional

def get_houdini_window():
    """
    Get Houdini window.
    Returns:
        pointer
    """
    win = hou.ui.mainQtWindow()
    return win

def get_maya_window():
    """
    Get Maya main window.
    Returns:
        pointer
    """
    return wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)  # Replace `long` with `int`

def get_all_treeitems(tree_widget):
    """Get all QTreeWidgetItems of a given QTreeWidget."""
    items = []
    iterator = QtWidgets.QTreeWidgetItemIterator(tree_widget)
    while iterator.value():
        item = iterator.value()
        items.append(item)
        iterator += 1
    return items

# ---------------------------------------------------------------------------- #
# -------------------------------- WIDGETS ----------------------------------- #

class ErrorWin(QtWidgets.QDialog):
    """Error window to display custom messages."""
    def __init__(self, img=None, parent=None):
        super().__init__(parent or get_maya_window())
        self.setObjectName("ErrorWin")
        self.setWindowTitle("Action Canceled: Vertex Animation Detected")
        self.resize(400, 100)

        layout = QtWidgets.QHBoxLayout(self)
        self.setLayout(layout)

        img_path = '/path/to/resources/pic_files'  # Update to a configurable resource path
        if not img:
            img = 'MasterYoda-Unlearn.jpg'

        pixmap = QtGui.QPixmap(f"{img_path}/{img}")
        label = QtWidgets.QLabel(self)
        label.setPixmap(pixmap)
        layout.addWidget(label)

        self.move(300, 200)

    def closeEvent(self, event):
        self.deleteLater()


class RectangleHoverEffect(QtCore.QObject):
    """Hover effect for a QWidget to move it in/out."""
    def __init__(self, rectangle, parent):
        super().__init__(parent)
        if not isinstance(rectangle, QtWidgets.QWidget):
            raise TypeError("rectangle must be a QWidget")
        if not rectangle.parent():
            raise ValueError("rectangle must have a parent")

        self.rectangle = rectangle
        self.animation = QtCore.QPropertyAnimation()
        self.animation.setTargetObject(rectangle)
        self.animation.setPropertyName(b"pos")
        self.animation.setDuration(300)
        self.animation.setEasingCurve(QtCore.QEasingCurve.OutQuad)
        rectangle.parent().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.rectangle.parent():
            start, end = obj.height(), obj.height() - self.rectangle.height()
            if event.type() == QtCore.QEvent.Enter:
                self._start_animation(start, end)
            elif event.type() == QtCore.QEvent.Leave:
                self._start_animation(end, start)
        return super().eventFilter(obj, event)

    def _start_animation(self, start, end):
        self.animation.setStartValue(QtCore.QPoint(0, start))
        self.animation.setEndValue(QtCore.QPoint(0, end))
        self.animation.start()

    def __del__(self):
        self.animation.stop()
        self.animation.deleteLater()


class ThumbWidget(QtWidgets.QFrame):
    """Custom thumbnail widget with hover effect and click signal."""
    clicked = QtCore.Signal()

    def __init__(self, title, pixmap, size=40, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)

        pixmap_label = QtWidgets.QLabel(self)
        pixmap_label.setPixmap(pixmap)
        pixmap_label.setScaledContents(True)

        title_label = QtWidgets.QLabel(title, self)
        title_label.setStyleSheet("color: #FFFFFF;")
        title_label.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(pixmap_label)
        layout.addWidget(title_label)

        RectangleHoverEffect(self, parent)

    def mousePressEvent(self, event):
        self.clicked.emit()


class PlotPoint(QtWidgets.QGraphicsRectItem):
    """Draggable and selectable plot point for custom graphics."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRect(-6, -6, 12, 12)
        self.setBrush(QtGui.QBrush(QtGui.QColor(255, 30, 30)))
        self.setPen(QtGui.QPen(QtGui.QColor(30, 30, 30), 2))


class PlotLine(QtWidgets.QGraphicsPathItem):
    """Bezier curve with draggable control points."""
    def __init__(self, start, end, parent=None):
        super().__init__(parent)
        self.start = start
        self.end = end
        self.update_path()

    def update_path(self):
        """Update the curve path based on control points."""
        path = QtGui.QPainterPath()
        path.moveTo(self.start)
        path.cubicTo(
            self.start + QtCore.QPointF(50, 0),
            self.end - QtCore.QPointF(50, 0),
            self.end,
        )
        self.setPath(path)


class PlotView(QtWidgets.QWidget):
    """Custom plot view for managing draggable lines and points."""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        self.scene = QtWidgets.QGraphicsScene(self)
        self.view = QtWidgets.QGraphicsView(self.scene, self)
        layout.addWidget(self.view)

class RangeSlider(QtWidgets.QSlider):
    """Custom double-handled range slider."""

    rangeChanged = QtCore.Signal(float, float)

    def __init__(self, orientation=QtCore.Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.first_position = 0
        self.second_position = 99
        self.setMinimum(0)
        self.setMaximum(99)

        self.offset = 10
        self.movement = 0
        self.isSliderDown = False

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            pos_x = event.pos().x()
            val = self.minimum() + ((self.maximum() - self.minimum()) * pos_x) / self.width()

            if abs(self.first_position - val) < abs(self.second_position - val):
                self.first_position = val
                self.movement = 1
            else:
                self.second_position = val
                self.movement = 2

            self.isSliderDown = True
            self.update()
            self._emit_range()

    def mouseMoveEvent(self, event):
        if self.isSliderDown:
            pos_x = event.pos().x()
            val = self.minimum() + ((self.maximum() - self.minimum()) * pos_x) / self.width()

            if self.movement == 1:
                self.first_position = max(0, min(val, self.second_position - 1))
            else:
                self.second_position = min(99, max(val, self.first_position + 1))

            self.update()
            self._emit_range()

    def mouseReleaseEvent(self, event):
        self.isSliderDown = False
        self.movement = 0

    def _emit_range(self):
        """Emit the current range as normalized values."""
        min_val = self.first_position / 99.0
        max_val = self.second_position / 99.0
        self.rangeChanged.emit(min_val, max_val)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        # Track
        track_rect = QtCore.QRect(
            self.offset, self.height() // 2 - 2,
                         self.width() - 2 * self.offset, 4
        )
        painter.fillRect(track_rect, QtGui.QColor(80, 80, 80))

        # Selected range
        x1 = int(self.offset + (self.first_position / 99.0) * (self.width() - 2 * self.offset))
        x2 = int(self.offset + (self.second_position / 99.0) * (self.width() - 2 * self.offset))

        range_rect = QtCore.QRect(x1, self.height() // 2 - 2, x2 - x1, 4)
        painter.fillRect(range_rect, QtGui.QColor(100, 180, 100))

        # Handles
        for pos in [self.first_position, self.second_position]:
            x = int(self.offset + (pos / 99.0) * (self.width() - 2 * self.offset))
            handle_rect = QtCore.QRect(x - 5, self.height() // 2 - 8, 10, 16)
            painter.setBrush(QtGui.QColor(200, 200, 200))
            painter.setPen(QtGui.QColor(100, 100, 100))
            painter.drawRoundedRect(handle_rect, 3, 3)

    def setRange(self, min_val: float, max_val: float):
        """Set range from normalized values (0-1)."""
        self.first_position = int(min_val * 99)
        self.second_position = int(max_val * 99)
        self.update()

class RangeSliderWithSpinbox(QtWidgets.QWidget):
    """Double-handle range slider flanked by two spinboxes.

    Layout::

        [spin_min] [══[▌]═══════[▐]══] [spin_max]

    Intentionally button-free so it composes freely in any parent layout.
    Typing a value outside the current limits **auto-extends** those limits.

    Signals:
        range_changed(float, float): Emitted on every handle / spinbox move.

    Args:
        limit_min: Lower bound (default ``0.0``).
        limit_max: Upper bound (default ``1.0``).
        decimals:  Decimal precision (default ``2``).
        parent:    Optional parent widget.

    Example::

        w = RangeSliderWithSpinbox(limit_min=0.0, limit_max=2.5)
        w.range_changed.connect(lambda lo, hi: print(lo, hi))
        w.set_limits(min_w, max_w)   # recalibrate from actual weights
    """

    range_changed = QtCore.Signal(float, float)

    def __init__(self,
                 limit_min: float = 0.0,
                 limit_max: float = 1.0,
                 decimals: int = 2,
                 parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        self._limit_min = limit_min
        self._limit_max = limit_max
        self._decimals = decimals
        self._syncing = False

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self._spin_min = QtWidgets.QDoubleSpinBox()
        self._spin_min.setDecimals(decimals)
        self._spin_min.setSingleStep(10 ** -decimals)
        self._spin_min.setFixedWidth(60)
        self._spin_min.setRange(-9999.0, 9999.0)   # wide open — limits are logical only
        self._spin_min.setToolTip('Lower bound — type to extend the range')
        layout.addWidget(self._spin_min)

        self._slider = RangeSlider(QtCore.Qt.Horizontal)
        self._slider.setMinimumHeight(22)
        layout.addWidget(self._slider, stretch=1)

        self._spin_max = QtWidgets.QDoubleSpinBox()
        self._spin_max.setDecimals(decimals)
        self._spin_max.setSingleStep(10 ** -decimals)
        self._spin_max.setFixedWidth(60)
        self._spin_max.setRange(-9999.0, 9999.0)   # wide open — limits are logical only
        self._spin_max.setToolTip('Upper bound — type to extend the range')
        layout.addWidget(self._spin_max)

        # Pre-seed spinbox values so set_limits clamps to the full range.
        # Block signals to avoid triggering _on_spin_*_changed before the
        # slider connections are wired — QDoubleSpinBox defaults to 0 which
        # would otherwise collapse both handles to the left.
        for sp, val in ((self._spin_min, limit_min), (self._spin_max, limit_max)):
            sp.blockSignals(True)
            sp.setValue(val)
            sp.blockSignals(False)
        self.set_limits(limit_min, limit_max)

        self._slider.rangeChanged.connect(self._on_slider_changed)
        self._spin_min.valueChanged.connect(self._on_spin_min_changed)
        self._spin_max.valueChanged.connect(self._on_spin_max_changed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_limits(self, limit_min: float, limit_max: float) -> None:
        """Recalibrate the logical slider bounds (does NOT restrict spinbox input).

        The spinboxes always accept any value in [-9999, 9999]; typing outside
        the current limits simply auto-extends them via the slot logic.
        """
        if limit_max <= limit_min:
            return
        self._limit_min = limit_min
        self._limit_max = limit_max
        self._push_to_slider()

    def set_range(self, lo: float, hi: float) -> None:
        """Set both handles programmatically, auto-extending limits if needed."""
        new_lim_min = min(lo, self._limit_min)
        new_lim_max = max(hi, self._limit_max)
        if new_lim_min < self._limit_min or new_lim_max > self._limit_max:
            self.set_limits(new_lim_min, new_lim_max)
        self._syncing = True
        self._spin_min.setValue(lo)
        self._spin_max.setValue(hi)
        self._syncing = False
        self._push_to_slider()
        self.range_changed.emit(self._spin_min.value(), self._spin_max.value())

    def snap_to_min(self) -> None:
        """Snap both handles to the current lower limit."""
        self.set_range(self._limit_min, self._limit_min)

    def snap_to_max(self) -> None:
        """Snap both handles to the current upper limit."""
        self.set_range(self._limit_max, self._limit_max)

    @property
    def low(self) -> float:
        return self._spin_min.value()

    @property
    def high(self) -> float:
        return self._spin_max.value()

    @property
    def limit_min(self) -> float:
        return self._limit_min

    @property
    def limit_max(self) -> float:
        return self._limit_max

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _to_norm(self, val: float) -> float:
        span = self._limit_max - self._limit_min
        return 0.0 if span == 0 else (val - self._limit_min) / span

    def _to_real(self, norm: float) -> float:
        return self._limit_min + norm * (self._limit_max - self._limit_min)

    def _push_to_slider(self) -> None:
        self._slider.first_position = int(self._to_norm(self._spin_min.value()) * 99)
        self._slider.second_position = int(self._to_norm(self._spin_max.value()) * 99)
        self._slider.update()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_slider_changed(self, lo_norm: float, hi_norm: float) -> None:
        if self._syncing:
            return
        self._syncing = True
        self._spin_min.setValue(self._to_real(lo_norm))
        self._spin_max.setValue(self._to_real(hi_norm))
        self._syncing = False
        self.range_changed.emit(self._spin_min.value(), self._spin_max.value())

    def _on_spin_min_changed(self, val: float) -> None:
        if self._syncing:
            return
        # Auto-extend lower logical limit
        if val < self._limit_min:
            self._limit_min = val
        # Prevent min > max
        if val > self._spin_max.value():
            self._syncing = True
            self._spin_min.setValue(self._spin_max.value())
            self._syncing = False
        self._push_to_slider()
        self.range_changed.emit(self._spin_min.value(), self._spin_max.value())

    def _on_spin_max_changed(self, val: float) -> None:
        if self._syncing:
            return
        # Auto-extend upper logical limit
        if val > self._limit_max:
            self._limit_max = val
        # Prevent max < min
        if val < self._spin_min.value():
            self._syncing = True
            self._spin_max.setValue(self._spin_min.value())
            self._syncing = False
        self._push_to_slider()
        self.range_changed.emit(self._spin_min.value(), self._spin_max.value())