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

