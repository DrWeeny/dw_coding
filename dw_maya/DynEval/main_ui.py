"""
DynEval Main UI — Simulation Management Tool

Layout
------
DynEvalUI (QMainWindow)
├── SimTreePanel          discovers + displays sim hierarchy, publishes SELECTED_NODE
└── SimDetailPanel
    ├── CacheVersionPanel  version list + create / attach / delete
    └── MapListPanel       map list + "Paint in Slimfast" trigger

DataHub contract (all inter-widget communication goes through these keys):
    SELECTED_NODE          SimItem | None         tree → all panels
    FRAME_RANGE            tuple[int, int]         main window → cache panel
    CACHE_SELECTED         CacheInfo | None        cache panel → (comments etc.)
    CACHE_CREATE_REQUESTED SimItem                 tree ctx menu → cache panel
    MAP_SELECTED           MapInfo | None          map panel → (external)
    PAINT_REQUESTED        MapInfo                 map panel → main window → Slimfast

DynEvalMainWindow contract (expected from wgt_base.py):
    self.hub               DataHub instance
    hub_subscribe(key, cb) subscribe to a hub key
    hub_publish(key, val)  publish a value to a hub key
    hub_get(key)           read current value without subscribing
"""

from __future__ import annotations

from typing import Optional
from pathlib import Path

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Slot
    from shiboken6 import wrapInstance
except ImportError:
    # Fallback for older Maya versions shipping PySide2
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Slot
    from shiboken2 import wrapInstance

import maya.cmds as cmds

import maya.OpenMayaUI as omui

from dw_logger import get_logger
import json_utils.core as dw_json

from dw_maya.DynEval.hub_keys import DynEvalKeys
import dw_maya.DynEval.sim_widget.wgt_commentary
from dw_maya.DynEval.sim_widget.wgt_commentary import CommentEditor
from dw_maya.DynEval.sim_registry import discover_all, build_solver_item
from dw_maya.DynEval.sim_widget.wgt_treewidget_toggle import SimulationTreeView
from dw_maya.DynEval.sim_widget.wgt_base import DynEvalMainWindow, DynEvalWidgetBase

logger = get_logger()


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def get_maya_window() -> QtWidgets.QWidget:
    return wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)


# ============================================================================
# MAIN WINDOW
# ============================================================================

class DynEvalUI(DynEvalMainWindow):
    """
    Thin orchestration layer.

    Responsibilities:
    - Creates the hub (via DynEvalMainWindow base).
    - Lays out SimTreePanel + SimDetailPanel.
    - Bridges PAINT_REQUESTED → Slimfast (the only cross-tool concern).
    - Exposes build_tree / refresh_tree as the public API for external callers.
    """

    def __init__(self, parent=None):
        super().__init__(parent or get_maya_window())

        self.setWindowTitle("DynEval")
        self.setObjectName("DynEvalUI")
        self.setGeometry(867, 546, 960, 540)
        self.setMouseTracking(True)

        self._central = QtWidgets.QWidget(self)
        self.setCentralWidget(self._central)

        self._build_layout()
        self._setup_hub()
        self._sync_frame_range()
        self.build_tree()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self):
        layout = QtWidgets.QHBoxLayout(self._central)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.tree_panel   = SimTreePanel(self.hub, parent=self)
        self.detail_panel = SimDetailPanel(self.hub, parent=self)

        layout.addWidget(self.tree_panel,   stretch=1)
        layout.addWidget(self.detail_panel, stretch=2)

    # ------------------------------------------------------------------
    # Hub setup
    # ------------------------------------------------------------------

    def _setup_hub(self):
        self.hub_subscribe(DynEvalKeys.PAINT_REQUESTED, self._on_paint_requested)

    def _sync_frame_range(self):
        start = int(cmds.playbackOptions(q=True, min=True))
        end   = int(cmds.playbackOptions(q=True, max=True))
        self.hub_publish(DynEvalKeys.FRAME_RANGE, (start, end))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_tree(self):
        self.tree_panel.build_tree()

    def refresh_tree(self):
        self.tree_panel.refresh_tree()

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_paint_requested(self, _old, map_info):
        """Bridge PAINT_REQUESTED to Slimfast — the only cross-tool call."""
        if map_info is None:
            return
        try:
            from dw_maya.dw_paint import slimfast
            slimfast.open_for(map_info)
        except Exception as e:
            logger.error(f"Slimfast launch failed: {e}")
            cmds.warning(f"Could not open Slimfast: {e}")


