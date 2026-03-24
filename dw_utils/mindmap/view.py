"""
MindMapView — QGraphicsView with zoom, pan, minimap and rubber-band selection.

Classes

- MindMapView:  Viewport with Ctrl+wheel zoom, space-drag pan, minimap overlay.
- MinimapOverlay: Small QWidget rendered inside the view showing the full graph.

"""

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QBrush
from PySide6.QtWidgets import QGraphicsView, QWidget

from dw_utils.mindmap.constants import (
    MINIMAP_WIDTH, MINIMAP_HEIGHT,
)
from dw_utils.mindmap.items import NodeItem, EdgeItem

from dw_logger import get_logger
log = get_logger()


class MinimapOverlay(QWidget):
    """
    A translucent thumbnail of the full scene rendered as a corner overlay.
    Updated only when the scene signals a change — no polling timer.

    Attributes:
        view: The parent MindMapView this minimap mirrors.
    """

    def __init__(self, view):
        super().__init__(view)
        self._view    = view
        self._enabled = True
        self.setFixedSize(MINIMAP_WIDTH, MINIMAP_HEIGHT)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(Qt.SubWindow)
        self._move_to_corner()

    def _move_to_corner(self):
        vr = self._view.rect()
        self.move(vr.width() - self.width() - 10,
                  vr.height() - self.height() - 10)

    def resizeEvent(self, event):
        self._move_to_corner()

    def paintEvent(self, event):
        if not self._enabled:
            return
        scene = self._view.scene()
        if scene is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Background panel
        bg_color  = QColor(20, 20, 40, 200)
        bg_brush  = QBrush(bg_color)
        bdr_color = QColor(100, 100, 150)
        bdr_pen   = QPen(bdr_color, 1)
        painter.setBrush(bg_brush)
        painter.setPen(bdr_pen)
        mw = float(self.width())
        mh = float(self.height())
        painter.drawRoundedRect(QRectF(0.0, 0.0, mw, mh), 6.0, 6.0)

        # Scale from scene coords to minimap coords
        sr      = scene.sceneRect()
        sr_w    = sr.width()
        sr_h    = sr.height()
        sr_x    = sr.x()
        sr_y    = sr.y()
        pad     = 4.0
        usable_w = mw - pad
        usable_h = mh - pad
        if sr_w <= 0 or sr_h <= 0:
            painter.end()
            return
        scale   = min(usable_w / sr_w, usable_h / sr_h)
        off_x   = pad * 0.5 + (usable_w - sr_w * scale) * 0.5
        off_y   = pad * 0.5 + (usable_h - sr_h * scale) * 0.5

        # Draw edges — use plain float arithmetic, only create QPointF at the end
        edge_pen = QPen(QColor(80, 80, 120), 1)
        painter.setPen(edge_pen)
        for edge in scene.all_edges():
            src_sp  = edge.source.scenePos()
            tgt_sp  = edge.target.scenePos()
            sc_x    = off_x + (src_sp.x() + edge.source.width  * 0.5 - sr_x) * scale
            sc_y    = off_y + (src_sp.y() + edge.source.height * 0.5 - sr_y) * scale
            tc_x    = off_x + (tgt_sp.x() + edge.target.width  * 0.5 - sr_x) * scale
            tc_y    = off_y + (tgt_sp.y() + edge.target.height * 0.5 - sr_y) * scale
            sc_pt   = QPointF(sc_x, sc_y)
            tc_pt   = QPointF(tc_x, tc_y)
            painter.drawLine(sc_pt, tc_pt)

        # Draw nodes
        for node in scene.all_nodes():
            nsp   = node.scenePos()
            nx    = off_x + (nsp.x() - sr_x) * scale
            ny    = off_y + (nsp.y() - sr_y) * scale
            nw    = max(4.0, node.width  * scale)
            nh    = max(3.0, node.height * scale)
            nc    = QColor(node.bg_color)
            nb    = QBrush(nc)
            nbc   = QColor(node.border_color)
            nbp   = QPen(nbc, 0.5)
            nr    = QRectF(nx, ny, nw, nh)
            painter.setBrush(nb)
            painter.setPen(nbp)
            painter.drawRoundedRect(nr, 2.0, 2.0)

        # Viewport rectangle
        vp      = self._view.viewport().rect()
        vp_tl   = vp.topLeft()
        vp_br   = vp.bottomRight()
        tl_s    = self._view.mapToScene(vp_tl)
        br_s    = self._view.mapToScene(vp_br)
        tl_mx   = off_x + (tl_s.x() - sr_x) * scale
        tl_my   = off_y + (tl_s.y() - sr_y) * scale
        br_mx   = off_x + (br_s.x() - sr_x) * scale
        br_my   = off_y + (br_s.y() - sr_y) * scale
        vp_rect = QRectF(QPointF(tl_mx, tl_my), QPointF(br_mx, br_my))
        vp_pc   = QColor(255, 220, 80, 200)
        vp_pen  = QPen(vp_pc, 1.5)
        vp_fc   = QColor(255, 220, 80, 30)
        vp_brs  = QBrush(vp_fc)
        painter.setPen(vp_pen)
        painter.setBrush(vp_brs)
        painter.drawRect(vp_rect)

        painter.end()


