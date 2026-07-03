"""
DynEval Main UI — Simulation Management Tool

Layout
------
DynEvalUI (QMainWindow)
├── SimTreePanel          discovers + displays sim hierarchy, publishes SELECTED_NODE
└── SimDetailPanel
    ├── CacheVersionPanel  version list + create / attach / delete
r    └── MapListPanel       map list + type combo; double-click = artisan paint

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

from functools import partial
from typing import Optional

from dw_maya.DynEval.sim_cmds.compat import (
    QtCore, QtGui, QtWidgets, Qt, Signal, Slot,
    wrapInstance, QShortcut, qt_exec,
)


import maya.cmds as cmds
import maya.OpenMayaUI as omui

from dw_logger import get_logger

from .hub_keys import DynEvalKeys
from .dendrology.map_leaf import MapInfo
from . import sim_cmds
# Ensure available simulation systems register themselves on import (nucleus, ...).
# Importing the systems package triggers each backend module to call register()
# (see systems/__init__.py). This must happen before discover_all() is used.
import traceback
try:
    # Importing the systems package triggers each backend module to call register().
    # Wrap in try/except so import-time exceptions are visible in the Script Editor
    # instead of silently failing and leaving the registry empty.
    import dw_maya.DynEval.systems  # noqa: F401
except Exception:
    traceback.print_exc()

import dw_maya.DynEval.sim_registry  # noqa: F401
from dw_maya.DynEval.sim_registry import discover_all, build_solver_item, get_system
from dw_maya.DynEval.sim_widget import SimulationTreeView
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
    - Handles PAINT_REQUESTED via the dw_paint stack (NClothMap.paint()).
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
        """Open Maya's artisan paint tool on the requested nucleus map.

        Goes through the dw_paint weight-source stack (NClothMap) so the
        paint entry point is the same logic Slimfast uses — DynEval just
        skips the Slimfast UI and calls use_map + paint directly.
        """
        if map_info is None:
            return
        try:
            from dw_maya.dw_nucleus_utils.dw_ncloth_class import NClothMap
            from dw_maya.dw_nucleus_utils.dw_core import get_mesh_from_nucx_node

            mesh = map_info.mesh or get_mesh_from_nucx_node(map_info.node)
            if not mesh or not cmds.objExists(mesh):
                cmds.warning(
                    f"No mesh resolved for '{map_info.node}' - cannot paint."
                )
                return

            # artAttrNClothToolScript works on the current selection
            cmds.select(mesh, replace=True)
            source = NClothMap(map_info.node, mesh, map_info.name)
            source.paint()
        except Exception as e:
            logger.error(f"Paint launch failed: {e}")
            cmds.warning(f"Could not open paint tool: {e}")


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
        self._undo = QShortcut(QtGui.QKeySequence(), self)
        self._redo = QShortcut(QtGui.QKeySequence(), self)
        self._undo.activated.connect(self._handle_undo)
        self._redo.activated.connect(self._handle_redo)

        self.tree.selectionModel().selectionChanged.connect(self._on_selection)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------

    def build_tree(self):
        self._status.show_loading("Building...")
        self.tree.clear()

        try:
            systems = discover_all()   # {system_name: [solver_node, ...]}
            if not systems:
                self._status.show_message("No simulation nodes found.")
                return

            for _system_name, solver_nodes in systems.items():
                for solver_node in solver_nodes:
                    solver_item = build_solver_item(solver_node)
                    if solver_item:
                        self.tree.model().invisibleRootItem().appendRow(solver_item)

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

        self.tabs.addTab(self.cache_tab, "Cache")
        self.tabs.addTab(self.maps_tab,  "Maps")
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
        self._fr_label = QtWidgets.QLabel("-")
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
        node_type = getattr(new_item, "node_type", None)
        self._set_actions_enabled(node_type in ("nCloth", "hairSystem"))

    def _on_frame_range(self, _old, frame_range):
        if frame_range:
            self._fr_label.setText(f"{frame_range[0]} - {frame_range[1]}")

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

        node_type = getattr(self._current_item, "node_type", None)
        system    = get_system(node_type) if node_type else None
        if not system or not system.cache_ops:
            return

        for cache_info in system.cache_ops.list_caches(self._current_item):
            frames = (
                f"{cache_info.start} - {cache_info.end}"
                if (cache_info.start or cache_info.end) else "-"
            )
            row = QtWidgets.QTreeWidgetItem([
                f"v{cache_info.version:03d}",
                cache_info.date,
                frames,
            ])
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
        system = get_system(getattr(self._current_item, "node_type", None))
        if not system or not system.cache_ops:
            logger.warning("_create_cache: no cache_ops for this node type")
            return
        frame_range = self.hub_get(DynEvalKeys.FRAME_RANGE) or (1, 100)
        try:
            system.cache_ops.create(self._current_item, frame_range)
            self._rebuild_list()
        except Exception as e:
            logger.error(f"Cache creation failed: {e}")
            cmds.warning(str(e))

    def _attach_selected(self):
        cache_info = self._selected_cache_info()
        if not (cache_info and self._current_item):
            return
        system = get_system(getattr(self._current_item, "node_type", None))
        if not system or not system.cache_ops:
            return
        try:
            system.cache_ops.attach(self._current_item, cache_info)
        except Exception as e:
            logger.error(f"Cache attach failed: {e}")
            cmds.warning(str(e))

    def _delete_selected(self):
        cache_info = self._selected_cache_info()
        if not (cache_info and self._current_item):
            return
        system = get_system(getattr(self._current_item, "node_type", None))
        if not system or not system.cache_ops:
            return

        confirm = QtWidgets.QMessageBox.question(
            self,
            "Delete Cache",
            f"Delete version {cache_info.version}?\nThis cannot be undone.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if confirm != QtWidgets.QMessageBox.Yes:
            return

        try:
            system.cache_ops.delete(self._current_item, cache_info)
            self._rebuild_list()
        except Exception as e:
            logger.error(f"Cache delete failed: {e}")
            cmds.warning(str(e))


# ============================================================================
# MAP LIST PANEL
# ============================================================================

class MapListPanel(DynEvalWidgetBase):
    """
    Lists paintable maps for the selected node, with an editable map-type
    combobox per row (None / Per-Vertex / Texture, i.e. the *MapType attr).

    Double-clicking a map forces its type to Per-Vertex (painting needs it)
    and publishes PAINT_REQUESTED → DynEvalUI opens artisan via NClothMap.
    Labels are colored by type: green = Per-Vertex, blue = Texture.

    Subscribes to
    -------------
    SELECTED_NODE          repopulates the map list
    """

    MAP_TYPE_LABELS = ("None", "Per-Vertex", "Texture")
    PER_VERTEX = 1
    # Label color per map type: None -> default, Per-Vertex -> green,
    # Texture -> blue (matches the old RFX tool).
    MAP_TYPE_COLORS = (None, (130, 200, 120), (95, 160, 230))

    def __init__(self, hub, parent=None):
        super().__init__(hub, parent)
        self._current_item = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(4)

        self.map_tree = QtWidgets.QTreeWidget()
        self.map_tree.setHeaderLabels(["Map", "Type"])
        self.map_tree.setRootIsDecorated(False)
        self.map_tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        header = self.map_tree.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        header.setStretchLastSection(False)
        self.map_tree.setColumnWidth(1, 100)
        layout.addWidget(self.map_tree)

        # Hub subscriptions
        self.subscribe(DynEvalKeys.SELECTED_NODE, self._on_node_changed)

        # Widget connections
        self.map_tree.currentItemChanged.connect(self._on_map_selected)
        self.map_tree.itemDoubleClicked.connect(self._on_map_double_clicked)

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
        self.map_tree.clear()

        if not self._current_item:
            return
        if not hasattr(self._current_item, "get_maps"):
            return

        # get_maps() returns plain map names — wrap them in MapInfo so
        # downstream consumers (Slimfast bridge) know node + mesh too.
        node = getattr(self._current_item, "node", None)
        mesh = getattr(self._current_item, "mesh_transform", None)
        for map_name in self._current_item.get_maps():
            map_info = MapInfo(node=node, name=map_name, mesh=mesh)
            row = QtWidgets.QTreeWidgetItem([map_name, ""])
            row.setData(0, QtCore.Qt.UserRole, map_info)
            self.map_tree.addTopLevelItem(row)

            combo = QtWidgets.QComboBox()
            combo.addItems(list(self.MAP_TYPE_LABELS))
            map_type = sim_cmds.get_vtx_map_type(node, f"{map_name}MapType")
            if map_type is not None and 0 <= map_type < len(self.MAP_TYPE_LABELS):
                combo.setCurrentIndex(map_type)
                self._apply_type_color(row, map_type)
            combo.currentIndexChanged.connect(
                partial(self._on_map_type_changed, map_info, row)
            )
            self.map_tree.setItemWidget(row, 1, combo)

    def _apply_type_color(self, row, type_index: int):
        """Color the map label by its type (green vertex / blue texture)."""
        rgb = None
        if 0 <= type_index < len(self.MAP_TYPE_COLORS):
            rgb = self.MAP_TYPE_COLORS[type_index]
        if rgb is None:
            brush = QtGui.QBrush()  # default-constructed = view default color
        else:
            brush = QtGui.QBrush(QtGui.QColor(*rgb))
        row.setForeground(0, brush)

    def _selected_map_info(self):
        row = self.map_tree.currentItem()
        return row.data(0, QtCore.Qt.UserRole) if row else None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_map_selected(self, _current, _previous):
        map_info = self._selected_map_info()
        self.publish(DynEvalKeys.MAP_SELECTED, map_info)

    def _on_map_type_changed(self, map_info, row, index: int):
        sim_cmds.set_vtx_map_type(map_info.node, f"{map_info.name}MapType", index)
        self._apply_type_color(row, index)

    def _on_map_double_clicked(self, row, _column: int):
        """Force the map to Per-Vertex and hand off to painting."""
        map_info = row.data(0, QtCore.Qt.UserRole)
        if map_info is None:
            return

        combo = self.map_tree.itemWidget(row, 1)
        if combo is not None and combo.currentIndex() != self.PER_VERTEX:
            # setCurrentIndex fires _on_map_type_changed → sets the attr
            combo.setCurrentIndex(self.PER_VERTEX)

        self.publish(DynEvalKeys.PAINT_REQUESTED, map_info)


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
        self._label.setText(f"[!]  {message}")
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