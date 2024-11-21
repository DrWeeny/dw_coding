from dataclasses import dataclass
from typing import Optional, List, Dict, Union, Any
from enum import Enum
from PySide6 import QtWidgets, QtGui, QtCore
from pathlib import Path
import maya.cmds as cmds
from dw_logger import get_logger
from ..dendrology.cache_leaf import CacheItem
import re
from .wgt_cache_operation import CacheOperationManager, OperationResult, CacheOperationStatus

logger = get_logger()

class PresetType(Enum):
    NUCLEUS = "nucleus"
    NCLOTH = "nCloth"
    NHAIR = "hairSystem"
    NRIGID = "nRigid"
    ZIVA = "zSolver"

@dataclass
class PresetInfo:
    """Data container for simulation presets."""
    name: str
    node_type: PresetType
    attributes: Dict[str, Any]
    version: str
    cache_name: Optional[str] = None
    solver: Optional[str] = None

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


class CacheTreeWidget(QtWidgets.QWidget):
    """Enhanced widget for managing simulation caches."""

    cache_selected = QtCore.Signal(CacheInfo)  # Emitted when cache is selected
    cache_attached = QtCore.Signal(CacheInfo)  # Emitted when cache is attached
    cache_detached = QtCore.Signal(CacheInfo)  # Emitted when cache is detached

    def __init__(self, parent=None):
        super().__init__(parent)
        self.node = None
        self.cache_manager = CacheOperationManager(self)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Initialize UI components."""
        layout = QtWidgets.QVBoxLayout(self)

        # Filter/Search
        self.filter_box = QtWidgets.QLineEdit()
        self.filter_box.setPlaceholderText("Filter caches...")
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
        self.cache_tree.setMaximumWidth(280)
        self.cache_tree.setColumnWidth(0, 200)
        self.cache_tree.setColumnWidth(1, 80)

        layout.addWidget(self.cache_tree)

        # Actions toolbar
        action_layout = QtWidgets.QHBoxLayout()

        self.attach_btn = QtWidgets.QPushButton("Attach")
        self.detach_btn = QtWidgets.QPushButton("Detach")
        self.materialize_btn = QtWidgets.QPushButton("Materialize")

        for btn in (self.attach_btn, self.detach_btn, self.materialize_btn):
            btn.setEnabled(False)
            action_layout.addWidget(btn)

        layout.addLayout(action_layout)

    def _connect_signals(self):
        """Connect widget signals."""
        self.filter_box.textChanged.connect(self._filter_caches)
        self.cache_tree.customContextMenuRequested.connect(self._show_context_menu)
        self.cache_tree.itemSelectionChanged.connect(self._handle_selection)

        # Button connections
        self.attach_btn.clicked.connect(self._attach_selected)
        self.detach_btn.clicked.connect(self._detach_selected)
        self.materialize_btn.clicked.connect(self._materialize_selected)

    def set_node(self, node):
        """Set the current simulation node and update cache list."""
        self.node = node
        self.build_cache_list()

    def build_cache_list(self):
        """Build the cache list for the current node."""
        self.cache_tree.clear()
        if not self.node:
            return

        try:
            cache_items = []

            # Get caches based on node type
            if isinstance(self.node, list):
                for dyn_item in self.node:
                    cache_items.extend(self._get_cache_items(dyn_item))
            else:
                cache_items.extend(self._get_cache_items(self.node))

            # Sort by version (descending) and add to tree
            cache_items.sort(key=lambda x: x.cache_info.version, reverse=True)
            self.cache_tree.addTopLevelItems(cache_items)

            # Update header
            node_name = self.node[0].short_name if isinstance(self.node, list) else self.node.short_name
            self.cache_tree.setHeaderLabels([node_name, "Version"])

        except Exception as e:
            logger.error(f"Failed to build cache list: {e}")

    def _get_cache_items(self, dyn_item) -> List[CacheItem]:
        """Get cache items for a dynamic item."""
        cache_items = []

        try:
            # Determine cache type based on node type
            cache_type = self._get_cache_type(dyn_item.node_type)
            if not cache_type:
                return []

            # Get cache list and create items
            caches = dyn_item.get_cache_list()
            for cache_name in caches:
                cache_info = self._create_cache_info(
                    dyn_item, cache_name, cache_type
                )
                if cache_info:
                    cache_items.append(CacheItem(cache_info))

        except Exception as e:
            logger.error(f"Failed to get cache items for {dyn_item.node}: {e}")

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
            # Get cache path and metadata
            cache_dir = Path(dyn_item.cache_dir())
            extension = 'abc' if cache_type == CacheType.ALEMBIC else 'xml'
            cache_path = cache_dir / f"{cache_name}.{extension}"

            # Get version from cache name
            version_match = re.search(r'v(\d{3})', cache_name)
            version = int(version_match.group(1)) if version_match else 0

            # Check validity and attachment
            metadata = Path(dyn_item.metadata())
            is_valid = self._check_cache_validity(metadata, cache_name)
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

    def _attach_selected(self):
        """Handle attach operation for selected caches."""
        selected_items = self.cache_tree.selectedItems()
        if not selected_items:
            return

        cache_infos = [item.cache_info for item in selected_items]
        results = self.cache_manager.attach_caches(cache_infos)

        self._handle_operation_results(results, "Attach Operation")
        self.build_cache_list()  # Refresh the list

    def _detach_selected(self):
        """Handle detach operation for selected caches."""
        selected_items = self.cache_tree.selectedItems()
        if not selected_items:
            return

        cache_infos = [item.cache_info for item in selected_items]
        results = self.cache_manager.detach_caches(cache_infos)

        self._handle_operation_results(results, "Detach Operation")
        self.build_cache_list()  # Refresh the list

    def _materialize_selected(self):
        """Handle materialize operation for selected caches."""
        selected_items = self.cache_tree.selectedItems()
        if not selected_items:
            return

        cache_infos = [item.cache_info for item in selected_items]
        results = self.cache_manager.materialize_caches(cache_infos)

        self._handle_operation_results(results, "Materialize Operation")

    def _handle_operation_results(self, results: List[OperationResult], operation_name: str):
        """Display results of cache operations."""
        failed_ops = [r for r in results if r.status == CacheOperationStatus.FAILED]

        if failed_ops:
            message = f"\n".join([
                f"• {r.message}: {str(r.error)}"
                for r in failed_ops
            ])

    def _filter_caches(self, filter_text: str):
        """Filter cache items based on search text."""
        for i in range(self.cache_tree.topLevelItemCount()):
            item = self.cache_tree.topLevelItem(i)
            should_show = (
                    filter_text.lower() in item.cache_info.name.lower() or
                    f"v{item.cache_info.version:03d}".lower() in filter_text.lower()
            )
            item.setHidden(not should_show)

    def _show_context_menu(self, position: QtCore.QPoint):
        """Show context menu for cache operations."""
        menu = QtWidgets.QMenu(self)
        selected_items = self.cache_tree.selectedItems()

        if not selected_items:
            return

        # Add basic operations
        attach_action = menu.addAction("Attach Cache")
        detach_action = menu.addAction("Detach Cache")
        menu.addSeparator()
        materialize_action = menu.addAction("Materialize")

        # Add validation section if cache has validation issues
        if any(not item.cache_info.is_valid for item in selected_items):
            menu.addSeparator()
            validate_action = menu.addAction("Validate Cache")

        # Enable/disable actions based on selection state
        attach_action.setEnabled(not all(item.cache_info.is_attached for item in selected_items))
        detach_action.setEnabled(any(item.cache_info.is_attached for item in selected_items))

        # Handle action triggers
        action = menu.exec_(self.cache_tree.viewport().mapToGlobal(position))
        if action == attach_action:
            self._attach_selected()
        elif action == detach_action:
            self._detach_selected()
        elif action == materialize_action:
            self._materialize_selected()
        elif action == validate_action:
            self._validate_selected()

    def _handle_selection(self):
        """Update UI elements based on selection."""
        selected_items = self.cache_tree.selectedItems()

        # Update button states
        self.attach_btn.setEnabled(
            bool(selected_items) and
            not all(item.cache_info.is_attached for item in selected_items)
        )
        self.detach_btn.setEnabled(
            bool(selected_items) and
            any(item.cache_info.is_attached for item in selected_items)
        )
        self.materialize_btn.setEnabled(bool(selected_items))

        # Emit selection signal for the first selected item
        if selected_items:
            self.cache_selected.emit(selected_items[0].cache_info)

    def _check_cache_validity(self, metadata_path: Path, cache_name: str) -> bool:
        """Check if cache is valid based on metadata."""
        try:
            if not metadata_path.exists():
                return False

            import json
            with metadata_path.open('r') as f:
                metadata = json.load(f)

            # Check if cache is marked as valid in metadata
            return (
                    'isvalid' in metadata and
                    cache_name in metadata['isvalid'] and
                    metadata['isvalid'][cache_name]
            )
        except Exception as e:
            logger.warning(f"Failed to check cache validity for {cache_name}: {e}")
            return False

    def _check_cache_attachment(self, dyn_item, cache_name: str) -> bool:
        """Check if cache is currently attached to the dynamic item."""
        try:
            from . import cache_management

            if dyn_item.node_type == 'zSolverTransform':
                # Check Alembic attachment
                abc_target = dyn_item.alembic_target()
                if not abc_target:
                    return False

                filename_attr = f"{abc_target}.filename"
                current_cache = cmds.getAttr(filename_attr) or ""
                return cache_name in current_cache

            else:
                # Check nCache attachment
                return cache_management.cache_is_attached(dyn_item.node, cache_name)

        except Exception as e:
            logger.warning(f"Failed to check cache attachment for {cache_name}: {e}")
            return False

    def _validate_selected(self):
        """Validate selected cache files."""
        selected_items = self.cache_tree.selectedItems()
        if not selected_items:
            return

        self.progress = QtWidgets.QProgressDialog(
            "Validating caches...", "Cancel", 0, len(selected_items), self
        )
        self.progress.setWindowModality(QtCore.Qt.WindowModal)

        invalid_caches = []
        for i, item in enumerate(selected_items):
            if self.progress.wasCanceled():
                break

            self.progress.setValue(i)
            cache_info = item.cache_info

            # Check file existence and basic validation
            if not self._validate_cache_file(cache_info):
                invalid_caches.append(cache_info.name)

        self.progress.setValue(len(selected_items))

        if invalid_caches:
            QtWidgets.QMessageBox.warning(
                self,
                "Cache Validation",
                f"The following caches have validation issues:\n\n" +
                "\n".join(f"• {name}" for name in invalid_caches)
            )
        else:
            QtWidgets.QMessageBox.information(
                self,
                "Cache Validation",
                "All selected caches are valid."
            )

    def _validate_cache_file(self, cache_info: CacheInfo) -> bool:
        """Perform basic validation on cache file."""
        try:
            # Check file existence
            if not cache_info.path.exists():
                return False

            # Check file size
            if cache_info.path.stat().st_size == 0:
                return False

            # Perform format-specific validation
            if cache_info.cache_type == CacheType.ALEMBIC:
                return self._validate_abc_cache(cache_info.path)
            else:
                return self._validate_ncache(cache_info.path)

        except Exception as e:
            logger.error(f"Cache validation failed for {cache_info.name}: {e}")
            return False

    def _validate_abc_cache(self, path: Path) -> bool:
        """Validate Alembic cache file."""
        try:
            # Basic ABC validation (could be expanded)
            with path.open('rb') as f:
                header = f.read(8)
                # Check ABC magic number
                return header.startswith(b'HDF')
        except Exception:
            return False

    def _validate_ncache(self, path: Path) -> bool:
        """Validate nCache file."""
        try:
            # Basic XML validation for nCache
            with path.open('r') as f:
                content = f.read(1024)  # Read first 1KB
                return (
                        '<?xml' in content and
                        'cacheVersion' in content
                )
        except Exception:
            return False