# ============================================================================
# TREE PANEL
# ============================================================================

class SimTreePanel(DynEvalWidgetBase):
    """
    Left panel — discovers all registered sim systems and builds the tree.

    Publishes
    ---------
    SELECTED_NODE          on any selection change
    CACHE_CREATE_REQUESTED from the context menu → handled by CacheVersionPanel
    """

    def __init__(self, hub, parent=None):
        super().__init__(hub, parent)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.tree = SimulationTreeView()
        self.tree.setMinimumWidth(260)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        layout.addWidget(self.tree)

        self._status = _StatusBar()
        layout.addWidget(self._status)

        # Undo / redo — only active while the mouse is inside this panel
        self._undo = QtGui.QShortcut(QtGui.QKeySequence(), self)
        self._redo = QtGui.QShortcut(QtGui.QKeySequence(), self)
        self._undo.activated.connect(self._handle_undo)
        self._redo.activated.connect(self._handle_redo)

        self.tree.selectionModel().selectionChanged.connect(self._on_selection)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def build_tree(self):
        self._status.show_loading("Building…")
        self.tree.clear()

        try:
            systems = discover_all()   # {system_name: [solver_node, ...]}
            if not systems:
                self._status.show_message("No simulation nodes found.")
                return

            for _system_name, solver_nodes in systems.items():
                for solver_node in solver_nodes:
                    row = build_solver_item(solver_node)
                    if row:
                        self.tree.model().invisibleRootItem().appendRow(row)

            self._expand_top_level()
            self._status.hide()

        except Exception as e:
            logger.error(f"build_tree failed: {e}")
            self._status.show_error(str(e))

    def refresh_tree(self):
        """Rebuild while preserving expansion state."""
        saved = self._collect_expanded_paths()
        self.build_tree()
        self._restore_expanded_paths(saved)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_selection(self):
        items = self.tree.get_selected_items()
        self.publish(DynEvalKeys.SELECTED_NODE, items[0] if items else None)

    def selected_item(self):
        items = self.tree.get_selected_items()
        return items[0] if items else None

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos: QtCore.QPoint):
        item = self.selected_item()
        if not item:
            return

        menu = QtWidgets.QMenu(self)
        node_type = getattr(item, "node_type", None)

        menu.addAction("Select in Maya", self._select_in_maya)
        menu.addSeparator()

        if node_type in ("nCloth", "hairSystem"):
            cache_menu = menu.addMenu("Cache")
            cache_menu.addAction("Create nCache", self._request_cache_create)

        elif node_type == "nucleus":
            menu.addAction("Refresh", self.refresh_tree)

        menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def _select_in_maya(self):
        item = self.selected_item()
        if not item:
            return

        node_type = getattr(item, "node_type", None)
        if node_type == "nCloth":
            target = getattr(item, "mesh_transform", item.node)
        elif node_type in ("nRigid", "dynamicConstraint"):
            rels = cmds.listRelatives(item.node, p=True)
            target = rels[0] if rels else item.node
        else:
            target = item.node

        cmds.select(target, r=True)

    def _request_cache_create(self):
        item = self.selected_item()
        if item:
            self.publish(DynEvalKeys.CACHE_CREATE_REQUESTED, item)

    # ------------------------------------------------------------------
    # Undo / redo
    # ------------------------------------------------------------------

    def _handle_undo(self):
        cmds.undo()
        self.refresh_tree()

    def _handle_redo(self):
        cmds.redo()
        self.refresh_tree()

    def enterEvent(self, event):
        super().enterEvent(event)
        self._undo.setKey(QtGui.QKeySequence.Undo)
        self._redo.setKey(QtGui.QKeySequence.Redo)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._undo.setKey(QtGui.QKeySequence())
        self._redo.setKey(QtGui.QKeySequence())

    # ------------------------------------------------------------------
    # Expansion helpers
    # ------------------------------------------------------------------

    def _expand_top_level(self):
        model = self.tree.model()
        for i in range(model.rowCount()):
            self.tree.expand(model.index(i, 0))

    def _collect_expanded_paths(self) -> set[str]:
        expanded: set[str] = set()

        def walk(parent_idx):
            if self.tree.isExpanded(parent_idx):
                item = self.tree.model().itemFromIndex(parent_idx)
                if item:
                    expanded.add(_item_path(item))
            for row in range(self.tree.model().rowCount(parent_idx)):
                walk(self.tree.model().index(row, 0, parent_idx))

        walk(QtCore.QModelIndex())
        return expanded

    def _restore_expanded_paths(self, paths: set[str]):
        def walk(parent_idx):
            item = self.tree.model().itemFromIndex(parent_idx)
            if item and _item_path(item) in paths:
                self.tree.expand(parent_idx)
            for row in range(self.tree.model().rowCount(parent_idx)):
                walk(self.tree.model().index(row, 0, parent_idx))

        walk(QtCore.QModelIndex())


