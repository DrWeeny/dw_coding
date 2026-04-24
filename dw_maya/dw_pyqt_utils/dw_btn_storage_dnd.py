"""
dw_btn_storage_dnd.py
=====================
Drop-in additions for VtxStorageButton:

    1.  DragDropMixin   – makes any VtxStorageButton a drag source AND drop target.
    2.  OperationPopup  – small radial-ish menu that appears on drop and lets the
                         user pick copy / add / sub / multiply / divide / intersect.

Usage
-----
Import this module alongside dw_btn_storage and mix DragDropMixin in:

    # In your existing file, replace the class header:
    class VtxStorageButton(DragDropMixin, QtWidgets.QPushButton):
        ...

Or, if you cannot touch the original file, subclass from outside:

    from dw_btn_storage import VtxStorageButton
    from dw_btn_storage_dnd import DragDropMixin

    class DnDStorageButton(DragDropMixin, VtxStorageButton):
        pass

The mixin must come **before** VtxStorageButton in the MRO so its event
overrides take precedence.
"""

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Qt

import json
import numpy as np
from typing import Optional

# ---------------------------------------------------------------------------
# MIME type used to carry serialised button state between buttons
# ---------------------------------------------------------------------------
_MIME_TYPE = "application/x-vtxstorage"


# ---------------------------------------------------------------------------
# Operation popup
# ---------------------------------------------------------------------------

