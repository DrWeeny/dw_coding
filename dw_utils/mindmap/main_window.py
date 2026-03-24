"""
MindMapWindow — top-level QMainWindow for the CFX Mind Map tool.

Classes

- MindMapWindow: Full application window with menu bar, toolbar, side panel,
  status bar, and integrated MindMapScene / MindMapView.

"""

import os
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QPointF, QSettings
from PySide6.QtGui import QKeySequence, QFont, QIcon, QColor, QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QToolBar, QStatusBar, QFileDialog,
    QMessageBox, QLabel, QSplitter, QDockWidget,
    QInputDialog, QSlider, QSpinBox,
)
import dw_utils
from dw_utils.mindmap.scene   import MindMapScene
from dw_utils.mindmap.view    import MindMapView
from dw_utils.mindmap.items   import NodeItem, EdgeItem
from dw_utils.mindmap.dialogs import (
    NodeEditorDialog, NodePropertiesPanel, EdgePropertiesDialog,
)
from dw_utils.mindmap.constants import (
    DEFAULT_BG_COLOR, DEFAULT_BORDER_COLOR, DEFAULT_TEXT_COLOR,
    DEFAULT_FONT_SIZE, DEFAULT_NODE_WIDTH, DEFAULT_NODE_HEIGHT,
    SHAPE_ROUNDED_RECT,
)

from dw_logger import get_logger

log = get_logger()

try:
    from json_utils.core import save_json_atomic, load_json
    _HAS_JSON_UTILS = True
except ImportError:
    import json as _json
    _HAS_JSON_UTILS = False

_SETTINGS_ORG  = "DWREPO"
_SETTINGS_APP  = "MindMap"
_DARK_STYLE = """
QMainWindow, QWidget {
    background: #16161e;
    color: #cdd6f4;
    font-family: "Segoe UI";
    font-size: 11px;
}
QMenuBar {
    background: #1e1e2e;
    color: #cdd6f4;
    border-bottom: 1px solid #313244;
}
QMenuBar::item:selected { background: #313244; }
QMenu {
    background: #1e1e2e;
    color: #cdd6f4;
    border: 1px solid #313244;
}
QMenu::item:selected { background: #313244; }
QToolBar {
    background: #1e1e2e;
    border-bottom: 1px solid #313244;
    spacing: 4px;
}
QStatusBar { background: #1e1e2e; color: #6c7086; }
QSplitter::handle { background: #313244; }
QDockWidget { color: #cdd6f4; }
QDockWidget::title {
    background: #1e1e2e;
    padding: 4px;
    font-weight: bold;
}
QGroupBox {
    border: 1px solid #313244;
    border-radius: 4px;
    margin-top: 8px;
    font-weight: bold;
    color: #a6adc8;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QPushButton {
    background: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 10px;
}
QPushButton:hover { background: #45475a; }
QPushButton:pressed { background: #585b70; }
QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #1e1e2e;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 3px;
    padding: 2px 4px;
}
QScrollBar:vertical { background: #1e1e2e; width: 8px; }
QScrollBar::handle:vertical { background: #45475a; border-radius: 4px; }
QSlider::groove:horizontal { background: #313244; height: 4px; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #89b4fa; width: 12px; height: 12px;
    border-radius: 6px; margin: -4px 0;
}
"""


def _save_json(path: str, data: dict) -> bool:
    if _HAS_JSON_UTILS:
        return save_json_atomic(path, data)
    try:
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as exc:
        print(f"[save_json] ERROR: {exc}")
        log.error(f"[save_json] {exc}")
        return False


def _load_json(path: str):
    if _HAS_JSON_UTILS:
        return load_json(path)
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"[load_json] ERROR: {exc}")
        log.error(f"[load_json] {exc}")
        return None