def _item_path(item: QtGui.QStandardItem) -> str:
    """Stable string key for a tree item (root → leaf slash-joined)."""
    parts: list[str] = []
    while item:
        parts.append(item.text())
        item = item.parent()
    return "/".join(reversed(parts))


# ============================================================================
# DETAIL PANEL  (container)
# ============================================================================

class SimDetailPanel(DynEvalWidgetBase):
    """
    Right panel — just a tab container.

    Each sub-panel subscribes to the hub independently;
    this class has no logic of its own.
    """

    def __init__(self, hub, parent=None):
        super().__init__(hub, parent)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QtWidgets.QTabWidget()
        self.cache_tab = CacheVersionPanel(hub)
        self.maps_tab  = MapListPanel(hub)
        self.comment_tab = CommentEditor(hub)

        self.tabs.addTab(self.cache_tab, "Cache")
        self.tabs.addTab(self.maps_tab,  "Maps")
        self.tabs.addTab(self.comment_tab, "Comment")
        layout.addWidget(self.tabs)


# ============================================================================
# CACHE VERSION PANEL
# ============================================================================

class CacheVersionPanel(DynEvalWidgetBase):
    """
    Lists available cache versions for the selected node.
    Provides create / attach / delete actions.

    Subscribes to
    -------------
    SELECTED_NODE          repopulates the version list
    FRAME_RANGE            updates the frame-range display
    CACHE_CREATE_REQUESTED triggers cache creation directly
    """

    def __init__(self, hub, parent=None):
        super().__init__(hub, parent)
        self._current_item = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(4)

        # -- Frame range row -----------------------------------------------
        fr_row = QtWidgets.QHBoxLayout()
        fr_row.addWidget(QtWidgets.QLabel("Frame range:"))
        self._fr_label = QtWidgets.QLabel("—")
        fr_row.addWidget(self._fr_label)
        fr_row.addStretch()
        layout.addLayout(fr_row)

        # -- Version list --------------------------------------------------
        self.cache_list = QtWidgets.QTreeWidget()
        self.cache_list.setHeaderLabels(["Version", "Date", "Frames"])
        self.cache_list.setRootIsDecorated(False)
        self.cache_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        layout.addWidget(self.cache_list)

        # -- Action buttons ------------------------------------------------
        btn_row = QtWidgets.QHBoxLayout()
        self._btn_create = QtWidgets.QPushButton("Create")
        self._btn_attach = QtWidgets.QPushButton("Attach")
        self._btn_delete = QtWidgets.QPushButton("Delete")

        for btn in (self._btn_create, self._btn_attach, self._btn_delete):
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

        self._set_actions_enabled(False)

        # -- Hub subscriptions --------------------------------------------
        self.subscribe(DynEvalKeys.SELECTED_NODE,          self._on_node_changed)
        self.subscribe(DynEvalKeys.FRAME_RANGE,            self._on_frame_range)
        self.subscribe(DynEvalKeys.CACHE_CREATE_REQUESTED, self._on_create_requested)

        # -- Widget connections --------------------------------------------
        self.cache_list.currentItemChanged.connect(self._on_version_selected)
        self._btn_create.clicked.connect(self._create_cache)
        self._btn_attach.clicked.connect(self._attach_selected)
        self._btn_delete.clicked.connect(self._delete_selected)

    # ------------------------------------------------------------------
    # Hub callbacks
    # ------------------------------------------------------------------

    def _on_node_changed(self, _old, new_item):
        self._current_item = new_item
        self._rebuild_list()
        self._set_actions_enabled(new_item is not None)

    def _on_frame_range(self, _old, frame_range):
        if frame_range:
            self._fr_label.setText(f"{frame_range[0]} – {frame_range[1]}")

    def _on_create_requested(self, _old, item):
        """Cache creation triggered from the tree context menu."""
        if item:
            self._current_item = item
            self._create_cache()

    # ------------------------------------------------------------------
    # Version list
    # ------------------------------------------------------------------

    def _rebuild_list(self):
        self.cache_list.clear()
        if not self._current_item:
            return
        if not hasattr(self._current_item, "get_cache_list"):
            return

        for cache_info in self._current_item.get_cache_list():
            frames = ""
            if hasattr(cache_info, "start") and hasattr(cache_info, "end"):
                frames = f"{cache_info.start} – {cache_info.end}"
            date = getattr(cache_info, "date", "")

            row = QtWidgets.QTreeWidgetItem([cache_info.version, date, frames])
            row.setData(0, QtCore.Qt.UserRole, cache_info)
            self.cache_list.addTopLevelItem(row)

    def _selected_cache_info(self):
        row = self.cache_list.currentItem()
        return row.data(0, QtCore.Qt.UserRole) if row else None

    def _set_actions_enabled(self, enabled: bool):
        self._btn_create.setEnabled(enabled)
        self._btn_attach.setEnabled(enabled)
        self._btn_delete.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_version_selected(self, current, _previous):
        cache_info = current.data(0, QtCore.Qt.UserRole) if current else None
        self.publish(DynEvalKeys.CACHE_SELECTED, cache_info)

    def _create_cache(self):
        if not self._current_item:
            return
        # TODO: system = get_system(self._current_item.node_type)
        #       system.cache_ops.create(self._current_item, self.hub_get(DynEvalKeys.FRAME_RANGE))
        #       self._rebuild_list()
        logger.debug("CacheVersionPanel._create_cache: not yet implemented")

    def _attach_selected(self):
        cache_info = self._selected_cache_info()
        if not (cache_info and self._current_item):
            return
        # TODO: system.cache_ops.attach(self._current_item, cache_info)
        logger.debug("CacheVersionPanel._attach_selected: not yet implemented")

    def _delete_selected(self):
        cache_info = self._selected_cache_info()
        if not (cache_info and self._current_item):
            return
        # TODO: system.cache_ops.delete(self._current_item, cache_info)
        #       self._rebuild_list()
        logger.debug("CacheVersionPanel._delete_selected: not yet implemented")


