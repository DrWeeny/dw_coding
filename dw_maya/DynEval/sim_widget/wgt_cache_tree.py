"""
Cache Tree Widget with DataHub Integration

Displays and manages simulation caches (nCache, Alembic).
Publishes cache selection and subscribes to node selection.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum
from PySide6 import QtWidgets, QtGui, QtCore
from pathlib import Path
import maya.cmds as cmds
import re

from dw_logger import get_logger

# Local imports
from ..hub_keys import HubKeys
from .wgt_base import DynEvalWidget
from ..dendrology.cache_leaf import CacheItem

logger = get_logger()


class CacheType(Enum):
    NCACHE = "nCache"
    GEOCACHE = "geoCache"
    ALEMBIC = "alembic"


@dataclass
class CacheInfo:
    """Data container for cache information."""
    name: str
    path: Path
    node: str
    version: int
    cache_type: CacheType
    is_valid: bool = True
    is_attached: bool = False
    mesh: Optional[str] = None


class CacheColors:
    """Color definitions for different cache types."""
    MAYA_BLUE = QtGui.QColor(68, 78, 88)
    GEO_RED = QtGui.QColor(128, 18, 18)
    NCLOTH_GREEN = QtGui.QColor(29, 128, 18)
    ABC_PURPLE = QtGui.QColor(104, 66, 129)

    @classmethod
    def get_color(cls, cache_type: CacheType) -> QtGui.QColor:
        return {
            CacheType.NCACHE: cls.NCLOTH_GREEN,
            CacheType.GEOCACHE: cls.GEO_RED,
            CacheType.ALEMBIC: cls.ABC_PURPLE
        }.get(cache_type, cls.MAYA_BLUE)


class CacheTreeWidget(DynEvalWidget):
    """
    Widget for managing simulation caches.

    Subscribes to:
        - HubKeys.SELECTED_ITEM: Updates cache list when selection changes

    Publishes:
        - HubKeys.CACHE_SELECTED: When a cache is selected
        - HubKeys.CACHE_ATTACHED: When cache attachment state changes
    """

    # Qt Signals (for backwards compatibility with direct connections)
    cache_selected = QtCore.Signal(object)  # CacheInfo
    cache_attached = QtCore.Signal(object)  # CacheInfo
    cache_detached = QtCore.Signal(object)  # CacheInfo

    def __init__(self, parent=None):
        super().__init__(parent)

        # Current node being displayed
        self._current_node = None

        # Setup UI
        self._setup_ui()
        self._connect_signals()
        self._setup_hub_subscriptions()

    def _setup_ui(self):
        """Initialize UI components."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Filter/Search
        self.filter_box = QtWidgets.QLineEdit()
        self.filter_box.setPlaceholderText("Filter caches...")
        self.filter_box.setClearButtonEnabled(True)
        layout.addWidget(self.filter_box)

        # Cache Tree
        self.cache_tree = QtWidgets.QTreeWidget()
        self.cache_tree.setColumnCount(2)
        self.cache_tree.setHeaderLabels(["Cache", "Version"])
        self.cache_tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.cache_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

        # Configure tree appearance
        self.cache_tree.setIndentation(0)
        self.cache_tree.setMinimumWidth(280)
        self.cache_tree.setMaximumWidth(350)
        self.cache_tree.setColumnWidth(0, 200)
        self.cache_tree.setColumnWidth(1, 80)
        self.cache_tree.setAlternatingRowColors(True)

        layout.addWidget(self.cache_tree)

        # Actions toolbar
        action_layout = QtWidgets.QHBoxLayout()

        self.attach_btn = QtWidgets.QPushButton("Attach")
        self.attach_btn.setToolTip("Attach selected cache to simulation node")

        self.detach_btn = QtWidgets.QPushButton("Detach")
        self.detach_btn.setToolTip("Detach cache from simulation node")

        self.materialize_btn = QtWidgets.QPushButton("Materialize")
        self.materialize_btn.setToolTip("Create a cached mesh from selected cache")

        for btn in (self.attach_btn, self.detach_btn, self.materialize_btn):
            btn.setEnabled(False)
            action_layout.addWidget(btn)

        layout.addLayout(action_layout)

    def _connect_signals(self):
        """Connect widget signals."""
        self.filter_box.textChanged.connect(self._filter_caches)
        self.cache_tree.customContextMenuRequested.connect(self._show_context_menu)
        self.cache_tree.itemSelectionChanged.connect(self._handle_selection)
        self.cache_tree.itemDoubleClicked.connect(self._handle_double_click)

        # Button connections
        self.attach_btn.clicked.connect(self._attach_selected)
        self.detach_btn.clicked.connect(self._detach_selected)
        self.materialize_btn.clicked.connect(self._materialize_selected)

    def _setup_hub_subscriptions(self):
        """Setup DataHub subscriptions."""
        # Subscribe to selection changes
        self.hub_subscribe(HubKeys.SELECTED_ITEM, self._on_node_selected)
        self.hub_subscribe(HubKeys.SELECTED_ITEMS, self._on_nodes_selected)

    # ========================================================================
    # HUB CALLBACKS
    # ========================================================================

    def _on_node_selected(self, old_value, new_value):
        """Hub callback: node selection changed."""
        if new_value is not None:
            self.set_node(new_value)

    def _on_nodes_selected(self, old_value, new_value):
        """Hub callback: multiple nodes selected."""
        if new_value and len(new_value) > 0:
            # For multiple selection, use first item
            self.set_node(new_value[0])

    # ========================================================================
    # PUBLIC METHODS
    # ========================================================================

    def set_node(self, node):
        """
        Set the current simulation node and update cache list.

        Args:
            node: BaseSimulationItem or similar with cache methods
        """
        self._current_node = node
        self.build_cache_list()

    def build_cache_list(self):
        """Build the cache list for the current node."""
        self.cache_tree.clear()

        if not self._current_node:
            self.cache_tree.setHeaderLabels(["Cache", "Version"])
            return

        try:
            cache_items = self._get_cache_items(self._current_node)

            # Sort by version (descending) and add to tree
            cache_items.sort(key=lambda x: x.cache_info.version, reverse=True)
            self.cache_tree.addTopLevelItems(cache_items)

            # Update header with node name
            node_name = getattr(self._current_node, 'short_name', str(self._current_node))
            self.cache_tree.setHeaderLabels([node_name, "Version"])

        except Exception as e:
            logger.error(f"Failed to build cache list: {e}")

    def get_selected_caches(self) -> List[CacheInfo]:
        """Get list of selected cache infos."""
        selected = []
        for item in self.cache_tree.selectedItems():
            if hasattr(item, 'cache_info'):
                selected.append(item.cache_info)
        return selected

    def clear(self):
        """Clear the cache tree."""
        self.cache_tree.clear()
        self._current_node = None

    # ========================================================================
    # PRIVATE METHODS
    # ========================================================================

    def _get_cache_items(self, dyn_item) -> List[CacheItem]:
        """Get cache items for a dynamic item."""
        cache_items = []

        try:
            # Determine cache type based on node type
            node_type = getattr(dyn_item, 'node_type', None)
            cache_type = self._get_cache_type(node_type)

            if not cache_type:
                return []

            # Get cache list from item
            if not hasattr(dyn_item, 'get_cache_list'):
                return []

            caches = dyn_item.get_cache_list()

            for cache_name in caches:
                cache_info = self._create_cache_info(dyn_item, cache_name, cache_type)
                if cache_info:
                    cache_items.append(CacheItem(cache_info))

        except Exception as e:
            logger.error(f"Failed to get cache items: {e}")

        return cache_items

    def _get_cache_type(self, node_type: str) -> Optional[CacheType]:
        """Determine cache type based on node type."""
        if node_type in ['nCloth', 'hairSystem']:
            return CacheType.NCACHE
        elif node_type == 'zSolverTransform':
            return CacheType.ALEMBIC
        return None

    def _create_cache_info(self, dyn_item, cache_name: str, cache_type: CacheType) -> Optional[CacheInfo]:
        """Create cache info object."""
        try:
            # Get cache path
            cache_dir = Path(dyn_item.cache_dir())
            extension = 'abc' if cache_type == CacheType.ALEMBIC else 'xml'
            cache_path = cache_dir / f"{cache_name}.{extension}"

            # Extract version from cache name
            version_match = re.search(r'v(\d{3})', cache_name)
            version = int(version_match.group(1)) if version_match else 0

            # Check validity and attachment
            is_valid = self._check_cache_validity(dyn_item, cache_name)
            is_attached = self._check_cache_attachment(dyn_item, cache_name)

            return CacheInfo(
                name=cache_name,
                path=cache_path,
                node=dyn_item.node,
                version=version,
                cache_type=cache_type,
                is_valid=is_valid,
                is_attached=is_attached,
                mesh=getattr(dyn_item, 'mesh_transform', None)
            )

        except Exception as e:
            logger.error(f"Failed to create cache info for {cache_name}: {e}")
            return None

    def _check_cache_validity(self, dyn_item, cache_name: str) -> bool:
        """Check if cache is valid based on metadata."""
        try:
            if not hasattr(dyn_item, 'metadata'):
                return True  # Assume valid if no metadata method

            metadata_path = Path(dyn_item.metadata())
            if not metadata_path.exists():
                return True  # Assume valid if no metadata file

            from dw_maya.dw_presets_io import dw_json
            metadata = dw_json.load_json(str(metadata_path))

            return metadata.get('isvalid', {}).get(cache_name, True)

        except Exception as e:
            logger.warning(f"Failed to check cache validity: {e}")
            return True

    def _check_cache_attachment(self, dyn_item, cache_name: str) -> bool:
        """Check if cache is currently attached."""
        try:
            from ..sim_cmds import cache_management
            return cache_management.cache_is_attached(dyn_item.node, cache_name)
        except Exception as e:
            logger.warning(f"Failed to check cache attachment: {e}")
            return False

    # ========================================================================
    # SELECTION HANDLING
    # ========================================================================

    def _handle_selection(self):
        """Handle cache selection changes."""
        selected_items = self.cache_tree.selectedItems()

        # Update button states
        has_selection = bool(selected_items)
        any_attached = any(
            getattr(item, 'cache_info', None) and item.cache_info.is_attached
            for item in selected_items
        )
        all_attached = all(
            getattr(item, 'cache_info', None) and item.cache_info.is_attached
            for item in selected_items
        ) if selected_items else False

        self.attach_btn.setEnabled(has_selection and not all_attached)
        self.detach_btn.setEnabled(has_selection and any_attached)
        self.materialize_btn.setEnabled(has_selection)

        # Publish and emit for first selected item
        if selected_items and hasattr(selected_items[0], 'cache_info'):
            cache_info = selected_items[0].cache_info

            # Publish to hub
            self.hub_publish(HubKeys.CACHE_SELECTED, cache_info)

            # Emit Qt signal for backwards compatibility
            self.cache_selected.emit(cache_info)

    def _handle_double_click(self, item, column):
        """Handle double-click to attach cache."""
        if hasattr(item, 'cache_info'):
            self._attach_cache(item.cache_info)

    # ========================================================================
    # CACHE OPERATIONS
    # ========================================================================

    def _attach_selected(self):
        """Attach selected caches."""
        for item in self.cache_tree.selectedItems():
            if hasattr(item, 'cache_info') and not item.cache_info.is_attached:
                self._attach_cache(item.cache_info)

    def _detach_selected(self):
        """Detach selected caches."""
        for item in self.cache_tree.selectedItems():
            if hasattr(item, 'cache_info') and item.cache_info.is_attached:
                self._detach_cache(item.cache_info)

    def _materialize_selected(self):
        """Materialize selected caches."""
        for item in self.cache_tree.selectedItems():
            if hasattr(item, 'cache_info'):
                self._materialize_cache(item.cache_info)

    def _attach_cache(self, cache_info: CacheInfo):
        """Attach a single cache."""
        try:
            # Emit signal for main UI to handle
            self.cache_attached.emit(cache_info)

            # Update attachment state
            cache_info.is_attached = True

            # Publish updated state
            self.hub_publish(HubKeys.CACHE_SELECTED, cache_info)

            # Refresh list
            self.build_cache_list()

        except Exception as e:
            logger.error(f"Failed to attach cache: {e}")

    def _detach_cache(self, cache_info: CacheInfo):
        """Detach a single cache."""
        try:
            from ..sim_cmds import cache_management
            cache_management.delete_caches([cache_info.node])

            cache_info.is_attached = False
            self.cache_detached.emit(cache_info)

            # Publish updated state
            self.hub_publish(HubKeys.CACHE_SELECTED, cache_info)

            self.build_cache_list()

        except Exception as e:
            logger.error(f"Failed to detach cache: {e}")

    def _materialize_cache(self, cache_info: CacheInfo):
        """Create materialized mesh from cache."""
        try:
            from ..sim_cmds import cache_management

            if not cache_info.mesh:
                cmds.warning("No mesh found for materialization")
                return

            result = cache_management.materialize(cache_info.mesh, str(cache_info.path))
            logger.info(f"Materialized cache: {result}")

        except Exception as e:
            logger.error(f"Failed to materialize cache: {e}")

    # ========================================================================
    # FILTER & CONTEXT MENU
    # ========================================================================

    def _filter_caches(self, filter_text: str):
        """Filter cache items based on search text."""
        filter_lower = filter_text.lower()

        for i in range(self.cache_tree.topLevelItemCount()):
            item = self.cache_tree.topLevelItem(i)
            if hasattr(item, 'cache_info'):
                should_show = (
                        filter_lower in item.cache_info.name.lower() or
                        f"v{item.cache_info.version:03d}".lower() in filter_lower
                )
                item.setHidden(not should_show)

    def _show_context_menu(self, position: QtCore.QPoint):
        """Show context menu for cache operations."""
        menu = QtWidgets.QMenu(self)
        selected_items = self.cache_tree.selectedItems()

        if not selected_items:
            return

        # Basic operations
        attach_action = menu.addAction("Attach Cache")
        detach_action = menu.addAction("Detach Cache")
        menu.addSeparator()
        materialize_action = menu.addAction("Materialize")
        menu.addSeparator()

        # File operations
        reveal_action = menu.addAction("Reveal in Explorer")
        delete_action = menu.addAction("Delete Cache Files")

        # Enable/disable based on state
        any_attached = any(
            hasattr(item, 'cache_info') and item.cache_info.is_attached
            for item in selected_items
        )
        all_attached = all(
            hasattr(item, 'cache_info') and item.cache_info.is_attached
            for item in selected_items
        )

        attach_action.setEnabled(not all_attached)
        detach_action.setEnabled(any_attached)

        # Execute action
        action = menu.exec_(self.cache_tree.viewport().mapToGlobal(position))

        if action == attach_action:
            self._attach_selected()
        elif action == detach_action:
            self._detach_selected()
        elif action == materialize_action:
            self._materialize_selected()
        elif action == reveal_action:
            self._reveal_in_explorer()
        elif action == delete_action:
            self._delete_cache_files()

    def _reveal_in_explorer(self):
        """Open file explorer at cache location."""
        selected = self.get_selected_caches()
        if selected:
            cache_dir = selected[0].path.parent
            if cache_dir.exists():
                import subprocess
                import sys
                if sys.platform == 'win32':
                    subprocess.Popen(f'explorer "{cache_dir}"')
                elif sys.platform == 'darwin':
                    subprocess.Popen(['open', str(cache_dir)])
                else:
                    subprocess.Popen(['xdg-open', str(cache_dir)])

    def _delete_cache_files(self):
        """Delete selected cache files from disk."""
        selected = self.get_selected_caches()
        if not selected:
            return

        # Confirm deletion
        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete Cache Files",
            f"Delete {len(selected)} cache file(s) from disk?\nThis cannot be undone.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )

        if reply == QtWidgets.QMessageBox.Yes:
            for cache_info in selected:
                try:
                    # Delete all files matching the cache name
                    cache_dir = cache_info.path.parent
                    base_name = cache_info.path.stem

                    for f in cache_dir.glob(f"{base_name}.*"):
                        f.unlink()

                except Exception as e:
                    logger.error(f"Failed to delete {cache_info.name}: {e}")

            self.build_cache_list()

    # ========================================================================
    # CLEANUP - handled by DynEvalWidget base class