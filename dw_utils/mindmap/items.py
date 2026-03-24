"""
NodeItem and EdgeItem — QGraphicsItem subclasses for the CFX Mind Map.

Classes

- NodeItem:  Renderable node with shape, text, colour and resize handle.
- EdgeItem:  Bezier-curve edge connecting two NodeItems.

"""

import math
import uuid

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QPointF, QRectF, QObject, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QColor, QPen, QBrush, QPainterPath, QPainter, QFont, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem

from dw_utils.mindmap.constants import (
    DEFAULT_NODE_WIDTH, DEFAULT_NODE_HEIGHT, DEFAULT_BG_COLOR,
    DEFAULT_BORDER_COLOR, DEFAULT_TEXT_COLOR, DEFAULT_FONT_SIZE,
    DEFAULT_OPACITY, DEFAULT_BORDER_WIDTH,
    DEFAULT_EDGE_COLOR, DEFAULT_EDGE_WIDTH, DEFAULT_EDGE_STYLE,
    DEFAULT_EDGE_DIRECTED, DEFAULT_EDGE_LABEL,
    SHAPE_ROUNDED_RECT, SHAPE_ELLIPSE, SHAPE_DIAMOND,
    SHAPE_HEXAGON, SHAPE_PARALLELOGRAM, SHAPE_RECT,
    Z_NODE, Z_EDGE, Z_SELECTED,
    EDGE_DASHED, EDGE_DOTTED,
)

# ──────────────────────────────────────────────────────────────────────────────
# Signal carrier — separate QObject because QGraphicsObject crashes on hover
# in PySide6 6.8.x when boundingRect()/shape() are overridden in Python.
# ──────────────────────────────────────────────────────────────────────────────

class _NodeSignals(QObject):
    """
    Companion QObject that owns signals for NodeItem.

    PySide6 crashes when subclassing QGraphicsObject (QObject + QGraphicsItem)
    and overriding boundingRect()/shape() — shiboken frees the return value
    before Qt C++ finishes using it.  Plain QGraphicsItem avoids this; signals
    live here instead.
    """
    node_moved          = QtCore.Signal(str)
    node_selected       = QtCore.Signal(str)
    node_double_clicked = QtCore.Signal(str)
    node_resized        = QtCore.Signal(str)


# ──────────────────────────────────────────────────────────────────────────────
# NodeItem
# ──────────────────────────────────────────────────────────────────────────────