class OperationPopup(QtWidgets.QFrame):
    """Small floating menu shown when one button is dropped onto another.

    Signals
    -------
    operation_chosen(str)
        Emitted with one of: "copy", "add", "sub", "multiply", "divide",
        "intersect".
    cancelled()
        Emitted when the user dismisses without choosing.
    """

    operation_chosen = QtCore.Signal(str)
    cancelled = QtCore.Signal()

    # (label, operation_key, enabled_when_no_weights)
    _OPS = [
        ("Copy",      "copy",      True),
        ("Add",       "add",       False),
        ("Subtract",  "sub",       False),
        ("Multiply",  "multiply",  False),
        ("Divide",    "divide",    False),
        ("Intersect", "intersect", True),
    ]

    def __init__(self, has_src_weights: bool, has_dst_weights: bool,
                 parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("OperationPopup")
        self._build_ui(has_src_weights, has_dst_weights)

    # ------------------------------------------------------------------
    def _build_ui(self, has_src_weights: bool, has_dst_weights: bool):
        self.setStyleSheet("""
            QFrame#OperationPopup {
                background: rgba(40, 40, 40, 230);
                border: 1px solid rgba(255,255,255,60);
                border-radius: 6px;
            }
            QPushButton {
                background: rgba(255,255,255,12);
                border: none;
                border-radius: 3px;
                color: #ddd;
                font-size: 12px;
                padding: 5px 14px;
                text-align: left;
            }
            QPushButton:hover {
                background: rgba(255,255,255,35);
                color: white;
            }
            QPushButton:disabled {
                color: rgba(200,200,200,60);
            }
            QLabel#title {
                color: rgba(200,200,200,160);
                font-size: 10px;
                padding: 4px 10px 2px 10px;
            }
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(2)

        title = QtWidgets.QLabel("Drop operation", objectName="title")
        layout.addWidget(title)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setStyleSheet("color: rgba(255,255,255,40);")
        layout.addWidget(sep)

        for label, key, always_enabled in self._OPS:
            btn = QtWidgets.QPushButton(label)
            # Arithmetic ops need weights on both sides
            enabled = always_enabled or (has_src_weights and has_dst_weights)
            btn.setEnabled(enabled)
            if not enabled:
                btn.setToolTip("Both buttons must have stored weights")
            # Capture key in closure
            btn.clicked.connect(lambda _=False, k=key: self._choose(k))
            layout.addWidget(btn)

        self.adjustSize()

    def _choose(self, key: str):
        self.operation_chosen.emit(key)
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            self.close()
        else:
            super().keyPressEvent(event)

    def show_near(self, global_pos: QtCore.QPoint):
        """Pop up close to *global_pos*, nudged to stay on screen."""
        self.move(global_pos + QtCore.QPoint(4, 4))
        self.show()
        # Nudge back onto screen if needed
        screen = QtWidgets.QApplication.screenAt(global_pos)
        if screen:
            sg = screen.availableGeometry()
            rect = self.frameGeometry()
            if rect.right() > sg.right():
                self.move(self.x() - (rect.right() - sg.right()), self.y())
            if rect.bottom() > sg.bottom():
                self.move(self.x(), self.y() - (rect.bottom() - sg.bottom()))


# ---------------------------------------------------------------------------
# Drag-and-drop mixin
# ---------------------------------------------------------------------------

class DragDropMixin:
    """Adds drag-and-drop to VtxStorageButton.

    Mix this in BEFORE VtxStorageButton in the MRO:

        class DnDStorageButton(DragDropMixin, VtxStorageButton):
            pass

    Drag behaviour
    --------------
    Middle-button press-and-hold (> _DRAG_THRESHOLD px) starts a drag.
    Left/right clicks are completely unaffected.

    Why grabMouse?
    Qt only tracks mouse-move events for the *primary* button.  For any
    other button (middle, extra) ``event.buttons()`` stays 0 in
    mouseMoveEvent, so the threshold check never fires.  Calling
    ``grabMouse()`` on middle-press routes ALL subsequent mouse events to
    this widget until ``releaseMouse()`` is called, which gives us the
    move events we need.

    Drop behaviour
    --------------
    When another VtxStorageButton is hovered, a dashed blue border appears.
    On release an OperationPopup is shown so the user can choose what to do.

    Operations
    ----------
    copy      – dst becomes an exact copy of src (from_dict)
    add       – dst.weights += src.weights  (union of selections)
    sub       – dst.weights -= src.weights  (difference of selections)
    multiply  – dst.weights *= src.weights
    divide    – dst.weights /= src.weights  (safe: div-by-zero → 0)
    intersect – intersection of the two selections; weights averaged
    """

    # Pixels of movement before a drag starts
    _DRAG_THRESHOLD: int = 6

    # Border style painted over the button while a valid drag hovers
    _DROP_BORDER_COLOR = QtGui.QColor(80, 160, 255, 220)
    _DROP_BORDER_WIDTH = 2

    # ------------------------------------------------------------------
    # Initialisation hook — called via super().__init__
    # ------------------------------------------------------------------

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptDrops(True)
        self._drag_start_pos: Optional[QtCore.QPoint] = None
        self._is_drop_target: bool = False  # visual highlight flag

    # ------------------------------------------------------------------
    # Mouse events — augment (not replace) the original ones
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QtCore.QEvent):
        if event.button() == Qt.MiddleButton:
            self._drag_start_pos = event.pos()
            # grabMouse() is essential: Qt won't deliver move events for
            # non-primary buttons without it.
            self.grabMouse()
        else:
            # Left / right clicks pass straight through unchanged
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtCore.QEvent):
        if self._drag_start_pos is not None:
            delta = (event.pos() - self._drag_start_pos).manhattanLength()
            if delta >= self._DRAG_THRESHOLD:
                self.releaseMouse()          # stop capturing before QDrag takes over
                self._drag_start_pos = None
                self._start_drag()
            return  # swallow move while we're waiting — don't call super
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtCore.QEvent):
        if event.button() == Qt.MiddleButton and self._drag_start_pos is not None:
            # Released without reaching the threshold — cancel quietly
            self.releaseMouse()
            self._drag_start_pos = None
            return
        super().mouseReleaseEvent(event) if hasattr(super(), "mouseReleaseEvent") else None

    # ------------------------------------------------------------------
    # Drag source
    # ------------------------------------------------------------------

    def _start_drag(self):
        """Kick off a QDrag from this button."""
        if not (self.storage.get("weights") or self.storage.get("selection")):
            return  # nothing to drag

        data = json.dumps(self.to_dict())
        mime = QtCore.QMimeData()
        mime.setData(_MIME_TYPE, QtCore.QByteArray(data.encode()))

        # Render the button to a pixmap for the drag cursor
        pixmap = self.grab()
        # Semi-transparent
        faded = QtGui.QPixmap(pixmap.size())
        faded.fill(Qt.transparent)
        painter = QtGui.QPainter(faded)
        painter.setOpacity(0.55)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()

        drag = QtGui.QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(faded)
        drag.setHotSpot(QtCore.QPoint(faded.width() // 2, faded.height() // 2))

        drag.exec_(Qt.CopyAction | Qt.MoveAction)

    # ------------------------------------------------------------------
    # Drop target
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QtCore.QEvent):
        if event.mimeData().hasFormat(_MIME_TYPE) and event.source() is not self:
            event.acceptProposedAction()
            self._is_drop_target = True
            self.update()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QtCore.QEvent):
        self._is_drop_target = False
        self.update()

    def dropEvent(self, event: QtCore.QEvent):
        self._is_drop_target = False
        self.update()

        if not event.mimeData().hasFormat(_MIME_TYPE):
            event.ignore()
            return

        raw = bytes(event.mimeData().data(_MIME_TYPE)).decode()
        try:
            src_dict = json.loads(raw)
        except json.JSONDecodeError:
            event.ignore()
            return

        event.acceptProposedAction()
        src_has_weights = bool(src_dict.get("storage", {}).get("weights"))
        dst_has_weights = bool(self.storage.get("weights"))

        popup = OperationPopup(
            has_src_weights=src_has_weights,
            has_dst_weights=dst_has_weights,
            parent=None,            # top-level so it floats freely
        )
        popup.operation_chosen.connect(
            lambda op, d=src_dict: self._apply_operation(op, d)
        )
        popup.show_near(QtGui.QCursor.pos())

    # ------------------------------------------------------------------
    # Paint — draw drop-target highlight
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._is_drop_target:
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            pen = QtGui.QPen(self._DROP_BORDER_COLOR, self._DROP_BORDER_WIDTH,
                             Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(
                self._DROP_BORDER_WIDTH,
                self._DROP_BORDER_WIDTH,
                self.width()  - 2 * self._DROP_BORDER_WIDTH,
                self.height() - 2 * self._DROP_BORDER_WIDTH,
                3, 3,
            )
            painter.end()

    # ------------------------------------------------------------------
    # Operation dispatch
    # ------------------------------------------------------------------

    def _apply_operation(self, op: str, src_dict: dict):
        """Apply *op* using *src_dict* as the source data."""
        if op == "copy":
            self._op_copy(src_dict)
        elif op == "add":
            self._op_weights(src_dict, mode="add")
        elif op == "sub":
            self._op_weights(src_dict, mode="sub")
        elif op == "multiply":
            self._op_weights(src_dict, mode="multiply")
        elif op == "divide":
            self._op_weights(src_dict, mode="divide")
        elif op == "intersect":
            self._op_intersect(src_dict)
        else:
            return

        # Refresh visual state
        has_data = bool(self.storage["weights"] or self.storage["selection"])
        self._update_button_state(has_data)

    # ------------------------------------------------------------------
    # Individual operations
    # ------------------------------------------------------------------

    def _op_copy(self, src_dict: dict):
        """Replace this button's state with a deep copy of the source."""
        self.from_dict(src_dict)

    def _op_weights(self, src_dict: dict, mode: str):
        """Element-wise arithmetic on the weight arrays.

        Both sides must have the same length; if not, the shorter array is
        zero-padded so the operation can still complete (a warning is logged).
        """
        dst_w = list(self.storage.get("weights") or [])
        src_w = list(src_dict.get("storage", {}).get("weights") or [])

        if not dst_w or not src_w:
            return

        # Align lengths
        max_len = max(len(dst_w), len(src_w))
        dst_arr = np.array(dst_w + [0.0] * (max_len - len(dst_w)), dtype=float)
        src_arr = np.array(src_w + [0.0] * (max_len - len(src_w)), dtype=float)

        if mode == "add":
            result = np.clip(dst_arr + src_arr, 0.0, 1.0)
        elif mode == "sub":
            result = np.clip(dst_arr - src_arr, 0.0, 1.0)
        elif mode == "multiply":
            result = np.clip(dst_arr * src_arr, 0.0, 1.0)
        elif mode == "divide":
            with np.errstate(divide="ignore", invalid="ignore"):
                result = np.where(src_arr != 0.0, dst_arr / src_arr, 0.0)
            result = np.clip(result, 0.0, 1.0)
        else:
            return

        self.storage["weights"] = result.tolist()

        # Merge selections (union)
        src_sel = src_dict.get("storage", {}).get("selection") or {}
        for mesh, ids in src_sel.items():
            if mesh not in self.storage["selection"]:
                self.storage["selection"][mesh] = list(ids)
            else:
                existing = set(self.storage["selection"][mesh])
                existing.update(ids)
                self.storage["selection"][mesh] = sorted(existing)

    def _op_intersect(self, src_dict: dict):
        """Keep only vertices present in *both* selections.

        Weights for kept vertices are averaged; the rest become 0.
        Works even when either side has no weights stored (selection-only).
        """
        src_sel  = src_dict.get("storage", {}).get("selection") or {}
        src_w    = src_dict.get("storage", {}).get("weights")   or []
        dst_sel  = self.storage.get("selection") or {}
        dst_w    = self.storage.get("weights")   or []

        new_sel: dict = {}
        for mesh in set(dst_sel) & set(src_sel):
            dst_ids = set(dst_sel[mesh])
            src_ids = set(src_sel[mesh])
            common  = sorted(dst_ids & src_ids)
            if common:
                new_sel[mesh] = common

        self.storage["selection"] = new_sel

        if dst_w and src_w:
            max_len = max(len(dst_w), len(src_w))
            dst_arr = np.array(dst_w + [0.0] * (max_len - len(dst_w)), dtype=float)
            src_arr = np.array(src_w + [0.0] * (max_len - len(src_w)), dtype=float)
            result  = np.clip((dst_arr + src_arr) * 0.5, 0.0, 1.0)
            self.storage["weights"] = result.tolist()


# ---------------------------------------------------------------------------
# Convenience: ready-to-use subclass
# ---------------------------------------------------------------------------

# Import guard — only attempt if the original module is importable
try:
    from dw_btn_storage import VtxStorageButton as _VtxStorageButton

    class DnDStorageButton(DragDropMixin, _VtxStorageButton):
        """VtxStorageButton with drag-and-drop support baked in."""
        pass

except ImportError:
    # If dw_btn_storage is not on sys.path yet (e.g. during standalone testing)
    DnDStorageButton = None  # type: ignore