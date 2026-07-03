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

import subprocess
import sys
from functools import partial
from pathlib import Path
from typing import Optional

from dw_maya.DynEval.sim_cmds.compat import (
    QtCore, QtGui, QtWidgets, Qt, Signal, Slot,
    wrapInstance, QShortcut, QAction, QActionGroup, qt_exec,
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
from dw_maya.DynEval.sim_registry import (
    discover_all, build_solver_item, get_system, all_sim_node_types,
)
from dw_maya.DynEval.sim_widget import SimulationTreeView
from dw_maya.DynEval.sim_widget.wgt_base import DynEvalMainWindow, DynEvalWidgetBase
from dw_maya.DynEval.sim_widget.wgt_commentary import CommentEditor
from dw_maya.DynEval.sim_cmds import cache_metadata, dyn_prefs
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

        self._build_menu()
        self._build_layout()
        self._setup_hub()
        self._sync_frame_range()
        self.build_tree()

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------

    def _build_menu(self):
        pref_menu = self.menuBar().addMenu("Pref")
        dist_menu = pref_menu.addMenu("Cache Distribution")

        # Exclusive checkable pair; the choice persists via optionVar and is
        # read by NucleusCacheOps.create at cache time (dyn_prefs).
        current = dyn_prefs.get_cache_distribution()
        self._dist_group = QActionGroup(self)
        self._dist_group.setExclusive(True)

        entries = (
            ("OneFile", "Single File",
             "One cache file for the whole frame range (default)."),
            ("OneFilePerFrame", "One File Per Frame",
             "One file per frame - lets you inspect a batch sim while it is "
             "still running."),
        )
        for value, label, tip in entries:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(value == current)
            action.setStatusTip(tip)
            action.setToolTip(tip)
            action.triggered.connect(partial(self._set_cache_distribution, value))
            self._dist_group.addAction(action)
            dist_menu.addAction(action)

    def _set_cache_distribution(self, value, *_args):
        try:
            dyn_prefs.set_cache_distribution(value)
            logger.info(f"Cache distribution set to {value!r}")
        except Exception as e:
            logger.error(f"Could not set cache distribution: {e}")

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

        # Leaf-type filter — one checkbox per registered sim node type
        # (nCloth / hairSystem / nRigid today), persisted via dyn_prefs.
        self._type_checks = {}
        filter_row = QtWidgets.QHBoxLayout()
        filter_row.setContentsMargins(2, 2, 2, 0)
        hidden = dyn_prefs.get_hidden_node_types()
        for sim_type in all_sim_node_types():
            check = QtWidgets.QCheckBox(sim_type)
            check.setChecked(sim_type not in hidden)
            check.toggled.connect(self._on_type_filter_changed)
            self._type_checks[sim_type] = check
            filter_row.addWidget(check)
        filter_row.addStretch()

        self._btn_refresh = QtWidgets.QPushButton("Refresh")
        self._btn_refresh.setToolTip(
            "Rebuild the tree from the scene (keeps expansion state)."
        )
        self._btn_refresh.clicked.connect(self.refresh_tree)
        filter_row.addWidget(self._btn_refresh)

        layout.addLayout(filter_row)

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

            visible = self._visible_types()
            for _system_name, solver_nodes in systems.items():
                for solver_node in solver_nodes:
                    solver_item = build_solver_item(solver_node, visible_types=visible)
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
    # Leaf-type filter
    # ------------------------------------------------------------------

    def _visible_types(self) -> set:
        return {t for t, check in self._type_checks.items() if check.isChecked()}

    def _on_type_filter_changed(self, _checked: bool):
        hidden = {t for t, check in self._type_checks.items() if not check.isChecked()}
        dyn_prefs.set_hidden_node_types(hidden)
        self.refresh_tree()

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
            menu.addAction("Attach Published Caches", self._attach_published_caches)
            menu.addSeparator()
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

    def _attach_published_caches(self):
        """Reattach every published-tagged cache under the selected solver.

        The scene-rebuild workflow: someone reopens/rebuilds the scene,
        right-clicks the solver, and every sim item whose metadata carries a
        published version gets that cache attached in one go.
        """
        solver_item = self.selected_item()
        if not solver_item:
            return

        attached, skipped = [], []
        for row in range(solver_item.rowCount()):
            child = solver_item.child(row, 0)
            node_type = getattr(child, "node_type", None)
            if node_type not in ("nCloth", "hairSystem"):
                continue

            version = cache_metadata.get_published(child)
            if version is None:
                continue

            system = get_system(node_type)
            if not system or not system.cache_ops:
                continue

            match = None
            for cache_info in system.cache_ops.list_caches(child):
                if cache_info.version == version:
                    match = cache_info
                    break

            label = f"{child.short_name} v{version:03d}"
            if match is None:
                skipped.append(label)
                logger.warning(
                    f"Attach published: no cache v{version:03d} on disk "
                    f"for {child.node!r}"
                )
                continue

            try:
                system.cache_ops.attach(child, match)
                attached.append(label)
            except Exception as e:
                skipped.append(label)
                logger.error(f"Attach published failed for {child.node!r}: {e}")

        if attached:
            logger.info(f"Attached published caches: {', '.join(attached)}")
        if skipped:
            cmds.warning(f"Published caches not attached: {', '.join(skipped)}")
        if not attached and not skipped:
            cmds.warning("No published cache tagged under this solver.")

        # Refresh the cache panel highlight for the current selection
        self.publish(DynEvalKeys.SELECTED_NODE, self.selected_item())

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
    Right panel — a tab container.

    Each sub-panel subscribes to the hub independently; the only logic
    here is tab focus: COMMENT_EDIT_REQUESTED (double-click on a comment
    cell in the cache panel) raises the Comment tab.
    """

    def __init__(self, hub, parent=None):
        super().__init__(hub, parent)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QtWidgets.QTabWidget()
        self.cache_tab   = CacheVersionPanel(hub)
        self.maps_tab    = MapListPanel(hub)
        self.comment_tab = CommentEditor(hub)

        self.tabs.addTab(self.cache_tab,   "Cache")
        self.tabs.addTab(self.maps_tab,    "Maps")
        self.tabs.addTab(self.comment_tab, "Comment")
        layout.addWidget(self.tabs)

        self.subscribe(DynEvalKeys.COMMENT_EDIT_REQUESTED, self._on_comment_edit)

    def _on_comment_edit(self, _old, cache_info):
        if cache_info is not None:
            self.tabs.setCurrentWidget(self.comment_tab)


# ============================================================================
# CACHE VERSION PANEL
# ============================================================================

class CacheVersionPanel(DynEvalWidgetBase):
    """
    Lists available cache versions for the selected node.
    Provides create / attach / delete actions.

    Row decoration
    --------------
    - The currently attached cache is bold on a blue background.
    - Favorite versions carry a star suffix (composite / blendshape sources).
    - The published version (the one tagged for publish) is green.
    Tags live in metadata.json via sim_cmds.cache_metadata.

    Interactions
    ------------
    - Double-click on the Comment cell -> raise the Comment tab
      (COMMENT_EDIT_REQUESTED); any other cell -> attach that version.
    - Context menu: attach / favorite / publish tag / comment / reveal /
      delete.

    Subscribes to
    -------------
    SELECTED_NODE          repopulates the version list
    FRAME_RANGE            updates the frame-range display
    CACHE_CREATE_REQUESTED triggers cache creation directly
    COMMENT_SAVED          refreshes the Comment column
    """

    COL_VERSION = 0
    COL_TYPE = 1
    COL_DATE = 2
    COL_FRAMES = 3
    COL_COMMENT = 4

    ATTACHED_BG = QtGui.QColor(38, 79, 120)
    FAVORITE_FG = QtGui.QColor(212, 175, 55)
    PUBLISHED_FG = QtGui.QColor(130, 200, 120)
    FAVORITE_MARK = "★"   # black star (escape keeps the source ASCII)

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
        self.cache_list.setHeaderLabels(["Version", "Type", "Date", "Frames", "Comment"])
        self.cache_list.setRootIsDecorated(False)
        self.cache_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.cache_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        header = self.cache_list.header()
        header.setStretchLastSection(True)
        self.cache_list.setColumnWidth(self.COL_VERSION, 70)
        self.cache_list.setColumnWidth(self.COL_TYPE, 70)
        self.cache_list.setColumnWidth(self.COL_DATE, 110)
        self.cache_list.setColumnWidth(self.COL_FRAMES, 80)
        layout.addWidget(self.cache_list)

        # -- Create mode (increment / replace) -------------------------------
        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel("On create:"))
        self._mode_increment = QtWidgets.QRadioButton("Increment")
        self._mode_increment.setToolTip("Each create writes a new version.")
        self._mode_replace = QtWidgets.QRadioButton("Replace")
        self._mode_replace.setToolTip(
            "Create overwrites the attached version (or the latest when "
            "none is attached)."
        )
        self._mode_group = QtWidgets.QButtonGroup(self)
        self._mode_group.addButton(self._mode_increment)
        self._mode_group.addButton(self._mode_replace)
        if dyn_prefs.get_cache_mode() == "replace":
            self._mode_replace.setChecked(True)
        else:
            self._mode_increment.setChecked(True)
        mode_row.addWidget(self._mode_increment)
        mode_row.addWidget(self._mode_replace)
        mode_row.addStretch()
        layout.addLayout(mode_row)

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
        self.subscribe(DynEvalKeys.COMMENT_SAVED,          self._on_comment_saved)

        # -- Widget connections --------------------------------------------
        self.cache_list.currentItemChanged.connect(self._on_version_selected)
        self.cache_list.itemDoubleClicked.connect(self._on_double_click)
        self.cache_list.customContextMenuRequested.connect(self._show_context_menu)
        self._mode_replace.toggled.connect(self._on_cache_mode_changed)
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

    def _on_comment_saved(self, _old, _comment):
        """A comment was written from the Comment tab — refresh the column."""
        self._rebuild_list(select_version=self._selected_version())

    # ------------------------------------------------------------------
    # Version list
    # ------------------------------------------------------------------

    def _rebuild_list(self, select_version: Optional[int] = None):
        self.cache_list.clear()
        if not self._current_item:
            return

        node_type = getattr(self._current_item, "node_type", None)
        system    = get_system(node_type) if node_type else None
        if not system or not system.cache_ops:
            return

        tags = cache_metadata.get_tags(self._current_item)
        bold = QtGui.QFont()
        bold.setBold(True)

        for cache_info in system.cache_ops.list_caches(self._current_item):
            cache_info.is_attached = self._is_attached(cache_info)

            frames = (
                f"{cache_info.start} - {cache_info.end}"
                if (cache_info.start or cache_info.end) else "-"
            )
            version_text = f"v{cache_info.version:03d}"
            if cache_info.version in tags["favorites"]:
                version_text = f"{version_text} {self.FAVORITE_MARK}"

            comment = tags["comments"].get(str(cache_info.version), "")
            comment_line = comment.splitlines()[0] if comment else ""

            row = QtWidgets.QTreeWidgetItem([
                version_text,
                cache_info.cache_type.value,
                cache_info.date,
                frames,
                comment_line,
            ])
            row.setData(0, QtCore.Qt.UserRole, cache_info)
            if comment:
                row.setToolTip(self.COL_COMMENT, comment)

            if cache_info.version == tags["published"]:
                row.setForeground(self.COL_VERSION, QtGui.QBrush(self.PUBLISHED_FG))
                row.setToolTip(self.COL_VERSION, "Published cache")
            elif cache_info.version in tags["favorites"]:
                row.setForeground(self.COL_VERSION, QtGui.QBrush(self.FAVORITE_FG))
                row.setToolTip(self.COL_VERSION, "Favorite cache")

            if cache_info.is_attached:
                for col in range(self.cache_list.columnCount()):
                    row.setBackground(col, QtGui.QBrush(self.ATTACHED_BG))
                    row.setFont(col, bold)

            self.cache_list.addTopLevelItem(row)

            if select_version is not None and cache_info.version == select_version:
                self.cache_list.setCurrentItem(row)

    def _is_attached(self, cache_info) -> bool:
        """True when this version is the cache currently driving the node."""
        try:
            from .sim_cmds import cache_management
            return cache_management.cache_is_attached(cache_info.node, cache_info.name)
        except Exception as e:
            logger.debug(f"attach check failed for {cache_info.name!r}: {e}")
            return False

    def _selected_version(self) -> Optional[int]:
        cache_info = self._selected_cache_info()
        return cache_info.version if cache_info else None

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
        replace = self._mode_replace.isChecked()
        try:
            system.cache_ops.create(self._current_item, frame_range, replace=replace)
            self._rebuild_list()
        except Exception as e:
            logger.error(f"Cache creation failed: {e}")
            cmds.warning(str(e))

    def _on_cache_mode_changed(self, replace_checked: bool):
        try:
            dyn_prefs.set_cache_mode("replace" if replace_checked else "increment")
        except Exception as e:
            logger.error(f"Could not set cache mode: {e}")

    def _attach_selected(self):
        cache_info = self._selected_cache_info()
        if cache_info:
            self._attach_cache(cache_info)

    def _attach_cache(self, cache_info):
        if not (cache_info and self._current_item):
            return
        system = get_system(getattr(self._current_item, "node_type", None))
        if not system or not system.cache_ops:
            return
        try:
            system.cache_ops.attach(self._current_item, cache_info)
            self._rebuild_list(select_version=cache_info.version)
        except Exception as e:
            logger.error(f"Cache attach failed: {e}")
            cmds.warning(str(e))

    def _on_double_click(self, row, column: int):
        """Comment cell -> open the Comment tab; any other cell -> attach."""
        cache_info = row.data(0, QtCore.Qt.UserRole)
        if cache_info is None:
            return
        if column == self.COL_COMMENT:
            self.publish(DynEvalKeys.CACHE_SELECTED, cache_info)
            self.publish(DynEvalKeys.COMMENT_EDIT_REQUESTED, cache_info)
        else:
            self._attach_cache(cache_info)

    def _toggle_favorite(self, cache_info):
        cache_metadata.toggle_favorite(self._current_item, cache_info.version)
        self._rebuild_list(select_version=cache_info.version)

    def _set_published(self, cache_info, state: bool):
        version = cache_info.version if state else None
        cache_metadata.set_published(self._current_item, version)
        self._rebuild_list(select_version=cache_info.version)

    def _materialize_cache(self, cache_info):
        """Fresh-duplicate the sim mesh at the outliner root and assign
        the right-clicked cache version to the duplicate."""
        if not self._current_item:
            return

        mesh = getattr(self._current_item, "mesh_transform", None)
        if not mesh or not cmds.objExists(mesh):
            try:
                from dw_maya.dw_nucleus_utils.dw_core import get_mesh_from_nucx_node
                mesh = get_mesh_from_nucx_node(self._current_item.node)
            except Exception:
                mesh = None
        if not mesh or not cmds.objExists(mesh):
            cmds.warning(
                f"No mesh resolved for '{self._current_item.node}' - cannot materialize."
            )
            return

        try:
            from .sim_cmds import cache_management
            result = cache_management.materialize(mesh, str(cache_info.path))
            cmds.select(result, replace=True)
            logger.info(f"Materialized {cache_info.name!r} as {result!r}")
        except Exception as e:
            logger.error(f"Materialize failed: {e}")
            cmds.warning(str(e))

    def _edit_comment(self, cache_info):
        self.publish(DynEvalKeys.CACHE_SELECTED, cache_info)
        self.publish(DynEvalKeys.COMMENT_EDIT_REQUESTED, cache_info)

    def _reveal_in_explorer(self, cache_info):
        cache_dir = Path(cache_info.path).parent
        if not cache_dir.exists():
            cmds.warning(f"Cache directory does not exist: {cache_dir}")
            return
        if sys.platform == "win32":
            subprocess.Popen(f'explorer "{cache_dir}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(cache_dir)])
        else:
            subprocess.Popen(["xdg-open", str(cache_dir)])

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos: QtCore.QPoint):
        row = self.cache_list.itemAt(pos)
        if row is None or not self._current_item:
            return
        cache_info = row.data(0, QtCore.Qt.UserRole)
        if cache_info is None:
            return

        tags = cache_metadata.get_tags(self._current_item)
        is_fav = cache_info.version in tags["favorites"]
        is_pub = cache_info.version == tags["published"]

        menu = QtWidgets.QMenu(self)
        menu.addAction("Attach", partial(self._attach_cache, cache_info))
        menu.addSeparator()
        menu.addAction(
            "Remove Favorite" if is_fav else "Set Favorite",
            partial(self._toggle_favorite, cache_info),
        )
        menu.addAction(
            "Clear Published" if is_pub else "Set as Published",
            partial(self._set_published, cache_info, not is_pub),
        )
        menu.addSeparator()
        menu.addAction("Materialize", partial(self._materialize_cache, cache_info))
        menu.addSeparator()
        menu.addAction("Edit Comment...", partial(self._edit_comment, cache_info))
        menu.addAction("Reveal in Explorer", partial(self._reveal_in_explorer, cache_info))
        menu.addSeparator()
        menu.addAction("Delete", self._delete_selected)

        menu.exec_(self.cache_list.viewport().mapToGlobal(pos))

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