class MindMapWindow(QMainWindow):
    """
    Top-level window for the CFX Mind Map tool.

    Provides menu bar, toolbar, properties dock, canvas and status bar.
    All graph modifications are routed through MindMapScene for undo/redo support.

    Attributes:
        scene: MindMapScene holding nodes and edges.
        view:  MindMapView viewport.
        props: NodePropertiesPanel dock widget.
    """

    def __init__(self, parent=None, load_file: str = None):
        super().__init__(parent)

        self.setWindowTitle("Mind Map")
        self.setMinimumSize(1100, 700)
        self.setStyleSheet(_DARK_STYLE)

        # Try to restore window geometry
        self._settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)

        self._current_file = None  # type: Optional[str]
        self._connecting_mode = False

        self._build_scene()
        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self._connect_signals()

        self._restore_geometry()

        # Load default template on first launch
        # self._load_cfx_template()
        self._load_file_path = None
        if load_file:
            if not os.path.isfile(load_file) and isinstance(load_file, str):
                _tool_dir = os.path.dirname(dw_utils.__file__)
                defaut_path = os.path.join(_tool_dir, "mindmap/data", load_file)
                if not load_file.endswith(".json"):
                    defaut_path += ".json"
                load_file = defaut_path
            # Defer the actual load to showEvent so the viewport has its final
            # size when fit_all() runs (same pattern as _load_cfx_template).
            self._load_file_path = load_file


    # ── construction ─────────────────────────────────────────────────────────

    def _build_scene(self):
        self.scene = MindMapScene(self)
        self.view  = MindMapView(self.scene, self)
        # Wire minimap updates to scene changes (no polling timer)
        self.view.connect_scene_signals(self.scene)

    def _build_ui(self):
        # Central widget: view + properties dock
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view)

        # Properties dock
        self.props = NodePropertiesPanel(self)
        dock = QDockWidget("Properties", self)
        dock.setWidget(self.props)
        dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.LeftDockWidgetArea)
        dock.setMinimumWidth(260)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self._props_dock = dock

        # Status bar
        self.status = QStatusBar(self)
        self.setStatusBar(self.status)
        self._zoom_label = QLabel("Zoom: 100%")
        self._zoom_label.setStyleSheet("color:#6c7086; margin-right:10px;")
        self.status.addPermanentWidget(self._zoom_label)

    def _build_menus(self):
        mb = self.menuBar()

        # ── File ─────────────────────────────────────────────────────────────
        file_menu = mb.addMenu("File")
        self._act_new   = file_menu.addAction("New Graph",          self._new_graph,  QKeySequence.New)
        self._act_open  = file_menu.addAction("Open…",              self._open_file,  QKeySequence.Open)
        self._act_save  = file_menu.addAction("Save",               self._save_file,  QKeySequence.Save)
        self._act_saveas= file_menu.addAction("Save As…",           self._save_as,    QKeySequence("Ctrl+Shift+S"))
        file_menu.addSeparator()
        self._act_exp_png = file_menu.addAction("Export PNG…",      self._export_png)
        self._act_exp_svg = file_menu.addAction("Export SVG…",      self._export_svg)
        file_menu.addSeparator()
        file_menu.addAction("Quit", self.close, QKeySequence("Ctrl+Q"))

        # ── Edit ─────────────────────────────────────────────────────────────
        edit_menu = mb.addMenu("Edit")
        self._act_undo  = edit_menu.addAction("Undo", self.scene.undo_stack.undo, QKeySequence.Undo)
        self._act_redo  = edit_menu.addAction("Redo", self.scene.undo_stack.redo, QKeySequence.Redo)
        edit_menu.addSeparator()
        edit_menu.addAction("Select All",   self.scene.select_all,      QKeySequence("Ctrl+A"))
        edit_menu.addAction("Copy",         self.scene.copy_selection,  QKeySequence.Copy)
        edit_menu.addAction("Paste",        self.scene.paste,           QKeySequence.Paste)
        edit_menu.addAction("Delete",       self.scene.delete_selection,QKeySequence.Delete)
        edit_menu.addSeparator()
        self._act_snap = edit_menu.addAction("Snap to Grid")
        self._act_snap.setCheckable(True)
        self._act_snap.triggered.connect(self._toggle_snap)

        # ── Node ─────────────────────────────────────────────────────────────
        node_menu = mb.addMenu("Node")
        node_menu.addAction("Add Node",            self._add_node_centre, QKeySequence("Ctrl+N"))
        node_menu.addAction("Add Node at Centre",  self._add_node_centre)
        node_menu.addSeparator()
        node_menu.addAction("Edit Selected…",      self._edit_selected_node, QKeySequence("F2"))

        # ── Edge ─────────────────────────────────────────────────────────────
        edge_menu = mb.addMenu("Edge")
        self._act_connect = edge_menu.addAction(
            "Connect Mode (click source → target)",
            self._toggle_connect_mode, QKeySequence("C"))
        self._act_connect.setCheckable(True)
        edge_menu.addSeparator()
        edge_menu.addAction("Edit Selected Edge…", self._edit_selected_edge)

        # ── Layout ───────────────────────────────────────────────────────────
        layout_menu = mb.addMenu("Layout")
        layout_menu.addAction("Auto-Layout (Force-Directed)",  self.scene.auto_layout)
        layout_menu.addAction("Fit All  [F]",                  self.view.fit_all)
        layout_menu.addAction("Reset Zoom",                    self.view.reset_zoom)

        # ── Templates ─────────────────────────────────────────────────────────
        tpl_menu = mb.addMenu("Templates")
        tpl_menu.addAction("example", self._load_cfx_template)
        tpl_menu.addAction("Blank Graph",                      self._new_graph)

        # ── View ─────────────────────────────────────────────────────────────
        view_menu = mb.addMenu("View")
        view_menu.addAction("Toggle Properties Panel",
                            lambda: self._props_dock.setVisible(
                                not self._props_dock.isVisible()))
        self._act_minimap = view_menu.addAction("Toggle Minimap")
        self._act_minimap.setCheckable(True)
        self._act_minimap.setChecked(True)
        self._act_minimap.triggered.connect(
            lambda v: setattr(self.view._minimap, '_enabled', v)
            or self.view._minimap.setVisible(v)
        )

        # ── Logging ──────────────────────────────────────────────────────────
        log_menu = mb.addMenu("Logging")

        # Master toggle — turns all modules on/off at once
        self._act_log_all = log_menu.addAction("Enable All Modules")
        self._act_log_all.setCheckable(True)
        self._act_log_all.setChecked(True)
        log_menu.addSeparator()

        # Per-module toggles — all ticked by default
        self._log_module_actions = {}
        _modules = [
            ("mindmap (root)",    "dw_utils.mindmap"),
        ]
        for label, mod_name in _modules:
            act = log_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(True)
            act.setData(mod_name)
            act.triggered.connect(
                lambda checked, m=mod_name: self._on_log_module_toggled(m, checked)
            )
            self._log_module_actions[mod_name] = act

        log_menu.addSeparator()

    def _build_toolbar(self):
        tb = QToolBar("Main", self)
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        def _a(text, shortcut=None, callback=None, checkable=False):
            act = QAction(text, self)
            if shortcut:
                act.setShortcut(shortcut)
            if callback:
                act.triggered.connect(callback)
            act.setCheckable(checkable)
            tb.addAction(act)
            return act

        _a("⬛ Add Node",   "Ctrl+N",     self._add_node_centre)
        tb.addSeparator()
        self._tb_connect = _a("🔗 Connect",  "C",          self._toggle_connect_mode, True)
        tb.addSeparator()
        _a("↩ Undo",       "Ctrl+Z",     self.scene.undo_stack.undo)
        _a("↪ Redo",       "Ctrl+Y",     self.scene.undo_stack.redo)
        tb.addSeparator()
        _a("⊞ Fit All",    "F",          self.view.fit_all)
        _a("⟳ Layout",     None,         self.scene.auto_layout)
        tb.addSeparator()
        _a("💾 Save",      "Ctrl+S",     self._save_file)
        _a("📂 Open",      "Ctrl+O",     self._open_file)

    # ── signal wiring ─────────────────────────────────────────────────────────

    def _connect_signals(self):
        self.scene.status_message.connect(self._show_status)
        self.scene.scene_changed.connect(self._on_scene_changed)
        self.scene.node_double_clicked.connect(self._on_node_double_click)
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self.view.zoom_changed.connect(self._on_zoom_changed)
        self.view.background_clicked.connect(self._on_background_click)
        self.props.properties_changed.connect(self._on_props_changed)
        self.props.connect_edge_requested.connect(self._start_edge_from_selected)

    # ── slot handlers ─────────────────────────────────────────────────────────

    def _show_status(self, msg: str):
        self.status.showMessage(msg, 4000)

    def _on_scene_changed(self):
        title = "CFX Mind Map"
        if self._current_file:
            title += f" — {os.path.basename(self._current_file)}"
        self.setWindowTitle(title + " *")

    def _on_zoom_changed(self, factor: float):
        self._zoom_label.setText(f"Zoom: {factor * 100:.0f}%")

    def _on_selection_changed(self):
        sel_nodes = [i for i in self.scene.selectedItems() if isinstance(i, NodeItem)]
        sel_edges = [i for i in self.scene.selectedItems() if isinstance(i, EdgeItem)]

        if len(sel_nodes) == 1:
            self.props.load_node(sel_nodes[0])
        else:
            self.props.clear()

        # Show edge count in status
        if sel_edges:
            self._show_status(f"{len(sel_edges)} edge(s) selected — double-click to edit")

    def _on_node_double_click(self, node_id: str):
        node = self.scene.get_node(node_id)
        if node is None:
            return
        dlg = NodeEditorDialog(node, self)
        if dlg.exec_():
            self.scene.edit_node(node, dlg.get_data())
            self.props.load_node(node)

    def _on_background_click(self, x, y):
        if self._connecting_mode:
            self._show_status("Click a node to start the edge, not empty space.")

    def _on_props_changed(self, data: dict):
        sel = [i for i in self.scene.selectedItems() if isinstance(i, NodeItem)]
        for node in sel:
            self.scene.edit_node(node, data)

    # ── logging controls ──────────────────────────────────────────────────────

    def _on_log_module_toggled(self, module_name, checked):
        """Enable or disable DEBUG logging for a single module."""
        print(f"[MindMap Logging] {module_name}: {checked}")

    def _on_log_all_toggled(self, checked):
        """Enable or disable DEBUG logging for all modules at once."""
        print(f"[MindMap Logging] All modules: toggled")

    # ── connect mode ──────────────────────────────────────────────────────────

    def _toggle_connect_mode(self, checked=None):
        if checked is None:
            checked = not self._connecting_mode
        self._connecting_mode = checked
        self._tb_connect.setChecked(checked)
        self._act_connect.setChecked(checked)
        if checked:
            self._show_status("Connect mode ON — click source node, then target node.")
            self.view.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        else:
            self._show_status("Connect mode OFF.")
            self.view.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)
            self.scene.cancel_edge_draw()

    def _start_edge_from_selected(self):
        sel = [i for i in self.scene.selectedItems() if isinstance(i, NodeItem)]
        if sel:
            self.scene.start_edge_from(sel[0])
            self._connecting_mode = True
            self.view.setDragMode(QtWidgets.QGraphicsView.NoDrag)
            self._tb_connect.setChecked(True)

    def _toggle_snap(self, checked: bool):
        self.scene.snap_grid = checked
        self.scene.update()

    def _add_node_centre(self):
        """Add a new node at the centre of the current viewport."""
        vp_center = self.view.mapToScene(
            self.view.viewport().rect().center()
        )
        node = self.scene.create_node(pos=vp_center)
        self._show_status(f"Node '{node.label}' added.")

    def _edit_selected_node(self):
        sel = [i for i in self.scene.selectedItems() if isinstance(i, NodeItem)]
        if sel:
            self._on_node_double_click(sel[0].node_id)

    def _edit_selected_edge(self):
        sel = [i for i in self.scene.selectedItems() if isinstance(i, EdgeItem)]
        if not sel:
            self._show_status("No edge selected.")
            return
        edge = sel[0]
        dlg  = EdgePropertiesDialog(edge, self)
        if dlg.exec_():
            data = dlg.get_data()
            edge.label    = data["label"]
            edge.color    = data["color"]
            edge.width    = data["width"]
            edge.style    = data["style"]
            edge.directed = data["directed"]
            edge._refresh()
            self.scene.scene_changed.emit()

    # ── mouse event override for connect mode ─────────────────────────────────

    def _handle_view_mouse_press(self, event):
        """Intercept clicks in connect mode to wire source → target."""
        if not self._connecting_mode:
            return False
        scene_pos = self.view.mapToScene(event.pos())
        items     = self.scene.items(scene_pos)
        nodes     = [i for i in items if isinstance(i, NodeItem)]
        if not nodes:
            return False
        node = nodes[0]
        if self.scene._edge_src is None:
            self.scene.start_edge_from(node)
        else:
            if node is not self.scene._edge_src:
                self.scene.create_edge(self.scene._edge_src, node)
                self.scene._edge_src = None
                self._toggle_connect_mode(False)
        return True

    # ── file operations ────────────────────────────────────────────────────────

    def _default_dir(self) -> str:
        return os.environ.get(
            "CFX_MINDMAP_DEFAULT_DIR",
            self._settings.value("last_dir", os.path.expanduser("~"))
        )

    def _new_graph(self):
        if not self._confirm_unsaved():
            return
        self.scene.clear_graph()
        self._current_file = None
        self.setWindowTitle("CFX Mind Map — New Graph")
        self._show_status("New graph created.")

    def _open_file(self):
        if not self._confirm_unsaved():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Mind Map", self._default_dir(), "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        data = _load_json(path)
        if data is None:
            QMessageBox.critical(self, "Error", f"Could not load file:\n{path}")
            return
        self.scene.from_dict(data)
        self._current_file = path
        self._settings.setValue("last_dir", os.path.dirname(path))
        self.view.fit_all()
        self.setWindowTitle(f"CFX Mind Map — {os.path.basename(path)}")
        self._show_status(f"Loaded: {path}")

    def _save_file(self):
        if self._current_file is None:
            self._save_as()
        else:
            self._do_save(self._current_file)

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Mind Map", self._default_dir(), "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        if not path.endswith(".json"):
            path += ".json"
        self._do_save(path)

    def _do_save(self, path: str):
        data = self.scene.to_dict()
        if _save_json(path, data):
            self._current_file = path
            self._settings.setValue("last_dir", os.path.dirname(path))
            self.setWindowTitle(f"CFX Mind Map — {os.path.basename(path)}")
            self._show_status(f"Saved: {path}")
        else:
            QMessageBox.critical(self, "Error", f"Could not save file:\n{path}")

    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export PNG", self._default_dir(), "PNG Image (*.png)"
        )
        if not path:
            return
        if not path.endswith(".png"):
            path += ".png"
        self._render_to_image(path, "png")

    def _export_svg(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SVG", self._default_dir(), "SVG Vector (*.svg)"
        )
        if not path:
            return
        if not path.endswith(".svg"):
            path += ".svg"
        # Use QPicture / QSvgGenerator
        try:
            from PySide6.QtSvg import QSvgGenerator
            gen = QSvgGenerator()
            gen.setFileName(path)
            nodes = self.scene.all_nodes()
            if nodes:
                from PySide6.QtCore import QRectF
                xs = [n.pos().x() for n in nodes]
                ys = [n.pos().y() for n in nodes]
                x2 = [n.pos().x() + n.width  for n in nodes]
                y2 = [n.pos().y() + n.height for n in nodes]
                br = QRectF(min(xs) - 40, min(ys) - 40,
                            max(x2) - min(xs) + 80,
                            max(y2) - min(ys) + 80)
            else:
                br = self.scene.sceneRect()
            gen.setSize(QtCore.QSize(int(br.width()), int(br.height())))
            gen.setViewBox(br)
            gen.setTitle("CFX Mind Map")
            painter = QtGui.QPainter()
            painter.begin(gen)
            self.scene.render(painter, source=br)
            painter.end()
            self._show_status(f"SVG exported: {path}")
        except Exception as exc:
            self._render_to_image(path.replace(".svg", ".png"), "png")
            self._show_status(f"SVG unavailable, exported PNG instead: {exc}")

    def _render_to_image(self, path: str, fmt: str):
        nodes = self.scene.all_nodes()
        if nodes:
            xs = [n.pos().x() for n in nodes]
            ys = [n.pos().y() for n in nodes]
            x2 = [n.pos().x() + n.width  for n in nodes]
            y2 = [n.pos().y() + n.height for n in nodes]
            from PySide6.QtCore import QRectF
            br = QRectF(min(xs) - 40, min(ys) - 40,
                        max(x2) - min(xs) + 80,
                        max(y2) - min(ys) + 80)
        else:
            br = self.scene.sceneRect()

        img = QtGui.QImage(
            int(br.width() * 2), int(br.height() * 2),
            QtGui.QImage.Format_ARGB32,
        )
        img.setDevicePixelRatio(2.0)
        img.fill(QColor("#0f0f1a"))
        painter = QtGui.QPainter(img)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        self.scene.render(painter, source=br)
        painter.end()
        img.save(path)
        self._show_status(f"PNG exported: {path}")

    def _confirm_unsaved(self) -> bool:
        """Returns True if the user confirms (or there are no changes)."""
        # Simple heuristic: if title ends with ' *' there are unsaved changes
        if self.windowTitle().endswith(" *"):
            res = QMessageBox.question(
                self, "Unsaved Changes",
                "There are unsaved changes. Continue without saving?",
                QMessageBox.Yes | QMessageBox.No,
            )
            return res == QMessageBox.Yes
        return True

    # ── template ──────────────────────────────────────────────────────────────

    def _load_cfx_template(self):
        if self.scene.all_nodes() and not self._confirm_unsaved():
            return
        self._current_file = None
        QtCore.QTimer.singleShot(100, self.view.fit_all)

    # ── keyboard shortcut for connect mode in view ────────────────────────────

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_C and not event.modifiers():
            self._toggle_connect_mode(not self._connecting_mode)
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            if self._connecting_mode:
                self._toggle_connect_mode(False)
                event.accept()
                return
        super().keyPressEvent(event)

    # ── mouse press pass-through for connect mode ─────────────────────────────

    def eventFilter(self, obj, event):
        if (obj is self.view.viewport()
                and event.type() == QtCore.QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton
                and self._connecting_mode):
            if self._handle_view_mouse_press(event):
                return True
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        self.view.viewport().installEventFilter(self)
        # Load the file passed via constructor now that the viewport has its
        # final size, then fit_all so everything is visible on first paint.
        if self._load_file_path:
            _path = self._load_file_path
            self._load_file_path = None
            QtCore.QTimer.singleShot(0, lambda: self._open_file(_path))


    # ── geometry persistence ──────────────────────────────────────────────────

    def _restore_geometry(self):
        geom = self._settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        state = self._settings.value("windowState")
        if state:
            self.restoreState(state)

    def closeEvent(self, event):
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("windowState", self.saveState())
        super().closeEvent(event)