class NodeItem(QGraphicsItem):
    """
    A single node on the mind-map canvas.

    Signals are on ``self.signals`` (_NodeSignals).  Connect like::

        node.signals.node_moved.connect(my_slot)
    """

    HANDLE_SIZE = 8

    def __init__(
        self,
        label        = "Node",
        body_text    = "",
        shape        = SHAPE_ROUNDED_RECT,
        bg_color     = DEFAULT_BG_COLOR,
        border_color = DEFAULT_BORDER_COLOR,
        text_color   = DEFAULT_TEXT_COLOR,
        font_size    = DEFAULT_FONT_SIZE,
        width        = DEFAULT_NODE_WIDTH,
        height       = DEFAULT_NODE_HEIGHT,
        opacity      = DEFAULT_OPACITY,
        border_width = DEFAULT_BORDER_WIDTH,
        category     = "",
        node_id      = None,
        parent       = None,
    ):
        super().__init__(parent)

        # companion signal carrier — must be kept as instance attribute
        self.signals      = _NodeSignals()

        self.node_id      = node_id or str(uuid.uuid4())
        self.label        = label
        self.body_text    = body_text
        self.node_shape   = shape   # named node_shape to avoid collision with shape() method
        self.bg_color     = bg_color
        self.border_color = border_color
        self.text_color   = text_color
        self.font_size    = font_size
        self._width       = float(width)
        self._height      = float(height)
        self.category     = category
        self.border_width = float(border_width)

        self._hover          = False
        self._resize_handle  = False
        self._resizing       = False
        self._resize_start_x = 0.0
        self._resize_start_y = 0.0
        self._resize_orig_w  = self._width
        self._resize_orig_h  = self._height

        # Image attachment — stored as base64 PNG string, rendered as QPixmap
        self.attachment      = ""        # base64 PNG string, empty = no image
        self._pixmap         = None      # QPixmap, rebuilt when attachment changes

        self.setOpacity(opacity)
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
            | QGraphicsItem.ItemSendsScenePositionChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(Z_NODE)

        # Cached geometry — MUST be instance attributes, MUST be mutated
        # in-place (never replaced).  Qt C++ holds a raw pointer to the object
        # returned by boundingRect()/shape(); replacing it creates a dangling
        # pointer → crash.
        self._bounding_rect = QRectF()
        self._shape_path    = QPainterPath()
        self._rebuild_geometry()

    # ── geometry ──────────────────────────────────────────────────────────────

    @property
    def width(self):
        return self._width

    @property
    def height(self):
        return self._height

    def _rebuild_geometry(self):
        """Update cached bounding rect and shape path IN-PLACE."""
        pad = max(self.border_width, self.HANDLE_SIZE * 0.5) + 2.0
        # setRect mutates — keeps the same Python object Qt already knows
        self._bounding_rect.setRect(
            -pad, -pad,
            self._width  + pad * 2.0,
            self._height + pad * 2.0,
        )
        # clear() + repopulate — same object, different contents
        self._shape_path.clear()
        nw = self._width
        nh = self._height
        cx = nw * 0.5
        cy = nh * 0.5

        if self.node_shape == SHAPE_RECT:
            self._shape_path.addRect(QRectF(0.0, 0.0, nw, nh))

        elif self.node_shape == SHAPE_ELLIPSE:
            self._shape_path.addEllipse(QRectF(0.0, 0.0, nw, nh))

        elif self.node_shape == SHAPE_DIAMOND:
            p0 = QPointF(cx, 0.0);  p1 = QPointF(nw, cy)
            p2 = QPointF(cx, nh);   p3 = QPointF(0.0, cy)
            self._shape_path.moveTo(p0); self._shape_path.lineTo(p1)
            self._shape_path.lineTo(p2); self._shape_path.lineTo(p3)
            self._shape_path.closeSubpath()

        elif self.node_shape == SHAPE_HEXAGON:
            hw = nw * 0.5
            pts = [
                QPointF(cx - hw*0.5, 0.0), QPointF(cx + hw*0.5, 0.0),
                QPointF(cx + hw, cy),      QPointF(cx + hw*0.5, nh),
                QPointF(cx - hw*0.5, nh),  QPointF(cx - hw, cy),
            ]
            self._shape_path.moveTo(pts[0])
            for p in pts[1:]:
                self._shape_path.lineTo(p)
            self._shape_path.closeSubpath()

        elif self.node_shape == SHAPE_PARALLELOGRAM:
            off = nw * 0.15
            pts = [
                QPointF(off, 0.0), QPointF(nw, 0.0),
                QPointF(nw - off, nh), QPointF(0.0, nh),
            ]
            self._shape_path.moveTo(pts[0])
            for p in pts[1:]:
                self._shape_path.lineTo(p)
            self._shape_path.closeSubpath()

        else:  # SHAPE_ROUNDED_RECT (default)
            self._shape_path.addRoundedRect(QRectF(0.0, 0.0, nw, nh), 10.0, 10.0)

    def boundingRect(self):
        return self._bounding_rect

    def shape(self):
        return self._shape_path

    # ── attachment helpers ────────────────────────────────────────────────────

    def set_attachment(self, base64_png: str):
        """Store a base64-encoded PNG and rebuild the cached QPixmap."""
        self.attachment = base64_png
        if base64_png:
            ba  = QByteArray.fromBase64(base64_png.encode("ascii"))
            pm  = QPixmap()
            pm.loadFromData(ba, "PNG")
            self._pixmap = pm if not pm.isNull() else None
        else:
            self._pixmap = None
        # Image may change required height — let scene know geometry changed
        self.prepareGeometryChange()
        self._rebuild_geometry()
        self.update()

    def clear_attachment(self):
        """Remove the attached image."""
        self.set_attachment("")

    def _image_height(self) -> float:
        """Height reserved for the image inside the node (0 if none)."""
        if self._pixmap and not self._pixmap.isNull():
            # Scale to node width, keep aspect ratio
            scale = self._width / max(self._pixmap.width(), 1)
            return min(self._pixmap.height() * scale, 200.0)   # cap at 200px
        return 0.0

    # ── painting ──────────────────────────────────────────────────────────────

    def paint(self, painter, option, widget=None):
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            nw = self._width
            nh = self._height

            bg       = QColor(self.bg_color)
            bdr_base = QColor(self.border_color)

            if self._hover and not self.isSelected():
                bdr_draw = bdr_base.lighter(140)
            else:
                bdr_draw = bdr_base
            pw  = self.border_width * (2.0 if self.isSelected() else 1.0)

            pen = QPen(bdr_draw, pw)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(QBrush(bg))
            painter.drawPath(self._shape_path)

            # selection glow — always derived from base border, never from hover colour
            if self.isSelected():
                glow_c = bdr_base.lighter(160)
                glow_p = QPen(glow_c, pw + 3.0)
                glow_p.setStyle(Qt.DotLine)
                painter.setPen(glow_p)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(self._shape_path)

            # label
            fc   = QColor(self.text_color)
            font = QFont("Segoe UI", self.font_size, QFont.Medium)
            painter.setFont(font)
            painter.setPen(fc)
            painter.drawText(
                QRectF(6.0, 4.0, nw - 12.0, nh - 8.0),
                Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextWordWrap,
                self.label,
            )

            # body-text dot
            if self.body_text.strip():
                dot_c = QColor("#f39c12")
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(dot_c))
                painter.drawEllipse(QRectF(nw - 14.0, 4.0, 8.0, 8.0))

            # attachment image — drawn below the label area
            if self._pixmap and not self._pixmap.isNull():
                ih     = self._image_height()
                margin = 4.0
                img_y  = nh - ih - margin
                img_rect = QRectF(margin, img_y, nw - margin * 2.0, ih)
                # Clip to the node shape so rounded corners look correct
                painter.save()
                painter.setClipPath(self._shape_path)
                painter.drawPixmap(img_rect.toRect(), self._pixmap)
                painter.restore()
                # Camera icon indicator at top-right when image is present
                cam_c   = QColor("#3498db")
                cam_pen = QPen(cam_c, 1.5)
                cam_r   = QRectF(nw - 24.0, 4.0, 10.0, 8.0)
                painter.setPen(cam_pen)
                painter.setBrush(QBrush(cam_c))
                painter.drawRoundedRect(cam_r, 1.5, 1.5)

            # resize handle
            if self._hover or self._resize_handle:
                hs      = float(self.HANDLE_SIZE)
                hr      = QRectF(nw - hs, nh - hs, hs * 2.0, hs * 2.0)
                hdl_c   = bdr_base.lighter(150)
                hdl_pen = QPen(hdl_c, 1.5)
                painter.setPen(hdl_pen)
                painter.setBrush(QBrush(bdr_base))
                painter.drawRect(hr)

        except Exception as exc:
            import traceback
            print(f"[NodeItem.paint ERROR] {exc}")
            traceback.print_exc()

    # ── hover / mouse ─────────────────────────────────────────────────────────

    def hoverEnterEvent(self, event):
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        self._resize_handle = False
        self.setCursor(Qt.ArrowCursor)
        self.update()
        super().hoverLeaveEvent(event)

    def hoverMoveEvent(self, event):
        pos = event.pos()
        px  = pos.x()
        py  = pos.y()
        hs  = float(self.HANDLE_SIZE)
        nw  = self._width
        nh  = self._height
        over = (px >= nw - hs and px <= nw + hs
                and py >= nh - hs and py <= nh + hs)
        if over != self._resize_handle:
            self._resize_handle = over
            self.setCursor(Qt.SizeFDiagCursor if over else Qt.ArrowCursor)
            self.update()
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            px  = pos.x()
            py  = pos.y()
            hs  = float(self.HANDLE_SIZE)
            nw  = self._width
            nh  = self._height
            if px >= nw - hs and px <= nw + hs and py >= nh - hs and py <= nh + hs:
                sp = event.scenePos()
                self._resizing       = True
                self._resize_start_x = sp.x()
                self._resize_start_y = sp.y()
                self._resize_orig_w  = self._width
                self._resize_orig_h  = self._height
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            sp    = event.scenePos()
            dx    = sp.x() - self._resize_start_x
            dy    = sp.y() - self._resize_start_y
            new_w = max(80.0, self._resize_orig_w + dx)
            new_h = max(30.0, self._resize_orig_h + dy)
            self.prepareGeometryChange()
            self._width  = new_w
            self._height = new_h
            self._rebuild_geometry()
            self.update()
            self.signals.node_resized.emit(self.node_id)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.signals.node_double_clicked.emit(self.node_id)
        event.accept()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.signals.node_moved.emit(self.node_id)
        if change == QGraphicsItem.ItemSelectedChange:
            self.setZValue(Z_SELECTED if value else Z_NODE)
            # When deselected by clicking another node, hoverLeaveEvent may
            # not fire — reset hover state here so the colour is always clean.
            if not value:
                self._hover         = False
                self._resize_handle = False
                self.setCursor(Qt.ArrowCursor)
            self.signals.node_selected.emit(self.node_id)
        return super().itemChange(change, value)

    # ── serialisation ─────────────────────────────────────────────────────────

    def to_dict(self):
        pos = self.pos()
        return {
            "id"          : self.node_id,
            "label"       : self.label,
            "body_text"   : self.body_text,
            "shape"       : self.node_shape,
            "bg_color"    : self.bg_color,
            "border_color": self.border_color,
            "text_color"  : self.text_color,
            "font_size"   : self.font_size,
            "width"       : self._width,
            "height"      : self._height,
            "opacity"     : self.opacity(),
            "border_width": self.border_width,
            "category"    : self.category,
            "attachment"  : self.attachment,
            "x"           : pos.x(),
            "y"           : pos.y(),
        }

    @classmethod
    def from_dict(cls, data):
        node = cls(
            label        = data.get("label",        "Node"),
            body_text    = data.get("body_text",    ""),
            shape        = data.get("shape",        SHAPE_ROUNDED_RECT),
            bg_color     = data.get("bg_color",     DEFAULT_BG_COLOR),
            border_color = data.get("border_color", DEFAULT_BORDER_COLOR),
            text_color   = data.get("text_color",   DEFAULT_TEXT_COLOR),
            font_size    = data.get("font_size",    DEFAULT_FONT_SIZE),
            width        = data.get("width",        DEFAULT_NODE_WIDTH),
            height       = data.get("height",       DEFAULT_NODE_HEIGHT),
            opacity      = data.get("opacity",      DEFAULT_OPACITY),
            border_width = data.get("border_width", DEFAULT_BORDER_WIDTH),
            category     = data.get("category",     ""),
            node_id      = data.get("id"),
        )
        node.setPos(data.get("x", 0.0), data.get("y", 0.0))
        if data.get("attachment"):
            node.set_attachment(data["attachment"])
        return node


