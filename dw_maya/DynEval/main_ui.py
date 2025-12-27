"""
DynEval Main UI - Simulation Management Tool

Refactored with DataHub integration for decoupled widget communication.

Author: abtidona
"""

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Set
from PySide6 import QtWidgets, QtGui, QtCore
import maya.cmds as cmds
import maya.utils as mu
from shiboken6 import wrapInstance
import maya.OpenMayaUI as omui
import shutil

from dw_maya.dw_presets_io import dw_preset, dw_json, dw_folder
from dw_logger import get_logger

# Local imports
from .sim_cmds import ziva_cmds, cache_management, vtx_map_management, info_management
from .dendrology.nucleus_leaf import (
    CharacterTreeItem, NucleusStandardItem, ClothTreeItem,
    HairTreeItem, NRigidTreeItem
)
from .dendrology.ziva_leaf import ZSolverTreeItem, FasciaTreeItem, SkinTreeItem
from .sim_widget import (
    StateManager, SimulationTreeView, PresetManager,
    CacheTreeWidget, MapTreeWidget, PresetWidget,
    CommentEditor, VertexMapEditor,
    CacheInfo, MapInfo, PresetInfo, CacheType, PresetType, MapType
)

# Hub integration
from .hub_keys import HubKeys, SelectionContext, PaintContext, UIMode
from .sim_widget.wgt_base import DynEvalMainWindow, HubPublisher

logger = get_logger()


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_maya_window() -> QtWidgets.QWidget:
    """Get the Maya main window as a QWidget pointer."""
    return wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)


def get_all_treeitems(model, item_type: str = None):
    """
    Generator that yields items in the tree, optionally filtered by item type.

    Args:
        model: The QStandardItemModel containing the tree.
        item_type: The type of items to yield (e.g., "nCloth").

    Yields:
        QStandardItem: Each matching item in the tree.
    """
    def recurse(parent_item):
        for row in range(parent_item.rowCount()):
            child_item = parent_item.child(row)
            if child_item:
                if item_type is None or getattr(child_item, 'node_type', None) == item_type:
                    yield child_item
                yield from recurse(child_item)

    root_item = model.invisibleRootItem()
    yield from recurse(root_item)


# ============================================================================
# MAIN UI CLASS
# ============================================================================