# ============================================================================
# MAP LIST PANEL
# ============================================================================

class MapListPanel(DynEvalWidgetBase):
    """
    Lists paintable maps for the selected node.
    "Paint" button publishes PAINT_REQUESTED → DynEvalUI bridges to Slimfast.

    Subscribes to
    -------------
    SELECTED_NODE          repopulates the map list
    """

    def __init__(self, hub, parent=None):
        super().__init__(hub, parent)
        self._current_item = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(4)

        self.map_list = QtWidgets.QListWidget()
        self.map_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        layout.addWidget(self.map_list)

        btn_row = QtWidgets.QHBoxLayout()
        self._btn_paint = QtWidgets.QPushButton("Paint in Slimfast")
        self._btn_paint.setEnabled(False)
        btn_row.addWidget(self._btn_paint)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Hub subscriptions
        self.subscribe(DynEvalKeys.SELECTED_NODE, self._on_node_changed)

        # Widget connections
        self.map_list.currentRowChanged.connect(self._on_map_selected)
        self._btn_paint.clicked.connect(self._request_paint)

    # ------------------------------------------------------------------
    # Hub callbacks
    # ------------------------------------------------------------------

    def _on_node_changed(self, _old, new_item):
        self._current_item = new_item
        self._rebuild_list()

    # ------------------------------------------------------------------
    # Map list
    # ------------------------------------------------------------------

    def _rebuild_list(self):
        self.map_list.clear()
        self._btn_paint.setEnabled(False)

        if not self._current_item:
            return
        if not hasattr(self._current_item, "get_maps"):
            return

        for map_info in self._current_item.get_maps():
            row = QtWidgets.QListWidgetItem(map_info.name)
            row.setData(QtCore.Qt.UserRole, map_info)
            self.map_list.addItem(row)

    def _selected_map_info(self):
        row = self.map_list.currentItem()
        return row.data(QtCore.Qt.UserRole) if row else None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_map_selected(self, _row: int):
        map_info = self._selected_map_info()
        self._btn_paint.setEnabled(map_info is not None)
        self.publish(DynEvalKeys.MAP_SELECTED, map_info)

    def _request_paint(self):
        map_info = self._selected_map_info()
        if map_info:
            self.publish(DynEvalKeys.PAINT_REQUESTED, map_info)