class MindMapView(QGraphicsView):
    """
    QGraphicsView with zoom, pan and minimap for the mind map.

    Signals:
        zoom_changed(float): Emitted with the new zoom factor.
        background_clicked(float, float): Emitted with scene x, y when the
            user clicks empty space (plain floats — no QPointF in signal).
    """

    zoom_changed       = QtCore.Signal(float)
    # Emit floats instead of QPointF — avoids value-type GC in signal delivery
    background_clicked = QtCore.Signal(float, float)

    ZOOM_MIN = 0.08
    ZOOM_MAX = 5.0

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)

        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._zoom          = 1.0
        self._panning       = False
        self._pan_start_x   = 0
        self._pan_start_y   = 0
        self._space_pressed = False

        # Minimap — updated via scene_changed signal, NOT a polling timer
        self._minimap = MinimapOverlay(self)

    def connect_scene_signals(self, scene):
        """Call after the scene is set to wire minimap updates to scene changes."""
        scene.scene_changed.connect(self._minimap.update)
        scene.scene_changed.connect(self._minimap.update)

    # ── zoom ──────────────────────────────────────────────────────────────────

    @property
    def zoom_level(self):
        return self._zoom

    def set_zoom(self, factor):
        factor = max(self.ZOOM_MIN, min(self.ZOOM_MAX, factor))
        if abs(factor - self._zoom) < 1e-6:
            return
        ratio      = factor / self._zoom
        self._zoom = factor
        self.scale(ratio, ratio)
        self.zoom_changed.emit(self._zoom)
        self._minimap.update()

    def fit_all(self):
        """Fit the entire graph in the viewport."""
        scene = self.scene()
        if not scene:
            return
        nodes = scene.all_nodes()
        if not nodes:
            self.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)
            return
        # Use plain floats — never chain .pos().x() directly
        xs, ys, x2s, y2s = [], [], [], []
        for n in nodes:
            p = n.pos()
            px, py = p.x(), p.y()
            xs.append(px)
            ys.append(py)
            x2s.append(px + n.width)
            y2s.append(py + n.height)
        br = QRectF(min(xs) - 40.0, min(ys) - 40.0,
                    max(x2s) - min(xs) + 80.0,
                    max(y2s) - min(ys) + 80.0)
        self.fitInView(br, Qt.KeepAspectRatio)
        self._zoom = self.transform().m11()
        self.zoom_changed.emit(self._zoom)

    def reset_zoom(self):
        self.resetTransform()
        self._zoom = 1.0
        self.zoom_changed.emit(self._zoom)

    # ── events ────────────────────────────────────────────────────────────────

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta  = event.angleDelta().y()
            factor = 1.12 if delta > 0 else 1.0 / 1.12
            self.set_zoom(self._zoom * factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_pressed = True
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.viewport().setCursor(Qt.OpenHandCursor)
        elif event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            sc = self.scene()
            if sc:
                sc.delete_selection()
        elif event.key() == Qt.Key_A and event.modifiers() & Qt.ControlModifier:
            self.scene().select_all()
        elif event.key() == Qt.Key_C and event.modifiers() & Qt.ControlModifier:
            self.scene().copy_selection()
        elif event.key() == Qt.Key_V and event.modifiers() & Qt.ControlModifier:
            # If clipboard contains an image AND a node is selected → attach image
            cb  = QtWidgets.QApplication.clipboard()
            pm  = cb.pixmap()
            if pm.isNull():
                img = cb.image()
                if not img.isNull():
                    from PySide6.QtGui import QPixmap
                    pm = QPixmap.fromImage(img)
            sel_nodes = [
                i for i in self.scene().selectedItems()
                if isinstance(i, NodeItem)
            ]
            if not pm.isNull() and sel_nodes:
                # Paste image onto all selected nodes
                from dw_utils.mindmap.dialogs import _pixmap_to_base64
                b64 = _pixmap_to_base64(pm)
                for node in sel_nodes:
                    old = node.to_dict()
                    new = dict(old)
                    new["attachment"] = b64
                    self.scene().edit_node(node, new)
                self.scene().status_message.emit(
                    f"Image pasted onto {len(sel_nodes)} node(s)."
                )
            else:
                # No image in clipboard — fall back to node paste
                self.scene().paste()
        elif event.key() == Qt.Key_Z and event.modifiers() & Qt.ControlModifier:
            self.scene().undo_stack.undo()
        elif event.key() == Qt.Key_Y and event.modifiers() & Qt.ControlModifier:
            self.scene().undo_stack.redo()
        elif event.key() == Qt.Key_F:
            self.fit_all()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_pressed = False
            self.setDragMode(QGraphicsView.RubberBandDrag)
            self.viewport().setCursor(Qt.ArrowCursor)
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            p = event.pos()
            self._panning     = True
            self._pan_start_x = p.x()
            self._pan_start_y = p.y()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.LeftButton:
            # emit floats, not QPointF
            vp        = event.pos()
            sp        = self.mapToScene(vp)
            sp_x      = sp.x()
            sp_y      = sp.y()
            sp_pt     = QPointF(sp_x, sp_y)
            items     = self.scene().items(sp_pt)
            if not any(isinstance(i, (NodeItem, EdgeItem)) for i in items):
                self.background_clicked.emit(sp_x, sp_y)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            p     = event.pos()
            cur_x = p.x()
            cur_y = p.y()
            # Use plain ints — no QPoint arithmetic
            dx = cur_x - self._pan_start_x
            dy = cur_y - self._pan_start_y
            self._pan_start_x = cur_x
            self._pan_start_y = cur_y
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - dx
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - dy
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = False
            cur = Qt.OpenHandCursor if self._space_pressed else Qt.ArrowCursor
            self.viewport().setCursor(cur)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._minimap._move_to_corner()

    def contextMenuEvent(self, event):
        """Right-click context menu on empty space or node."""
        vp         = event.pos()
        sp         = self.mapToScene(vp)
        sp_x       = sp.x()
        sp_y       = sp.y()
        sp_pt      = QPointF(sp_x, sp_y)
        items      = self.scene().items(sp_pt)
        node_items = [i for i in items if isinstance(i, NodeItem)]

        menu = QtWidgets.QMenu(self)

        if not node_items:
            act_add = menu.addAction("Add Node Here")
            act_add.triggered.connect(
                lambda _=False, x=sp_x, y=sp_y:
                    self.scene().create_node(pos=QPointF(x, y))
            )
        else:
            node = node_items[0]

            act_edge = menu.addAction("Start Edge From Here")
            act_edge.triggered.connect(lambda _=False, n=node: self.scene().start_edge_from(n))

            menu.addSeparator()

            act_copy_style = menu.addAction("Copy Style")
            act_copy_style.triggered.connect(
                lambda _=False, n=node: self.scene().copy_node_style(n)
            )

            has_style = bool(self.scene()._style_clipboard)
            act_paste_style = menu.addAction("Paste Style")
            act_paste_style.setEnabled(has_style)
            act_paste_style.triggered.connect(
                lambda _=False, n=node: self.scene().paste_node_style(n)
            )

            menu.addSeparator()

            act_del = menu.addAction("Delete Node")
            act_del.triggered.connect(lambda _=False, n=node: (
                n.setSelected(True),
                self.scene().delete_selection(),
            ))

        menu.exec_(event.globalPos())