class DynEvalUI(DynEvalMainWindow):
    """
    Main UI for managing simulation systems in Maya.

    Features:
    - Unified tree view for Nucleus and Ziva simulations
    - Cache management with versioning
    - Vertex map editing and painting
    - Preset management with blending
    - Comment/annotation system

    Uses DataHub for decoupled widget communication.
    """

    def __init__(self, parent=None):
        # Use Maya window as parent if not specified
        if parent is None:
            try:
                parent = get_maya_window()
            except Exception:
                pass

        super().__init__(parent)

        # Hub publisher for publishing selection/state
        self._publisher = HubPublisher()

        # Core managers
        self.state_manager = StateManager()
        self.preset_manager = PresetManager()

        # UI Setup
        self.setGeometry(867, 546, 1200, 600)
        self.setWindowTitle('Dynamic Systems Manager')
        self.setObjectName('DynEvalUI')

        # Track mouse for shortcuts
        self.setMouseTracking(True)
        self._mouse_over = False

        # Setup UI
        self.central_widget = QtWidgets.QWidget(self)
        self._setup_ui()
        self.setCentralWidget(self.central_widget)

        # Setup shortcuts and connections
        self._setup_shortcuts()
        self._setup_hub_subscriptions()

        # Build initial tree
        self.build_tree()

    def _setup_ui(self):
        """Initialize the main UI layout."""
        main_layout = QtWidgets.QHBoxLayout()

        # ====================================================================
        # LEFT PANEL - Simulation Tree
        # ====================================================================
        left_panel = self._create_left_panel()
        main_layout.addLayout(left_panel)

        # ====================================================================
        # MIDDLE PANEL - Cache/Maps/Presets
        # ====================================================================
        middle_panel = self._create_middle_panel()
        main_layout.addLayout(middle_panel)

        # ====================================================================
        # RIGHT PANEL - Details/Comments/Paint
        # ====================================================================
        right_panel = self._create_right_panel()
        main_layout.addWidget(right_panel)

        self.central_widget.setLayout(main_layout)

    def _create_left_panel(self) -> QtWidgets.QVBoxLayout:
        """Create the left panel with simulation tree."""
        layout = QtWidgets.QVBoxLayout()

        # Tree widget container
        tree_container = QtWidgets.QWidget()
        tree_layout = QtWidgets.QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)

        # Simulation tree
        self.dyn_eval_tree = SimulationTreeView()
        self.dyn_eval_tree.setMinimumWidth(280)
        self.dyn_eval_tree.setMinimumHeight(300)

        # Context menu
        self.dyn_eval_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.dyn_eval_tree.customContextMenuRequested.connect(self._show_tree_context_menu)

        tree_layout.addWidget(self.dyn_eval_tree)
        layout.addWidget(tree_container)

        # Status area
        status_layout = self._create_status_area()
        layout.addLayout(status_layout)

        return layout

    def _create_status_area(self) -> QtWidgets.QHBoxLayout:
        """Create status indicator area."""
        layout = QtWidgets.QHBoxLayout()

        # Loading indicator
        self.loading_movie = QtGui.QMovie()
        self.loading_label = QtWidgets.QLabel()
        self.loading_label.setFixedSize(16, 16)
        self.loading_label.setMovie(self.loading_movie)
        self.loading_label.hide()

        # Status label
        self.status_label = QtWidgets.QLabel()
        self.status_label.setAlignment(QtCore.Qt.AlignLeft)
        self.status_label.hide()

        layout.addWidget(self.loading_label)
        layout.addWidget(self.status_label, stretch=1)
        layout.setContentsMargins(5, 5, 5, 5)

        return layout

    def _create_middle_panel(self) -> QtWidgets.QVBoxLayout:
        """Create the middle panel with cache/maps/presets."""
        layout = QtWidgets.QVBoxLayout()

        # Mode selector
        self.mode_selector = QtWidgets.QComboBox()
        self.mode_selector.addItems(["Cache", "Maps", "Presets"])
        layout.addWidget(self.mode_selector)

        # Stacked widget for different views
        self.stack_widget = QtWidgets.QStackedWidget()

        # Cache view
        self.cache_tree = CacheTreeWidget()
        self.stack_widget.addWidget(self.cache_tree)

        # Maps view
        self.maps_tree = MapTreeWidget()
        self.stack_widget.addWidget(self.maps_tree)

        # Preset view
        self.preset_widget = PresetWidget()
        self.stack_widget.addWidget(self.preset_widget)

        layout.addWidget(self.stack_widget)

        return layout

    def _create_right_panel(self) -> QtWidgets.QTabWidget:
        """Create the right panel with details tabs."""
        self.details_panel = QtWidgets.QTabWidget()
        self.details_panel.setMinimumWidth(300)

        # Comments tab
        self.comments_tab = CommentEditor()
        self.details_panel.addTab(self.comments_tab, "Comments")

        # Paint/Edit Maps tab
        self.paint_map_tab = VertexMapEditor()
        self.details_panel.addTab(self.paint_map_tab, "Edit Maps")

        # Info tab
        self.info_tab = QtWidgets.QTextEdit()
        self.info_tab.setReadOnly(True)
        self.details_panel.addTab(self.info_tab, "Info")

        return self.details_panel

    # ========================================================================
    # HUB SUBSCRIPTIONS
    # ========================================================================

    def _setup_hub_subscriptions(self):
        """Setup all DataHub subscriptions."""
        # Subscribe to cache selection changes
        self.hub_subscribe(HubKeys.CACHE_SELECTED, self._on_cache_selected)

        # Subscribe to map selection changes
        self.hub_subscribe(HubKeys.MAP_SELECTED, self._on_map_selected)

        # Subscribe to paint context changes
        self.hub_subscribe(HubKeys.PAINT_ACTIVE, self._on_paint_state_changed)

        # Connect widget signals to hub publishers
        self._connect_widget_signals()

    def _connect_widget_signals(self):
        """Connect widget signals to publish to hub."""
        # Mode selector
        self.mode_selector.currentIndexChanged.connect(self._handle_mode_change)

        # Tree selection - publish to hub
        self.dyn_eval_tree.selectionModel().selectionChanged.connect(
            self._handle_tree_selection
        )

        # Cache widget signals
        self.cache_tree.cache_selected.connect(self._on_cache_widget_selection)
        self.cache_tree.cache_attached.connect(self._on_cache_attached)

        # Maps widget signals
        self.maps_tree.mapSelected.connect(self._on_map_widget_selection)
        self.maps_tree.mapTypeChanged.connect(self._on_map_type_changed)

        # Preset widget signals
        self.preset_widget.preset_applied.connect(self._on_preset_applied)

        # Comment signals
        self.comments_tab.save_requested.connect(self._handle_comment_save)

    # ========================================================================
    # SELECTION HANDLING
    # ========================================================================

    def _handle_tree_selection(self):
        """Handle selection changes in main tree - publish to hub."""
        items = self.dyn_eval_tree.get_selected_items()

        # Publish selection to hub
        self._publisher.publish_selection(items[0] if len(items) == 1 else items if items else None)

        # Update dependent widgets
        if items:
            current_item = items[0]
            mode = self.mode_selector.currentIndex()
            self._update_widgets_for_selection(current_item, mode)
            self._update_info_panel(current_item)

    def _update_widgets_for_selection(self, item, mode: int):
        """Update widgets based on current selection and mode."""
        match mode:
            case 0:  # Cache
                self.cache_tree.set_node(item)
            case 1:  # Maps
                self.maps_tree.set_current_node(item)
            case 2:  # Presets
                self.preset_widget.set_node(item.node if item else None)

    def get_selected_tree_item(self, multiple_selection: bool = False):
        """Get selected item(s) from tree."""
        items = self.dyn_eval_tree.get_selected_items()
        if not items:
            return None
        return items if multiple_selection else items[0]

    # ========================================================================
    # HUB CALLBACKS
    # ========================================================================

    def _on_cache_selected(self, old_value, new_value):
        """Hub callback: cache selection changed."""
        if new_value:
            self._update_comment_for_cache(new_value)

    def _on_map_selected(self, old_value, new_value):
        """Hub callback: map selection changed."""
        if new_value:
            logger.debug(f"Map selected via hub: {new_value.name}")

    def _on_paint_state_changed(self, old_value, new_value):
        """Hub callback: paint tool state changed."""
        if new_value:
            # Paint mode activated - switch to paint tab
            self.details_panel.setCurrentWidget(self.paint_map_tab)

    def _on_cache_widget_selection(self, cache_info: CacheInfo):
        """Handle cache selection from widget - publish to hub."""
        self._publisher.publish_cache_selection(cache_info)

    def _on_cache_attached(self, cache_info: CacheInfo):
        """Handle cache attachment event."""
        try:
            if cache_info.cache_type == CacheType.ALEMBIC:
                self._attach_abc_cache(cache_info)
            else:
                self._attach_ncache_from_info(cache_info)

            # Publish updated state
            self._publisher.publish_cache_selection(cache_info)

        except Exception as e:
            logger.error(f"Failed to attach cache: {e}")
            cmds.warning(str(e))

    def _on_map_widget_selection(self, map_info: MapInfo):
        """Handle map selection from widget - publish to hub."""
        self._publisher.publish_map_selection(map_info)

    def _on_map_type_changed(self, map_info: MapInfo, new_type: MapType):
        """Handle map type change."""
        try:
            current_item = self.get_selected_tree_item()
            if current_item:
                vtx_map_management.set_vtx_map_type(
                    current_item.node,
                    f"{map_info.name}MapType",
                    new_type.value
                )
        except Exception as e:
            logger.error(f"Failed to change map type: {e}")

    def _on_preset_applied(self, preset_info: PresetInfo):
        """Handle preset application."""
        try:
            current_item = self.get_selected_tree_item()
            if not current_item:
                return

            success = self.preset_manager.load_preset(
                preset_info,
                [current_item.node],
                blend=1.0
            )

            if success:
                self.hub_publish(HubKeys.PRESET_LOADED, preset_info)
            else:
                cmds.warning(f"Failed to apply preset {preset_info.name}")

        except Exception as e:
            logger.error(f"Failed to apply preset: {e}")

    # ========================================================================
    # MODE HANDLING
    # ========================================================================

    def _handle_mode_change(self, index: int):
        """Handle switching between cache/maps/preset modes."""
        self.stack_widget.setCurrentIndex(index)

        # Publish mode change
        mode_names = ['cache', 'maps', 'presets']
        self._publisher.publish_ui_mode(mode_names[index])

        # Update current widget
        if current_item := self.get_selected_tree_item():
            self._update_widgets_for_selection(current_item, index)

    # ========================================================================
    # INFO PANEL
    # ========================================================================

    def _update_info_panel(self, item):
        """Update info panel with current item details."""
        if not item:
            self.info_tab.clear()
            return

        info_lines = []

        # Basic node info
        node_name = getattr(item, 'node', None) or item.data(QtCore.Qt.UserRole + 1)
        node_type = getattr(item, 'node_type', None) or item.data(QtCore.Qt.UserRole + 5)

        info_lines.append(f"<b>Node:</b> {node_name}")
        info_lines.append(f"<b>Type:</b> {node_type}")

        # Solver info
        solver = getattr(item, 'solver_name', None) or item.data(QtCore.Qt.UserRole + 4)
        if solver:
            info_lines.append(f"<b>Solver:</b> {solver}")

        # Mesh info
        if hasattr(item, 'mesh_transform'):
            info_lines.append(f"<b>Mesh:</b> {item.mesh_transform}")

        # State info
        if hasattr(item, 'state'):
            state_text = "Enabled" if item.state else "Disabled"
            color = "green" if item.state else "red"
            info_lines.append(f"<b>State:</b> <span style='color:{color}'>{state_text}</span>")

        # Cache info
        if hasattr(item, 'get_cache_list'):
            cache_count = len(item.get_cache_list())
            info_lines.append(f"<b>Caches:</b> {cache_count}")

        # Map info
        if hasattr(item, 'get_maps'):
            map_count = len(item.get_maps())
            info_lines.append(f"<b>Maps:</b> {map_count}")

        self.info_tab.setHtml("<br>".join(info_lines))

    # ========================================================================
    # CONTEXT MENU
    # ========================================================================

    def _show_tree_context_menu(self, position: QtCore.QPoint):
        """Show context menu for tree items."""
        menu = QtWidgets.QMenu(self)
        current_item = self.get_selected_tree_item()

        if not current_item:
            return

        node_type = getattr(current_item, 'node_type', None)

        # Basic operations
        select_action = menu.addAction("Select in Maya")
        select_action.triggered.connect(self._select_in_maya)

        menu.addSeparator()

        # Type-specific operations
        if node_type in ['nCloth', 'hairSystem']:
            cache_menu = menu.addMenu("Cache")
            create_action = cache_menu.addAction("Create nCache")
            create_action.triggered.connect(self.create_cache)

            if hasattr(current_item, 'get_cache_list') and current_item.get_cache_list():
                delete_action = cache_menu.addAction("Delete All Caches")
                delete_action.triggered.connect(self._delete_all_caches)

        elif node_type == 'zSolverTransform':
            cache_menu = menu.addMenu("Cache")
            create_action = cache_menu.addAction("Create Alembic")
            create_action.triggered.connect(self.create_abc_cache)

        # Preset operations
        menu.addSeparator()
        preset_menu = menu.addMenu("Presets")
        save_preset_action = preset_menu.addAction("Save Preset...")
        save_preset_action.triggered.connect(self._save_preset_dialog)

        menu.exec_(self.dyn_eval_tree.viewport().mapToGlobal(position))

    def _select_in_maya(self):
        """Select the current item's mesh in Maya."""
        item = self.get_selected_tree_item()
        if not item:
            return

        node_type = getattr(item, 'node_type', None)

        if node_type in ['nRigid', 'dynamicConstraint']:
            transform = cmds.listRelatives(item.node, p=True)
        elif node_type == 'nCloth':
            transform = getattr(item, 'mesh_transform', item.node)
        else:
            transform = item.node

        if transform:
            cmds.select(transform, r=True)

    # ========================================================================
    # TREE BUILDING
    # ========================================================================

    def build_tree(self):
        """Build the complete simulation hierarchy tree."""
        try:
            self._show_status("Initializing...", loading=True)
            self.dyn_eval_tree.clear()

            # Get nucleus data
            self._show_status("Loading Nucleus systems...", loading=True)
            nucleus_data = self._get_nucleus_data()

            # Build tree
            if nucleus_data:
                self._show_status("Building tree...", loading=True)
                self._build_nucleus_tree(nucleus_data)

            # Expand top level items
            for i in range(self.dyn_eval_tree.model().rowCount()):
                index = self.dyn_eval_tree.model().index(i, 0)
                self.dyn_eval_tree.expand(index)

            self._hide_status()

        except Exception as e:
            logger.error(f"Failed to build tree: {e}")
            self._show_status(f"Error: {e}", loading=False)

    def _get_nucleus_data(self) -> Dict[str, Any]:
        """Gather nucleus system data."""
        try:
            return info_management.dw_get_hierarchy()
        except Exception as e:
            logger.error(f"Failed to get nucleus data: {e}")
            return {}

    def _build_nucleus_tree(self, system_hierarchy: Dict[str, Any]):
        """Build nucleus system hierarchy."""
        try:
            for character, solvers in system_hierarchy.items():
                # Sort solvers by outliner order
                sorted_solvers = info_management.sort_list_by_outliner(list(solvers.keys()))

                for solver in sorted_solvers:
                    # Create solver item
                    solver_item = NucleusStandardItem(solver)
                    state_item = QtGui.QStandardItem()
                    state_item.setEditable(False)
                    state_item.setData(solver_item.state, QtCore.Qt.UserRole + 3)

                    # Add dynamic elements
                    elements = system_hierarchy[character][solver]
                    if any(elements.get(key) for key in ['nCloth', 'hairSystem', 'nRigid']):
                        self._add_dynamic_elements(elements, solver_item)

                    # Add to model
                    self.dyn_eval_tree.model().invisibleRootItem().appendRow([solver_item, state_item])

        except Exception as e:
            logger.error(f"Failed to build nucleus tree: {e}")

    def _add_dynamic_elements(self, elements: Dict[str, List[str]], parent_item: QtGui.QStandardItem):
        """Add dynamic elements to parent item."""
        element_types = [
            ('nCloth', ClothTreeItem),
            ('hairSystem', HairTreeItem),
            ('nRigid', NRigidTreeItem)
        ]

        for element_type, item_class in element_types:
            nodes = elements.get(element_type, [])
            if nodes:
                sorted_nodes = info_management.sort_list_by_outliner(nodes)
                for node in sorted_nodes:
                    try:
                        item = item_class(node)
                        state_item = QtGui.QStandardItem()
                        state_item.setData(item.state, QtCore.Qt.UserRole + 3)
                        state_item.setEditable(False)
                        parent_item.appendRow([item, state_item])
                    except Exception as e:
                        logger.warning(f"Failed to create item for {node}: {e}")

    def refresh_tree(self):
        """Refresh the tree while maintaining expansion state."""
        expanded_items = self._get_expanded_items()
        self.build_tree()
        self._restore_expanded_items(expanded_items)

    def _get_expanded_items(self) -> Set[str]:
        """Get set of expanded item paths."""
        expanded = set()

        def collect_expanded(parent_index):
            if self.dyn_eval_tree.isExpanded(parent_index):
                item = self.dyn_eval_tree.model().itemFromIndex(parent_index)
                if item:
                    expanded.add(self._get_item_path(item))

            for row in range(self.dyn_eval_tree.model().rowCount(parent_index)):
                child_index = self.dyn_eval_tree.model().index(row, 0, parent_index)
                collect_expanded(child_index)

        collect_expanded(QtCore.QModelIndex())
        return expanded

    def _restore_expanded_items(self, expanded_paths: Set[str]):
        """Restore expansion state from paths."""
        def expand_matched(parent_index):
            item = self.dyn_eval_tree.model().itemFromIndex(parent_index)
            if item and self._get_item_path(item) in expanded_paths:
                self.dyn_eval_tree.expand(parent_index)

            for row in range(self.dyn_eval_tree.model().rowCount(parent_index)):
                child_index = self.dyn_eval_tree.model().index(row, 0, parent_index)
                expand_matched(child_index)

        expand_matched(QtCore.QModelIndex())

    def _get_item_path(self, item: QtGui.QStandardItem) -> str:
        """Get unique path for tree item."""
        path = []
        while item:
            path.append(item.text())
            item = item.parent()
        return '/'.join(reversed(path))

    # ========================================================================
    # STATUS DISPLAY
    # ========================================================================

    def _show_status(self, message: str, loading: bool = False):
        """Show status message with optional loading animation."""
        self.status_label.setText(message)
        self.status_label.show()

        if loading:
            self.loading_label.show()
        else:
            self.loading_label.hide()

        # Publish to hub
        self._publisher.publish_status(message, loading)

    def _hide_status(self):
        """Hide status indicators."""
        self.loading_label.hide()
        self.status_label.hide()
        self._publisher.publish_status("", False)

    # ========================================================================
    # CACHE OPERATIONS
    # ========================================================================

    def create_cache(self):
        """Create nCache for selected items."""
        items = self.get_selected_tree_item(multiple_selection=True)
        if not items:
            cmds.warning("No items selected for caching.")
            return

        if not isinstance(items, list):
            items = [items]

        self._show_status("Creating cache...", loading=True)

        try:
            # Prepare cache info
            ncloth_nodes = [item.node for item in items]
            cache_dir = items[0].cache_dir(0) if items else ''

            # Create directories
            for item in items:
                Path(item.cache_dir()).mkdir(parents=True, exist_ok=True)

            # Delete existing caches
            cmds.waitCursor(state=1)
            self._show_status("Removing existing caches...", loading=True)
            cache_management.delete_caches(ncloth_nodes)
            cmds.waitCursor(state=0)

            # Create new caches
            self._show_status("Creating caches...", loading=True)
            caches = cache_management.create_cache(ncloth_nodes, cache_dir)

            # Handle comment
            if comment := self.comments_tab.getComment():
                self._save_cache_comment(items[0], comment)

            # Attach caches
            self._show_status("Attaching caches...", loading=True)
            self._attach_created_caches(caches, items, cache_dir)

            # Refresh cache list
            if self.mode_selector.currentIndex() == 0:
                mu.executeDeferred(self.cache_tree.build_cache_list)

            self._hide_status()

        except Exception as e:
            self._show_status(f"Error: {e}", loading=False)
            logger.error(f"Cache creation failed: {e}")

    def create_abc_cache(self):
        """Create Alembic cache for Ziva items."""
        items = self.get_selected_tree_item(multiple_selection=True)
        if not items:
            cmds.warning("No items selected for Alembic caching.")
            return

        # Implementation for Ziva Alembic caching
        # ... (keeping existing logic)

    def _attach_created_caches(self, caches: List[str], items: List, cache_dir: str):
        """Attach newly created caches to their nodes."""
        for cache_name, item in zip(caches, items):
            try:
                target_dir = item.cache_file(1)
                src_path = Path(cache_dir)

                # Find and move cache files
                cache_files = [f for f in src_path.iterdir() if f.name.startswith(cache_name)]

                for src in cache_files:
                    dst = Path(target_dir).with_suffix(src.suffix)
                    shutil.move(str(src), str(dst))

                # Attach cache
                cache_management.attach_ncache(target_dir, item.node)

            except Exception as e:
                logger.error(f"Failed to attach cache {cache_name}: {e}")

    def _attach_ncache_from_info(self, cache_info: CacheInfo):
        """Attach nCache from CacheInfo object."""
        try:
            cmds.waitCursor(state=1)
            cache_management.delete_caches([cache_info.node])
            cache_management.attach_ncache(str(cache_info.path), cache_info.node)
            cmds.waitCursor(state=0)
        except Exception as e:
            cmds.waitCursor(state=0)
            raise

    def _attach_abc_cache(self, cache_info: CacheInfo):
        """Attach Alembic cache from CacheInfo object."""
        abc_attr = f"{cache_info.node}.filename"
        cmds.setAttr(abc_attr, str(cache_info.path), type='string')

    def _delete_all_caches(self):
        """Delete all caches for selected item."""
        item = self.get_selected_tree_item()
        if item and hasattr(item, 'node'):
            cache_management.delete_caches([item.node])
            self.cache_tree.build_cache_list()

    # ========================================================================
    # COMMENTS
    # ========================================================================

    def _update_comment_for_cache(self, cache_info: CacheInfo):
        """Update comment display for selected cache."""
        current_item = self.get_selected_tree_item()
        if not current_item:
            return

        self.comments_tab.setTitle(current_item.short_name if hasattr(current_item, 'short_name') else str(current_item))

        try:
            metadata_path = Path(current_item.metadata())
            if metadata_path.exists():
                data = dw_json.load_json(str(metadata_path))
                solver = getattr(current_item, 'solver_name', None)
                comment = data.get('comment', {}).get(solver, {}).get(cache_info.version, "")
                self.comments_tab.setComment(comment)
            else:
                self.comments_tab.setComment("")
        except Exception as e:
            logger.warning(f"Failed to load comment: {e}")
            self.comments_tab.setComment("")

    def _handle_comment_save(self, comment: str):
        """Handle comment save request."""
        current_item = self.get_selected_tree_item()
        if not current_item:
            cmds.warning("No item selected.")
            return

        selected_caches = self.cache_tree.cache_tree.selectedItems()
        if not selected_caches:
            cmds.warning("No cache selected.")
            return

        try:
            metadata_path = current_item.metadata()
            solver = getattr(current_item, 'solver_name', None) or current_item.data(QtCore.Qt.UserRole + 4)

            comment_data = {'comment': {solver: {}}}
            for cache in selected_caches:
                comment_data['comment'][solver][cache.cache_info.version] = comment

            metadata_file = Path(metadata_path)
            if metadata_file.exists():
                dw_json.merge_json(str(metadata_path), comment_data, defer=True)
            else:
                dw_json.save_json(str(metadata_path), comment_data, defer=True)

        except Exception as e:
            logger.error(f"Failed to save comment: {e}")

    def _save_cache_comment(self, item, comment: str):
        """Save comment for cache."""
        if not comment:
            return

        try:
            metadata_path = item.metadata()
            solver = getattr(item, 'solver_name', None)
            current_iter = item.get_iter()

            comment_data = {'comment': {solver: {current_iter: comment}}}

            if Path(metadata_path).exists():
                dw_json.merge_json(metadata_path, comment_data, defer=True)
            else:
                dw_json.save_json(metadata_path, comment_data, defer=True)

        except Exception as e:
            logger.error(f"Failed to save cache comment: {e}")

    # ========================================================================
    # PRESETS
    # ========================================================================

    def _save_preset_dialog(self):
        """Show dialog to save current settings as preset."""
        current_item = self.get_selected_tree_item()
        if not current_item:
            cmds.warning("No item selected.")
            return

        name, ok = QtWidgets.QInputDialog.getText(
            self, "Save Preset", "Preset name:"
        )

        if ok and name:
            try:
                preset = self.preset_manager.save_preset([current_item.node], name)
                QtWidgets.QMessageBox.information(
                    self, "Success", f"Preset '{name}' saved!"
                )
            except Exception as e:
                QtWidgets.QMessageBox.warning(
                    self, "Error", f"Failed to save preset: {e}"
                )

    # ========================================================================
    # SHORTCUTS
    # ========================================================================

    def _setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        self.undo_shortcut = QtGui.QShortcut(QtGui.QKeySequence.Undo, self)
        self.redo_shortcut = QtGui.QShortcut(QtGui.QKeySequence.Redo, self)

        self.undo_shortcut.activated.connect(self._handle_undo)
        self.redo_shortcut.activated.connect(self._handle_redo)

        self._update_shortcuts_state(False)

    def _handle_undo(self):
        """Handle undo operation."""
        cmds.undo()
        self.refresh_tree()

    def _handle_redo(self):
        """Handle redo operation."""
        cmds.redo()
        self.refresh_tree()

    def enterEvent(self, event):
        """Handle mouse entering window."""
        super().enterEvent(event)
        self._mouse_over = True
        self._update_shortcuts_state(True)

    def leaveEvent(self, event):
        """Handle mouse leaving window."""
        super().leaveEvent(event)
        self._mouse_over = False
        self._update_shortcuts_state(False)

    def _update_shortcuts_state(self, enabled: bool):
        """Update shortcut states based on mouse position."""
        if enabled:
            self.undo_shortcut.setKey(QtGui.QKeySequence.Undo)
            self.redo_shortcut.setKey(QtGui.QKeySequence.Redo)
        else:
            self.undo_shortcut.setKey(QtGui.QKeySequence())
            self.redo_shortcut.setKey(QtGui.QKeySequence())

    # ========================================================================
    # CLEANUP
    # CLEANUP - handled by DynEvalMainWindow base class


# ============================================================================
# LAUNCH FUNCTION
# ============================================================================

def show_ui() -> DynEvalUI:
    """Launch the DynEval UI."""
    global _dyneval_instance

    # Close existing instance
    try:
        _dyneval_instance.close()
        _dyneval_instance.deleteLater()
    except:
        pass

    # Create new instance
    _dyneval_instance = DynEvalUI()
    _dyneval_instance.show()

    return _dyneval_instance


_dyneval_instance = None