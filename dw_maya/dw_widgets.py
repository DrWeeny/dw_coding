import sys, os
import math
from functools import partial

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import os.path

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
        from shiboken6 import wrapInstance  # Changed for PySide6
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

def get_all_treeitems(QTreeWidget):
    """ Get all QTreeWidgetItem of given QTreeWidget
        :param QTreeWidget: QTreeWidget object
        :return: All QTreeWidgetItem list
        :rtype: list """
    items = []
    iterator = QtWidgets.QTreeWidgetItemIterator.All
    all_items = QtWidgets.QTreeWidgetItemIterator(QTreeWidget, iterator) or None
    if all_items is not None:
        while all_items.value():
            item = all_items.value()
            items.append(item)
            all_items += 1
    return items

class ErrorWin(QtWidgets.QDialog):
    def __init__(self, img=None, parent=get_maya_window()):
        super(ErrorWin, self).__init__(parent)
        self.setObjectName("MyWindow")
        self.resize(400, 100)
        self.setWindowTitle("Action Canceled: Vertex Animation Detected")
        hbox = QtWidgets.QHBoxLayout(self)
        img_path = rdPath + '/../../resources/pic_files'
        if not img:
            img = 'MasterYoda-Unlearn.jpg'

        pixmap = QtGui.QPixmap(os.path.join(img_path, img))

        lbl = QtWidgets.QLabel(self)
        lbl.setPixmap(pixmap)

        hbox.addWidget(lbl)
        self.setLayout(hbox)

        self.move(300, 200)
        self.show()

    def closeEvent(self, event):
        self.deleteLater()
class RectangleHoverEffect(QtCore.QObject):
    """ Take QWidget and move it in/out on hover event """

    def __init__(self, rectangle, parent):
        super(RectangleHoverEffect, self).__init__(parent)
        if not isinstance(rectangle, QtWidgets.QWidget):
            raise TypeError("{} must be a QWidget".format(rectangle))
        if rectangle.parent() is None:
            raise ValueError("{} must have a parent".format(rectangle))
        self.m_rectangle = rectangle
        self.m_rectangle.parent().installEventFilter(self)
        self.m_animation = QtCore.QPropertyAnimation(
            self,
            targetObject=self.m_rectangle,
            propertyName=b"pos",
            duration=300,
            easingCurve=QtCore.QEasingCurve.OutQuad,
        )

    def eventFilter(self, obj, event):
        if self.m_rectangle.isValid():
            if self.m_rectangle.parent() is obj:
                y0 = self.m_rectangle.parent().height()
                y1 = self.m_rectangle.parent().height() - self.m_rectangle.height()

                if event.type() == QtCore.QEvent.Enter:
                    self._start_animation(y0, y1)
                elif event.type() == QtCore.QEvent.Leave:
                    self._start_animation(y1, y0)
        return QtCore.QObject.eventFilter(self, obj, event)

    def _start_animation(self, y0, y1):
        self.m_animation.setStartValue(QtCore.QPoint(0, y0))
        self.m_animation.setEndValue(QtCore.QPoint(0, y1))
        self.m_animation.start()


class ThumbWidget(QtWidgets.QFrame):
    clicked = QtCore.Signal()

    def __init__(self, title, pixmap, size=40, parent=None):
        super(ThumbWidget, self).__init__(parent)

        scale = 2
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setFrameShadow(QtWidgets.QFrame.Raised)

        pixmap_label = QtWidgets.QLabel(pixmap=pixmap, scaledContents=True)

        title_label = QtWidgets.QLabel(title)
        title_label.setStyleSheet("""color: #FFFFFF""")
        title_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        title_label.setFixedSize(self.width() / scale, size / scale)

        font = QtGui.QFont()
        font.setFamily("SF Pro Display")
        font.setPointSize(6)
        title_label.setFont(font)
        title_label.setWordWrap(True)

        self.background_label = QtWidgets.QLabel(pixmap_label)
        self.background_label.setStyleSheet("background: #32353B;")
        self.background_label.setFixedSize(size, size/scale)
        self.background_label.move(0, self.height()/2)

        background_lay = QtWidgets.QVBoxLayout(self.background_label)
        background_lay.addWidget(title_label)
        background_lay.setContentsMargins(0, 0, 0, 0)
        background_lay.setSpacing(0)

        self.setFixedSize(size, size)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(pixmap_label)

        effect = RectangleHoverEffect(self.background_label, self)

    def mousePressEvent(self, event):
        self.clicked.emit()