class CommentPanel(DynEvalWidgetBase):
    """
    Onglet commentaire — un commentaire par version de cache.

    Subscribes to
    -------------
    SELECTED_NODE     met à jour le titre, vide l'éditeur
    CACHE_SELECTED    charge le commentaire correspondant à cette version
    """

    def __init__(self, hub, parent=None):
        super().__init__(hub, parent)
        self._current_item  = None
        self._current_cache = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- ton widget existant ----------------------------------------
        self.editor = dw_maya.DynEval.sim_widget.wgt_commentary.CommentEditor(parent=self)
        layout.addWidget(self.editor)
        # ----------------------------------------------------------------

        self.subscribe(DynEvalKeys.SELECTED_NODE,  self._on_node_changed)
        self.subscribe(DynEvalKeys.CACHE_SELECTED, self._on_cache_selected)

        # signal émis par wgt_commentaire quand l'utilisateur sauvegarde
        self.editor.save_requested.connect(self._save_comment)   # adjust this

    # ------------------------------------------------------------------
    # Hub callbacks
    # ------------------------------------------------------------------

    def _on_node_changed(self, _old, new_item):
        self._current_item  = new_item
        self._current_cache = None

        title = getattr(new_item, "short_name", str(new_item)) if new_item else ""
        self.editor.setTitle(title)      # adjust this
        self.editor.setComment("")       # adjust this

    def _on_cache_selected(self, _old, cache_info):
        self._current_cache = cache_info
        self._load_comment()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _load_comment(self):
        self.editor.setComment("")       # adjust this

        if not self._current_item or not self._current_cache:
            return

        try:
            metadata_path = Path(self._current_item.metadata())
            if not metadata_path.exists():
                return

            data   = dw_json.load_json(str(metadata_path))
            solver = getattr(self._current_item, "solver_name", "")
            text   = (data
                      .get("comment", {})
                      .get(solver, {})
                      .get(self._current_cache.version, ""))
            self.editor.setComment(text)   # adjust this

        except Exception as e:
            logger.warning(f"Commentaire non chargé : {e}")

    def _save_comment(self, comment: str):
        if not self._current_item or not self._current_cache:
            return

        try:
            metadata_path = Path(self._current_item.metadata())
            solver = getattr(self._current_item, "solver_name", "")

            payload = {"comment": {solver: {self._current_cache.version: comment}}}

            if metadata_path.exists():
                dw_json.merge_json(str(metadata_path), payload, defer=True)
            else:
                dw_json.save_json(str(metadata_path), payload, defer=True)

            self.publish(DynEvalKeys.COMMENT_SAVED, comment)

        except Exception as e:
            logger.error(f"Échec sauvegarde commentaire : {e}")

# ============================================================================
# INTERNAL: STATUS BAR
# ============================================================================

class _StatusBar(QtWidgets.QWidget):
    """Minimal inline loading / error indicator for the tree panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self._icon  = QtWidgets.QLabel()
        self._icon.setFixedSize(14, 14)
        self._label = QtWidgets.QLabel()
        self._label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        layout.addWidget(self._icon)
        layout.addWidget(self._label, stretch=1)
        self.hide()

    def show_loading(self, message: str):
        self._label.setText(message)
        self.show()

    def show_message(self, message: str):
        self._label.setText(message)
        self.show()

    def show_error(self, message: str):
        self._label.setText(f"⚠  {message}")
        self.show()

    def hide(self):
        self._label.clear()
        super().hide()


# ============================================================================
# LAUNCH
# ============================================================================

_instance: Optional[DynEvalUI] = None


def show_ui() -> DynEvalUI:
    global _instance
    try:
        _instance.close()
        _instance.deleteLater()
    except Exception:
        pass

    _instance = DynEvalUI()
    _instance.show()
    return _instance