# ──────────────────────────────────────────────────────────────────────────────
# EdgeItem
# ──────────────────────────────────────────────────────────────────────────────

class EdgeItem(QGraphicsPathItem):
    """
    A bezier-curve edge connecting two NodeItems.
    """

    ARROW_SIZE = 10.0

    def __init__(
        self,
        source,
        target,
        label    = DEFAULT_EDGE_LABEL,
        color    = DEFAULT_EDGE_COLOR,
        width    = DEFAULT_EDGE_WIDTH,
        style    = DEFAULT_EDGE_STYLE,
        directed = DEFAULT_EDGE_DIRECTED,
        edge_id  = None,
        parent   = None,
    ):
        super().__init__(parent)

        self.edge_id  = edge_id or str(uuid.uuid4())
        self.source   = source
        self.target   = target
        self.label    = label
        self.color    = color
        self.width    = width
        self.style    = style
        self.directed = directed

        self.setZValue(Z_EDGE)
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsFocusable)
        self.setAcceptHoverEvents(True)
        self._hover = False

        self.source.signals.node_moved.connect(self._refresh)
        self.source.signals.node_resized.connect(self._refresh)
        self.target.signals.node_moved.connect(self._refresh)
        self.target.signals.node_resized.connect(self._refresh)

        self._refresh()

    def _node_center_xy(self, node):
        sp = node.scenePos()
        return sp.x() + node.width * 0.5, sp.y() + node.height * 0.5

    def _refresh(self, *_):
        self.prepareGeometryChange()
        sx, sy = self._node_center_xy(self.source)
        tx, ty = self._node_center_xy(self.target)
        dx  = tx - sx
        cp1 = QPointF(sx + dx * 0.5, sy)
        cp2 = QPointF(tx - dx * 0.5, ty)
        src = QPointF(sx, sy)
        tgt = QPointF(tx, ty)
        path = QPainterPath(src)
        path.cubicTo(cp1, cp2, tgt)
        self.setPath(path)
        self.update()

    def paint(self, painter, option, widget=None):
        try:
            painter.setRenderHint(QPainter.Antialiasing)

            path      = self.path()
            base_col  = QColor(self.color)
            draw_col  = base_col.lighter(160) if (self._hover or self.isSelected()) else base_col
            w         = self.width + (1.0 if self._hover else 0.0)
            pen       = QPen(draw_col, w)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)

            if self.style == EDGE_DASHED:
                pen.setStyle(Qt.DashLine)
            elif self.style == EDGE_DOTTED:
                pen.setStyle(Qt.DotLine)
            else:
                pen.setStyle(Qt.SolidLine)

            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

            if self.directed and path.elementCount() >= 2:
                tip    = path.pointAtPercent(1.0)
                back   = path.pointAtPercent(0.98)
                angle  = math.atan2(tip.y() - back.y(), tip.x() - back.x())
                a      = self.ARROW_SIZE
                p1     = QPointF(tip.x() - a * math.cos(angle - math.pi/7),
                                 tip.y() - a * math.sin(angle - math.pi/7))
                p2     = QPointF(tip.x() - a * math.cos(angle + math.pi/7),
                                 tip.y() - a * math.sin(angle + math.pi/7))
                arrow  = QPainterPath()
                arrow.moveTo(tip)
                arrow.lineTo(p1)
                arrow.lineTo(p2)
                arrow.closeSubpath()
                arr_c  = QColor(self.color)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(arr_c))
                painter.drawPath(arrow)

            if self.label:
                mid    = path.pointAtPercent(0.5)
                lp     = QPointF(mid.x() + 4.0, mid.y() - 4.0)
                lf     = QFont("Segoe UI", 8)
                lc     = QColor(self.color).lighter(180)
                painter.setFont(lf)
                painter.setPen(lc)
                painter.drawText(lp, self.label)

        except Exception as exc:
            import traceback
            print(f"[EdgeItem.paint ERROR] {exc}")
            traceback.print_exc()

    def hoverEnterEvent(self, event):
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def to_dict(self):
        return {
            "id"      : self.edge_id,
            "source"  : self.source.node_id,
            "target"  : self.target.node_id,
            "label"   : self.label,
            "color"   : self.color,
            "width"   : self.width,
            "style"   : self.style,
            "directed": self.directed,
        }