class PlotPoint(QtWidgets.QGraphicsRectItem):

    def __init__(self, parent=None):
        super().__init__(parent)  # Use Python 3 syntax for super()
        self.setAcceptHoverEvents(True)
        self.setFlag(self.ItemSendsScenePositionChanges, True)
        self.setFlag(self.ItemIsSelectable, True)
        self.setFlag(self.ItemIsMovable, True)
        self.setRect(-6, -6, 12, 12)
        self.setPen(QtGui.QPen(QtGui.QColor(30,30,30), 2, QtCore.Qt.SolidLine))
        self.setBrush(QtGui.QBrush(QtGui.QColor(255,30,30)))

    def itemChange(self, change, value):
        if change == self.ItemScenePositionHasChanged:
            if isinstance(self.parentItem(), PlotLine):
                self.parentItem().updatePath()
        return super().itemChange(change, value)


class PlotLine(QtWidgets.QGraphicsPathItem):

    def __init__(self, startPoint, endPoint, parent=None):
        super().__init__(parent)
        self._start_point = startPoint
        self._end_point = endPoint

        self._hover = False
        self.setAcceptHoverEvents(True)
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable)
        self.setFlag(QtWidgets.QGraphicsItem.ItemSendsScenePositionChanges)
        self.setZValue(-100)
        self.updatePath()

    def updatePath(self):
        points = [self._start_point]
        for child in self.childItems():
            if isinstance(child, PlotPoint):
                points.append(child.pos())
        points.append(self._end_point)
        sorted_points = sorted(points, key=partial(PlotLine.percentageByPoint, self.path()))
        self.setPath(PlotLine.getBezierPath(sorted_points))

    def paint(self, painter, option, widget):
        painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform | QtGui.QPainter.HighQualityAntialiasing, True)
        pen = QtGui.QPen(QtGui.QColor(170, 170, 170), 2, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
        if self.isSelected():
            pen.setColor(QtGui.QColor(255, 255, 255))
        elif self._hover:
            pen.setColor(QtGui.QColor(255, 30, 30))
        painter.setPen(pen)
        painter.drawPath(self.path())

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            item = PlotPoint(parent=self)
            item.setPos(event.pos())

    def hoverEnterEvent(self, event):
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def shape(self):
        qp = QtGui.QPainterPathStroker()
        qp.setWidth(15)
        qp.setCapStyle(QtCore.Qt.SquareCap)
        return qp.createStroke(self.path())

    @staticmethod
    def getBezierPath(points=[], curving=1.0):
        # Calculate Bezier Line
        path = QtGui.QPainterPath()
        curving = 1.0  # range 0-1
        if len(points) < 2:
            return path
        path.moveTo(points[0])
        for i in range(len(points) - 1):
            startPoint = points[i]
            endPoint = points[i + 1]
            # use distance as multiplier, closer nodes => less bezier curve
            dist = math.hypot(endPoint.x() - startPoint.x(), endPoint.y() - startPoint.y())
            # multiply distance by 0.375
            offset = dist * 0.375 * curving
            ctrlPt1 = startPoint + QtCore.QPointF(offset, 0)
            ctrlPt2 = endPoint + QtCore.QPointF(-offset, 0)
            path.cubicTo(ctrlPt1, ctrlPt2, endPoint)
        return path

    @staticmethod
    def percentageByPoint(path, point, precision=0.5):
        t = 0.0
        distances = []
        while t <= 100.0:
            distances.append(QtGui.QVector2D(point - path.pointAtPercent(t / 100.0)).length())
            t += precision
        percentage = distances.index(min(distances)) * precision
        return percentage


class PlotView(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        main_layout = QtWidgets.QVBoxLayout()

        self.scene = QtWidgets.QGraphicsScene(self)  # Ensure the scene has a parent
        self.view = QtWidgets.QGraphicsView(self.scene)
        self.view.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)
        self.view.setCacheMode(QtWidgets.QGraphicsView.CacheBackground)
        self.view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.view.setRenderHint(QtGui.QPainter.Antialiasing)
        self.view.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)

        # Add line to scene
        self.line = PlotLine(QtCore.QPointF(-150, 150), QtCore.QPointF(250, -150))
        self.scene.addItem(self.line)

        main_layout.addWidget(self.view)
        self.setLayout(main_layout)

    def mousePressEvent(self, event):
        scene_pos = self.view.mapToScene(event.pos())
        item_at_pos = self.scene.itemAt(scene_pos, QtGui.QTransform())  # Correct method to get scene items
        if item_at_pos is None:
            self._current_rect_item = PlotPoint()
            self.scene.addItem(self._current_rect_item)  # Ensure to add the item to the scene
            self._start = scene_pos
            self._current_rect_item.setPos(self._start)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene_pos = self.view.mapToScene(event.pos())
        if self._current_rect_item is not None:
            r = QtCore.QRectF(self._start, scene_pos).normalized()
            self._current_rect_item.setRect(r)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._current_rect_item = None
        super().mouseReleaseEvent(event)

