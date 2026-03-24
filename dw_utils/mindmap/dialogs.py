"""
Dialogs for the Mind Map tool.

Classes

- NodeEditorDialog:   Double-click dialog for editing node label and body text.
- NodePropertiesPanel: Side-panel for full node styling (shape, colours, font, etc.).
- EdgePropertiesDialog: Dialog for editing edge label, colour, style, direction.

"""

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap, QImage
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QTextEdit, QComboBox, QSpinBox,
    QDoubleSpinBox, QPushButton, QColorDialog, QCheckBox,
    QSlider, QGroupBox, QDialogButtonBox, QWidget, QFrame,
    QSizePolicy, QFileDialog,
)

from dw_utils.mindmap.constants import (
    ALL_SHAPES, ALL_EDGE_STYLES,
    DEFAULT_BG_COLOR, DEFAULT_BORDER_COLOR, DEFAULT_TEXT_COLOR,
    DEFAULT_FONT_SIZE, DEFAULT_NODE_WIDTH, DEFAULT_NODE_HEIGHT,
    DEFAULT_BORDER_WIDTH,
    DEFAULT_EDGE_COLOR, DEFAULT_EDGE_WIDTH, DEFAULT_EDGE_STYLE,
    DEFAULT_EDGE_DIRECTED,
)
from dw_utils.mindmap.items import NodeItem, EdgeItem


# ──────────────────────────────────────────────────────────────────────────────
# Image helpers
# ──────────────────────────────────────────────────────────────────────────────

def _pixmap_to_base64(pixmap: QPixmap) -> str:
    """Convert a QPixmap to a base64-encoded PNG string."""
    ba  = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    pixmap.save(buf, "PNG")
    buf.close()
    return ba.toBase64().data().decode("ascii")


def _base64_to_pixmap(b64: str) -> QPixmap:
    """Decode a base64 PNG string back to a QPixmap."""
    ba = QByteArray.fromBase64(b64.encode("ascii"))
    pm = QPixmap()
    pm.loadFromData(ba, "PNG")
    return pm


# ──────────────────────────────────────────────────────────────────────────────
# Colour picker button helper
# ──────────────────────────────────────────────────────────────────────────────

class _ColourButton(QPushButton):
    """A button that shows its current colour and opens a picker on click."""

    colour_changed = QtCore.Signal(str)

    def __init__(self, hex_color: str = "#ffffff", parent=None):
        super().__init__(parent)
        self._hex = hex_color
        self._update_style()
        self.setFixedSize(48, 24)
        self.clicked.connect(self._pick)

    def _update_style(self):
        c     = QColor(self._hex)
        light = c.lightness() > 128
        text  = "#000000" if light else "#ffffff"
        self.setStyleSheet(
            f"background-color:{self._hex}; color:{text}; border:1px solid #555; border-radius:3px;"
        )
        self.setText(self._hex)

    def _pick(self):
        dlg = QColorDialog(QColor(self._hex), self)
        dlg.setOption(QColorDialog.ShowAlphaChannel, False)
        if dlg.exec_():
            self._hex = dlg.selectedColor().name()
            self._update_style()
            self.colour_changed.emit(self._hex)

    @property
    def hex_color(self) -> str:
        return self._hex

    def set_color(self, hex_color: str):
        self._hex = hex_color
        self._update_style()


# ──────────────────────────────────────────────────────────────────────────────
# NodeEditorDialog
# ──────────────────────────────────────────────────────────────────────────────

class NodeEditorDialog(QDialog):
    """
    Double-click dialog for quickly editing a node's label and body text.

    Shows label (single line) and a Markdown-friendly multiline body.
    Accepts with Ctrl+Enter.

    Attributes:
        label_edit: QLineEdit for the node label.
        body_edit:  QTextEdit for extended notes / markdown.
    """

    def __init__(self, node: NodeItem, parent=None):
        super().__init__(parent)
        self.node = node
        self.setWindowTitle(f"Edit Node — {node.label}")
        self.setMinimumSize(520, 480)
        self.setModal(True)
        self._attachment_b64 = node.attachment   # current base64 string
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Label row
        lbl_row = QHBoxLayout()
        lbl_row.addWidget(QLabel("Label:"))
        self.label_edit = QLineEdit(self.node.label)
        font = QFont("Segoe UI", 13, QFont.Bold)
        self.label_edit.setFont(font)
        lbl_row.addWidget(self.label_edit)
        layout.addLayout(lbl_row)

        # Body text
        body_lbl = QLabel("Notes / Description  (Markdown supported):")
        body_lbl.setStyleSheet("color:#aaa; font-size:10px;")
        layout.addWidget(body_lbl)

        self.body_edit = QTextEdit()
        self.body_edit.setPlainText(self.node.body_text)
        self.body_edit.setAcceptRichText(False)
        self.body_edit.setFont(QFont("Consolas", 10))
        self.body_edit.setStyleSheet(
            "background:#1e1e2e; color:#cdd6f4; border:1px solid #444;"
            " border-radius:4px; padding:6px;"
        )
        layout.addWidget(self.body_edit, stretch=1)

        # ── Image attachment ──────────────────────────────────────────────────
        img_group = QGroupBox("Attachment")
        img_group.setStyleSheet(
            "QGroupBox{font-weight:bold;color:#aaa;border:1px solid #333;"
            "border-radius:4px;margin-top:6px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}"
        )
        img_v = QVBoxLayout(img_group)
        img_v.setSpacing(4)

        # Preview label
        self._img_preview = QLabel()
        self._img_preview.setAlignment(Qt.AlignCenter)
        self._img_preview.setMinimumHeight(80)
        self._img_preview.setMaximumHeight(160)
        self._img_preview.setStyleSheet(
            "background:#1a1a2e; border:1px solid #333; border-radius:3px; color:#666;"
        )
        self._img_preview.setText("No image attached")
        img_v.addWidget(self._img_preview)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self._btn_paste_img = QPushButton("📋  Paste from Clipboard")
        self._btn_paste_img.setToolTip("Paste image from clipboard (e.g. Windows Snipping Tool)")
        self._btn_paste_img.clicked.connect(self._paste_image)
        btn_row.addWidget(self._btn_paste_img)

        self._btn_load_img = QPushButton("📁  Load File…")
        self._btn_load_img.setToolTip("Load PNG / JPG / BMP from disk")
        self._btn_load_img.clicked.connect(self._load_image)
        btn_row.addWidget(self._btn_load_img)

        self._btn_clear_img = QPushButton("✖  Clear")
        self._btn_clear_img.setToolTip("Remove attached image")
        self._btn_clear_img.clicked.connect(self._clear_image)
        btn_row.addWidget(self._btn_clear_img)
        img_v.addLayout(btn_row)

        layout.addWidget(img_group)

        # Reload preview if node already has an attachment
        if self._attachment_b64:
            self._refresh_preview()

        # Hint + buttons
        hint = QLabel("Ctrl+Enter to confirm")
        hint.setAlignment(Qt.AlignRight)
        hint.setStyleSheet("color:#666; font-size:9px;")
        layout.addWidget(hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ── image helpers ─────────────────────────────────────────────────────────

    def _refresh_preview(self):
        """Update the preview label from self._attachment_b64."""
        if not self._attachment_b64:
            self._img_preview.setPixmap(QPixmap())
            self._img_preview.setText("No image attached")
            return
        pm = _base64_to_pixmap(self._attachment_b64)
        if pm.isNull():
            self._img_preview.setText("⚠ Could not load image")
            return
        scaled = pm.scaled(
            self._img_preview.width() or 460,
            self._img_preview.maximumHeight(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._img_preview.setPixmap(scaled)
        self._img_preview.setText("")

    def _set_pixmap(self, pm: QPixmap):
        """Store *pm* as the current attachment."""
        if pm.isNull():
            return
        self._attachment_b64 = _pixmap_to_base64(pm)
        self._refresh_preview()

    def _paste_image(self):
        """Paste an image from the system clipboard."""
        cb = QtWidgets.QApplication.clipboard()
        pm = cb.pixmap()
        if pm.isNull():
            # Also try image data (some apps put QImage, not QPixmap)
            img = cb.image()
            if not img.isNull():
                pm = QPixmap.fromImage(img)
        if pm.isNull():
            self._img_preview.setText("⚠ No image found in clipboard")
            return
        self._set_pixmap(pm)

    def _load_image(self):
        """Open a file browser and load an image from disk."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All Files (*)",
        )
        if not path:
            return
        pm = QPixmap(path)
        if pm.isNull():
            self._img_preview.setText(f"⚠ Could not load: {path}")
            return
        self._set_pixmap(pm)

    def _clear_image(self):
        """Remove the attached image."""
        self._attachment_b64 = ""
        self._img_preview.setPixmap(QPixmap())
        self._img_preview.setText("No image attached")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._attachment_b64:
            self._refresh_preview()

    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and event.modifiers() & Qt.ControlModifier):
            self.accept()
            return
        super().keyPressEvent(event)

    def get_data(self) -> dict:
        return {
            "label"      : self.label_edit.text().strip() or "Node",
            "body_text"  : self.body_edit.toPlainText(),
            "attachment" : self._attachment_b64,
        }


# ──────────────────────────────────────────────────────────────────────────────
# NodePropertiesPanel
# ──────────────────────────────────────────────────────────────────────────────

_SHAPE_DISPLAY = {
    "rounded_rect" : "⬜  Rounded Rect",
    "rect"         : "▭  Rectangle",
    "ellipse"      : "⬭  Ellipse",
    "diamond"      : "◇  Diamond",
    "hexagon"      : "⬡  Hexagon",
    "parallelogram": "▱  Parallelogram",
}

_EDGE_STYLE_DISPLAY = {
    "solid" : "— Solid",
    "dashed": "-- Dashed",
    "dotted": "·· Dotted",
}


def _section(title: str) -> QGroupBox:
    gb = QGroupBox(title)
    gb.setStyleSheet(
        "QGroupBox{font-weight:bold;color:#aaa;border:1px solid #333;"
        "border-radius:4px;margin-top:6px;}"
        "QGroupBox::title{subcontrol-origin:margin;left:8px;padding:0 4px;}"
    )
    return gb


class NodePropertiesPanel(QWidget):
    """
    Side panel showing all editable properties of the currently selected node.

    Emits ``properties_changed(dict)`` when the user modifies any field,
    allowing the scene to apply the change with undo support.

    Signals:
        properties_changed(dict): Emitted with the new property dict.
        connect_edge_requested(): Emitted when "Start Edge" button is clicked.
    """

    properties_changed      = QtCore.Signal(dict)
    connect_edge_requested  = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(260)
        self.setMaximumWidth(300)
        self._node = None  # type: NodeItem or None
        self._build_ui()
        self.setEnabled(False)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        title = QLabel("Node Properties")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:13px; font-weight:bold; color:#ecf0f1;")
        layout.addWidget(title)

        # ── Content ──────────────────────────────────────────────────────────
        gb_content = _section("Content")
        form_c     = QFormLayout(gb_content)

        self.lbl_label  = QLineEdit()
        self.lbl_body   = QTextEdit()
        self.lbl_body.setFixedHeight(70)
        self.lbl_body.setAcceptRichText(False)
        self.lbl_category = QLineEdit()
        form_c.addRow("Label:", self.lbl_label)
        form_c.addRow("Notes:", self.lbl_body)
        form_c.addRow("Category:", self.lbl_category)
        layout.addWidget(gb_content)

        # ── Appearance ───────────────────────────────────────────────────────
        gb_app  = _section("Appearance")
        form_a  = QFormLayout(gb_app)

        self.shape_combo = QComboBox()
        for key in ALL_SHAPES:
            self.shape_combo.addItem(_SHAPE_DISPLAY.get(key, key), key)

        self.btn_bg     = _ColourButton(DEFAULT_BG_COLOR)
        self.btn_border = _ColourButton(DEFAULT_BORDER_COLOR)
        self.btn_text   = _ColourButton(DEFAULT_TEXT_COLOR)

        self.spin_font  = QSpinBox()
        self.spin_font.setRange(6, 36)
        self.spin_font.setValue(DEFAULT_FONT_SIZE)

        self.spin_border_w = QDoubleSpinBox()
        self.spin_border_w.setRange(0.5, 10.0)
        self.spin_border_w.setSingleStep(0.5)
        self.spin_border_w.setValue(DEFAULT_BORDER_WIDTH)

        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(20, 100)
        self.slider_opacity.setValue(100)

        form_a.addRow("Shape:", self.shape_combo)
        form_a.addRow("Fill:", self.btn_bg)
        form_a.addRow("Border:", self.btn_border)
        form_a.addRow("Text:", self.btn_text)
        form_a.addRow("Font size:", self.spin_font)
        form_a.addRow("Border px:", self.spin_border_w)
        form_a.addRow("Opacity:", self.slider_opacity)
        layout.addWidget(gb_app)

        # ── Size ─────────────────────────────────────────────────────────────
        gb_size  = _section("Size")
        form_s   = QFormLayout(gb_size)
        self.spin_width  = QSpinBox()
        self.spin_width.setRange(60, 1000)
        self.spin_width.setValue(DEFAULT_NODE_WIDTH)
        self.spin_height = QSpinBox()
        self.spin_height.setRange(24, 600)
        self.spin_height.setValue(DEFAULT_NODE_HEIGHT)
        form_s.addRow("Width:", self.spin_width)
        form_s.addRow("Height:", self.spin_height)
        layout.addWidget(gb_size)

        # ── Actions ──────────────────────────────────────────────────────────
        gb_act = _section("Actions")
        vl_act = QVBoxLayout(gb_act)

        self.btn_connect = QPushButton("🔗  Start Edge From This Node")
        self.btn_connect.clicked.connect(self.connect_edge_requested)
        vl_act.addWidget(self.btn_connect)

        self.btn_apply = QPushButton("✔  Apply Changes")
        self.btn_apply.setStyleSheet(
            "background:#27ae60; color:white; font-weight:bold;"
            " border-radius:4px; padding:5px;"
        )
        self.btn_apply.clicked.connect(self._emit_changes)
        vl_act.addWidget(self.btn_apply)
        layout.addWidget(gb_act)

        layout.addStretch()

        # ── Live-update connections ───────────────────────────────────────────
        # Only text-content fields auto-apply on edit-finished.
        # Appearance / size / colour widgets emit ONLY via the Apply button
        # to prevent load_node() from propagating values to other nodes.
        for w in (self.lbl_label, self.lbl_category):
            w.editingFinished.connect(self._emit_changes)
        self.lbl_body.textChanged.connect(self._emit_changes)

    def load_node(self, node: NodeItem):
        """Populate all controls from *node* without emitting any changes."""
        self._node = node
        self.setEnabled(True)

        # Block every widget's signals while we load so valueChanged /
        # currentIndexChanged / colour_changed don't fire _emit_changes
        # and accidentally overwrite the node (or other selected nodes).
        widgets = [
            self.lbl_label, self.lbl_body, self.lbl_category,
            self.shape_combo, self.btn_bg, self.btn_border, self.btn_text,
            self.spin_font, self.spin_border_w, self.slider_opacity,
            self.spin_width, self.spin_height,
        ]
        for w in widgets:
            w.blockSignals(True)

        self.lbl_label.setText(node.label)
        self.lbl_body.setPlainText(node.body_text)
        self.lbl_category.setText(node.category)

        idx = self.shape_combo.findData(node.node_shape)
        if idx >= 0:
            self.shape_combo.setCurrentIndex(idx)

        self.btn_bg.set_color(node.bg_color)
        self.btn_border.set_color(node.border_color)
        self.btn_text.set_color(node.text_color)
        self.spin_font.setValue(node.font_size)
        self.spin_border_w.setValue(node.border_width)
        self.slider_opacity.setValue(int(node.opacity() * 100))
        self.spin_width.setValue(int(node.width))
        self.spin_height.setValue(int(node.height))

        for w in widgets:
            w.blockSignals(False)

    def clear(self):
        self._node = None
        self.setEnabled(False)

    def _emit_changes(self, *_):
        if self._node is None:
            return
        self.properties_changed.emit(self._collect())

    def _collect(self) -> dict:
        return {
            "label"       : self.lbl_label.text().strip() or "Node",
            "body_text"   : self.lbl_body.toPlainText(),
            "category"    : self.lbl_category.text(),
            "shape"       : self.shape_combo.currentData(),
            "bg_color"    : self.btn_bg.hex_color,
            "border_color": self.btn_border.hex_color,
            "text_color"  : self.btn_text.hex_color,
            "font_size"   : self.spin_font.value(),
            "border_width": self.spin_border_w.value(),
            "opacity"     : self.slider_opacity.value() / 100.0,
            "width"       : self.spin_width.value(),
            "height"      : self.spin_height.value(),
        }


# ──────────────────────────────────────────────────────────────────────────────
# EdgePropertiesDialog
# ──────────────────────────────────────────────────────────────────────────────

class EdgePropertiesDialog(QDialog):
    """
    Dialog for editing an existing edge's label, colour, style, and direction.

    Attributes:
        edge: The EdgeItem being edited.
    """

    def __init__(self, edge: EdgeItem, parent=None):
        super().__init__(parent)
        self.edge = edge
        self.setWindowTitle("Edge Properties")
        self.setMinimumWidth(340)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        layout = QFormLayout(self)

        self.lbl_edit = QLineEdit(self.edge.label)
        layout.addRow("Label:", self.lbl_edit)

        self.color_btn = _ColourButton(self.edge.color)
        layout.addRow("Colour:", self.color_btn)

        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.5, 12.0)
        self.width_spin.setSingleStep(0.5)
        self.width_spin.setValue(self.edge.width)
        layout.addRow("Width:", self.width_spin)

        self.style_combo = QComboBox()
        for key in ALL_EDGE_STYLES:
            self.style_combo.addItem(_EDGE_STYLE_DISPLAY.get(key, key), key)
        idx = self.style_combo.findData(self.edge.style)
        if idx >= 0:
            self.style_combo.setCurrentIndex(idx)
        layout.addRow("Style:", self.style_combo)

        self.directed_cb = QCheckBox("Directed (show arrowhead)")
        self.directed_cb.setChecked(self.edge.directed)
        layout.addRow("", self.directed_cb)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_data(self) -> dict:
        return {
            "label"   : self.lbl_edit.text(),
            "color"   : self.color_btn.hex_color,
            "width"   : self.width_spin.value(),
            "style"   : self.style_combo.currentData(),
            "directed": self.directed_cb.isChecked(),
        }



