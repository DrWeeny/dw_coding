import sys
from typing import List, Any, Dict, Set
import shutil
from PySide6 import QtWidgets, QtGui, QtCore  # Use PySide6 for Maya compatibility with Python 3
from pathlib import Path
import maya.utils as mu
import mmap

# External module imports (always required)
import dw_maya.dw_presets_io as dw_json
from dw_logger import get_logger

logger = get_logger()

# Application mode variables
MODE = 0

try:
    import hou
    MODE=2
except ImportError:
    pass

try:
    import maya.cmds as cmds
    import maya.OpenMayaUI as omui
    from shiboken6 import wrapInstance  # Maya now uses shiboken6 with PySide6
    from . import sim_cmds
    from .sim_cmds import ziva_cmds
    from .dendrology.nucleus_leaf import *
    from .dendrology.ziva_leaf import ZSolverTreeItem, FasciaTreeItem, SkinTreeItem
    from .dendrology.cache_leaf import CacheItem
    from .sim_widget import StateManager, SimulationTreeView, PresetManager, CacheTreeWidget, MapTreeWidget, PresetWidget, CommentEditor, TreeBuildProgress
    MODE = 1
except ImportError:
    pass

# ====================================================================
# GENERAL FUNCTIONS
# ====================================================================

def copy_file(src, dest):
    """Helper function to copy a single file."""
    shutil.copyfile(src, dest)

def copy_files_parallel(file_paths, destination_dir, max_workers=4):
    """
    Copies multiple files to the destination directory in parallel.

    Args:
        file_paths (list): List of file paths to copy.
        destination_dir (str): Directory to copy files to.
        max_workers (int): Number of parallel workers (threads).
    """
    from concurrent.futures import ThreadPoolExecutor
    destination_dir = Path(destination_dir)
    if not destination_dir.exists():
        destination_dir.mkdir(parents=True)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for src in file_paths:
            dest = destination_dir / Path(src).name
            futures.append(executor.submit(copy_file, src, dest))

        for future in futures:
            future.result()  # Ensure all files are copied


def safe_copy_file(src, dest):
    """Copy file safely, ensuring no file exists at the destination and creating directories as needed."""
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if not dest_path.exists():
        shutil.copyfile(src, dest)


def copy_files_safely(file_paths, destination_dir):
    """
    Copies multiple files to the destination directory sequentially.
    Ensures Maya commands are only called from the main thread.
    """
    for src in file_paths:
        dest = Path(destination_dir) / Path(src).name

        # Use Maya's main thread handling if any Maya-dependent file preparation or checks are needed.
        mu.executeInMainThreadWithResult(safe_copy_file, src, dest)

def copy_large_file(src, dest):
    """Copy large files using memory mapping."""
    with open(src, "rb") as fsrc, open(dest, "wb") as fdst:
        # Memory-map the file, length 0 means whole file
        with mmap.mmap(fsrc.fileno(), 0, access=mmap.ACCESS_READ) as m:
            shutil.copyfileobj(m, fdst)
# ====================================================================
# WINDOW GETTER
# ====================================================================

def get_maya_window():
    """
    Get the Maya main window as a QWidget pointer.
    Returns:
        QWidget: The main Maya window.
    """
    return wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)


def get_houdini_window():
    """
    Get the main Houdini window.
    Returns:
        QWidget: The main Houdini window.
    """
    win = hou.ui.mainQtWindow()
    return win


def get_all_treeitems(model, item_type=None):
    """
    Generator that yields items in the tree, optionally filtered by item type.

    Args:
        model (QtGui.QStandardItemModel): The model containing the tree.
        item_type (str, optional): The type of items to yield (e.g., "nCloth").

    Yields:
        QtGui.QStandardItem: Each matching item in the tree.
    """
    def recurse(parent_item):
        for row in range(parent_item.rowCount()):
            child_item = parent_item.child(row)
            if item_type is None or child_item.node_type == item_type:
                yield child_item
            yield from recurse(child_item)

    root_item = model.invisibleRootItem()
    yield from recurse(root_item)


class DynEvalUI(QtWidgets.QMainWindow):

    """
    The Sim UI embed a unified way to simulate different type of solvers
    """
    save_preset = True

    def __init__(self, parent=None):
        super().__init__(parent)

        # Core managers
        self.state_manager = StateManager()
        self.preset_manager = PresetManager()

        # UI Setup
        self.setGeometry(867, 546, 1200, 600)  # Wider to accommodate new features
        self.setWindowTitle('Dynamic Systems Manager')

        # Track if mouse is over the window
        self.setMouseTracking(True)
        self._mouse_over = False

        # Setup central widget and layout
        self.central_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.central_widget)

        # Initialize UI
        self._setup_ui()
        self._setup_shortcuts()

    def _setup_ui(self):
        """Initialize the main UI layout."""

        main_layout = QtWidgets.QHBoxLayout()

        # ====================================================================
        # LEFT PANEL
        # ====================================================================
        left_panel = QtWidgets.QVBoxLayout()

        # Set up the main tree model
        self.dyn_eval_tree = SimulationTreeView()

        # Create a contextual menu
        self.dyn_eval_tree.installEventFilter(self)
        self.dyn_eval_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.dyn_eval_tree.customContextMenuRequested.connect(self._show_tree_context_menu)

        # Add status label beneath tree
        self.status_layout = QtWidgets.QVBoxLayout()
        self.status_label = QtWidgets.QLabel()
        self.status_label.setAlignment(QtCore.Qt.AlignLeft)
        self.status_label.hide()

        # Add loading indicator
        self.loading_movie = QtGui.QMovie(":/icons/loading.gif")
        self.loading_label = QtWidgets.QLabel()
        self.loading_label.setMovie(self.loading_movie)
        self.loading_label.hide()

        status_wrapper = QtWidgets.QHBoxLayout()
        status_wrapper.addWidget(self.loading_label)
        status_wrapper.addWidget(self.status_label, stretch=1)
        self.status_layout.addLayout(status_wrapper)

        left_panel.addLayout(self.status_layout)

        main_layout.addLayout(left_panel)

        # ====================================================================
        # MIDDLE PANEL
        # ====================================================================
        middle_panel = QtWidgets.QVBoxLayout()
        # Set up the cache and maps area
        self.cb_mode_picker = QtWidgets.QComboBox()
        # todo : deformer list
        self.mode_selector.addItems(["Cache", "Maps", "Presets"])
        middle_panel.addWidget(self.mode_selector)

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
        middle_panel.addWidget(self.stack_widget)
        main_layout.addLayout(middle_panel)

        # ====================================================================
        # RIGHT PANEL
        # ====================================================================
        self.details_panel = QtWidgets.QTabWidget()
        self.details_panel.setMinimumWidth(300)

        # Comments tab
        self.comments_tab = CommentEditor()
        self.details_panel.addTab(self.comments_tab, "Comments")

        # Info tab (for showing node/cache/map details)
        self.info_tab = QtWidgets.QTextEdit()
        self.info_tab.setReadOnly(True)
        self.details_panel.addTab(self.info_tab, "Info")

        main_layout.addWidget(self.details_panel)

        # Connect signals
        self._connect_signals()

    def _connect_signals(self):
        """Connect all UI signals."""
        # Mode selector
        self.mode_selector.currentIndexChanged.connect(self._handle_mode_change)

        # Tree view signals
        self.dyn_eval_tree.selectionModel().selectionChanged.connect(
            self._handle_tree_selection
        )

        # Cache signals
        self.cache_tree.cache_selected.connect(self._handle_cache_selection)
        self.cache_tree.cache_attached.connect(self._handle_cache_attached)

        # Maps signals
        self.maps_tree.map_edited.connect(self._handle_map_edited)

        # Preset signals
        self.preset_widget.preset_applied.connect(self._handle_preset_applied)

        # Comment signals
        self.comments_tab.save_requested.connect(self._handle_comment_save)

    def _handle_mode_change(self, index: int):
        """Handle switching between cache/maps/preset modes."""
        self.stack_widget.setCurrentIndex(index)
        current_item = self.get_selected_tree_item()

        if current_item:
            if index == 0:  # Cache mode
                self.cache_tree.set_node(current_item)
            elif index == 1:  # Maps mode
                self.maps_tree.set_node(current_item)
            else:  # Preset mode
                self.preset_widget.set_node(current_item)

    def _handle_tree_selection(self):
        """Handle selection changes in main tree."""
        current_item = self.get_selected_tree_item()
        if not current_item:
            return

        # Update current view based on mode
        current_mode = self.mode_selector.currentIndex()
        self._handle_mode_change(current_mode)

        # Update info panel
        self._update_info_panel(current_item)

    def _update_info_panel(self, item):
        """Update info panel with current item details."""
        info_text = []
        info_text.append(f"Node: {item.node}")
        info_text.append(f"Type: {item.node_type}")

        if hasattr(item, 'solver_name'):
            info_text.append(f"Solver: {item.solver_name}")

        if hasattr(item, 'mesh_transform'):
            info_text.append(f"Mesh: {item.mesh_transform}")

        self.info_tab.setText("\n".join(info_text))

    def _show_tree_context_menu(self, position: QtCore.QPoint):
        """Show context menu for tree items."""
        menu = QtWidgets.QMenu(self)
        current_item = self.get_selected_tree_item()

        if current_item:
            # Basic operations
            menu.addAction("Select in Maya", self._select_in_maya)
            menu.addSeparator()

            # Add type-specific operations
            if current_item.node_type in ['nCloth', 'hairSystem']:
                cache_menu = menu.addMenu("Cache")
                cache_menu.addAction("Create nCache", self._create_ncache)

            elif current_item.node_type == 'zSolverTransform':
                cache_menu = menu.addMenu("Cache")
                cache_menu.addAction("Create Alembic", self._create_abc_cache)

        menu.exec_(self.dyn_eval_tree.viewport().mapToGlobal(position))

    # ====================================================================
    # TREE BUILDING METHODS
    # ====================================================================
    def build_tree(self):
        """Build the complete simulation hierarchy tree."""
        try:
            self._show_status("Initializing...", True)
            self.dyn_eval_tree.model.clear()

            # Get data (safely in main thread)
            self._show_status("Loading Nucleus systems...", True)
            nucleus_data = mu.executeInMainThreadWithResult(self._get_nucleus_data)

            self._show_status("Loading Ziva systems...", True)
            ziva_data = mu.executeInMainThreadWithResult(self._get_ziva_data)

            # Build trees
            if nucleus_data:
                self._show_status("Building Nucleus tree...", True)
                self._build_nucleus_tree(nucleus_data)

            if ziva_data:
                self._show_status("Building Ziva tree...", True)
                self._build_ziva_tree(ziva_data)

            # Expand items
            self._show_status("Finalizing...", True)
            for i in range(self.dyn_eval_tree.model.rowCount()):
                index = self.dyn_eval_tree.model.index(i, 0)
                self.dyn_eval_tree.expand(index)

            self._hide_status()

        except Exception as e:
            logger.error(f"Failed to build tree: {e}")

    def _show_status(self, message: str, loading: bool = False):
        """Show status message with optional loading animation."""
        self.status_label.setText(message)
        self.status_label.show()

        if loading:
            self.loading_movie.start()
            self.loading_label.show()
        else:
            self.loading_movie.stop()
            self.loading_label.hide()

    def _hide_status(self):
        """Hide status indicators."""
        self.loading_movie.stop()
        self.loading_label.hide()
        self.status_label.hide()

    def _get_nucleus_data(self) -> Dict[str, Any]:
        """Gather nucleus system data safely."""
        try:
            return sim_cmds.dw_get_hierarchy()
        except Exception as e:
            logger.error(f"Failed to get nucleus data: {e}")
            return {}

    def _get_ziva_data(self) -> Dict[str, Any]:
        """Gather Ziva system data safely."""
        try:
            return ziva_cmds.ziva_sys()
        except Exception as e:
            logger.error(f"Failed to get Ziva data: {e}")
            return {}

    def _build_nucleus_tree(self, system_hierarchy: Dict[str, Any]):
        """Build nucleus system hierarchy with improved organization.

        Args:
            system_hierarchy: Dictionary of nucleus systems
        """
        try:
            for character, solvers in system_hierarchy.items():
                # Create character group
                char_item = CharacterTreeItem(character)

                # Sort and add solvers
                sorted_solvers = sim_cmds.sort_list_by_outliner(solvers.keys())
                for solver in sorted_solvers:
                    # Create solver item
                    solver_item = NucleusStandardItem(solver)

                    # Add dynamic elements to solver
                    elements = solvers[solver]
                    if any(elements.get(key) for key in ['nCloth', 'hairSystem', 'nRigid']):
                        self._add_dynamic_elements(elements, solver_item)

                    char_item.appendRow(solver_item)

                self.dyn_eval_tree.model.appendRow(char_item)

        except Exception as e:
            logger.error(f"Failed to build nucleus tree: {e}")

    def _build_ziva_tree(self, ziva_hierarchy: Dict[str, Any]):
        """Build Ziva system hierarchy with improved organization.

        Args:
            ziva_hierarchy: Dictionary of Ziva systems
        """
        try:
            for character, node_types in ziva_hierarchy.items():
                # Create character group
                char_item = CharacterTreeItem(character)

                # Add solver if present
                solver = node_types.get('solver')
                if solver:
                    solver_item = ZSolverTreeItem(solver)
                    char_item.appendRow(solver_item)

                # Add muscles and skins with proper ordering
                for node_type in ['muscle', 'skin']:
                    nodes = node_types.get(node_type, [])
                    if nodes:
                        item_class = FasciaTreeItem if node_type == 'muscle' else SkinTreeItem
                        self._add_ordered_items(nodes, item_class, char_item)

                self.dyn_eval_tree.model.appendRow(char_item)

        except Exception as e:
            logger.error(f"Failed to build Ziva tree: {e}")

    def _add_dynamic_elements(self, elements: Dict[str, List[str]], parent_item: QtGui.QStandardItem):
        """Add dynamic elements to parent item with proper organization.

        Args:
            elements: Dictionary of element types and their nodes
            parent_item: Parent item to add elements to
        """
        # Define element types and their corresponding item classes
        element_types = [
            ('nCloth', ClothTreeItem),
            ('hairSystem', HairTreeItem),
            ('nRigid', NRigidTreeItem)
        ]

        for element_type, item_class in element_types:
            nodes = elements.get(element_type, [])
            if nodes:
                self._add_ordered_items(nodes, item_class, parent_item)

    def _add_ordered_items(self, nodes: List[str], item_class: type, parent_item: QtGui.QStandardItem):
        """Add items in proper outliner order with error handling.

        Args:
            nodes: List of node names to add
            item_class: Class to use for creating items
            parent_item: Parent item to add to
        """
        try:
            sorted_nodes = sim_cmds.sort_list_by_outliner(nodes)
            for node in sorted_nodes:
                try:
                    item = item_class(node)
                    parent_item.appendRow(item)
                except Exception as e:
                    logger.warning(f"Failed to create item for {node}: {e}")

        except Exception as e:
            logger.error(f"Failed to add ordered items: {e}")

    def refresh_tree(self):
        """Refresh the tree while maintaining expansion state."""
        # Store expansion state
        expanded_items = self._get_expanded_items()

        # Rebuild tree
        self.build_tree()

        # Restore expansion state
        self._restore_expanded_items(expanded_items)

    def _get_expanded_items(self) -> Set[str]:
        """Get set of expanded item paths."""
        expanded = set()

        def collect_expanded(parent_index):
            if self.dyn_eval_tree.isExpanded(parent_index):
                item = self.dyn_eval_tree.model.itemFromIndex(parent_index)
                expanded.add(self._get_item_path(item))

            for row in range(self.dyn_eval_tree.model.rowCount(parent_index)):
                child_index = self.dyn_eval_tree.model.index(row, 0, parent_index)
                collect_expanded(child_index)

        collect_expanded(QtCore.QModelIndex())
        return expanded

    def _restore_expanded_items(self, expanded_paths: Set[str]):
        """Restore expansion state from paths."""

        def expand_matched(parent_index):
            item = self.dyn_eval_tree.model.itemFromIndex(parent_index)
            if self._get_item_path(item) in expanded_paths:
                self.dyn_eval_tree.expand(parent_index)

            for row in range(self.dyn_eval_tree.model.rowCount(parent_index)):
                child_index = self.dyn_eval_tree.model.index(row, 0, parent_index)
                expand_matched(child_index)

        expand_matched(QtCore.QModelIndex())

    def _get_item_path(self, item: QtGui.QStandardItem) -> str:
        """Get unique path for tree item."""
        path = []
        while item:
            path.append(item.text())
            item = item.parent()
        return '/'.join(reversed(path))

    # ====================================================================
    # SELECTION HELPERS
    # ====================================================================

    def get_selected_tree_item(self,
                               multiple_selection=False) -> list[Any]:
        """Get the first selected item in the QTreeView.

        Returns:
            QtGui.QStandardItem: The first selected item, if any.
        """
        indexes = self.dyn_eval_tree.selectionModel().selectedRows()
        if indexes:
            if multiple_selection:
                return [self.dyn_eval_tree.model.itemFromIndex(index) for index in indexes]
            return self.dyn_eval_tree.model.itemFromIndex(indexes[0])
        return None

    # ====================================================================
    # TOGGLE AND STATE MANAGEMENT
    # ====================================================================

    def on_toggle(self, index, state):
        """Slot to handle toggling of dynamic state from delegate."""
        item = self.dyn_eval_tree.model.itemFromIndex(index)
        item.setData(state, QtCore.Qt.UserRole + 3)  # Update model data if needed
        # Apply state change to the node in Maya
        try:
            cmds.setAttr(f"{item.node}.{item.state_attr}", int(state))
        except Exception as e:
            cmds.warning(f"Failed to toggle state for {item.node}: {e}")

    # ====================================================================
    # CONTEXT MENU AND ACTIONS
    # ====================================================================


    def _context_add_cache_options(self, menu, node_type):
        """
        Adds cache creation options to the context menu based on the node type.

        Args:
            menu (QtWidgets.QMenu): The context menu to add cache options to.
            node_type (str): The type of the selected node to determine applicable options.
        """
        # Add a label for the cache options section
        cache_label = QtWidgets.QWidgetAction(self)
        cache_label.setDefaultWidget(QtWidgets.QLabel(' '*7+'Cache Methods :'))
        menu.addAction(cache_label)

        # Add specific cache options based on the node type
        if node_type in ['nCloth', 'hairSystem']:
            menu.addAction(self._context_create_action('Create nCache for Selected', self.createCache))
            menu.addSeparator()

        if node_type in ['nCloth', 'nRigid']:
            menu.addAction(self._context_create_action('Create GeoCache for Selected', self.createGeoCache))
            menu.addSeparator()

        if node_type == 'zSolverTransform':
            menu.addAction(self._context_create_action('Create Alembic Cache', self.createZAbcCache))
            menu.addSeparator()

    def _context_create_action(self, text, handler):
        """
        Helper method to create a QAction for the context menu with a connected handler.

        Args:
            text (str): The display text for the action.
            handler (callable): The function to call when the action is triggered.

        Returns:
            QtWidgets.QAction: The created action with the specified text and handler.
        """
        action = QtWidgets.QAction(text, self)
        action.triggered.connect(handler) # Connect the specified handler function
        return action

    # ====================================================================
    # CACHE CREATION METHODS
    # ====================================================================

    def createZAbcCache(self):
        """Creates Alembic cache for selected Ziva items."""
        dyn_items = self.dyn_eval_tree.selectedItems()
        if not dyn_items:
            cmds.warning("No items selected for Alembic caching.")
            return

        self._show_status("Preparing Alembic cache...", True)

        try:
            current_iter, futurdir, meshes = self._prepare_cache_items(dyn_items)

            # Create Alembic cache
            self._show_status("Creating Alembic cache...", True)
            caches = mu.executeInMainThreadWithResult(
                ziva_cmds.create_cache, futurdir[0], meshes
            )

            # Handle multiple caches
            if len(futurdir) > 1:
                self._show_status("Copying cache files...", True)
                for file in futurdir:
                    copy_files_safely(caches, file)

        # ===============================================================
            # Update metadata
            comment = self.comments_tab.getComment()
            preset = None
            if self.save_preset:
                preset = mu.executeInMainThreadWithResult(
                    ziva_cmds.get_preset, dyn_items[0].solver_name
                )

            if comment or preset:
                self._update_cache_metadata(
                    dyn_items[0], {}, current_iter,
                    comment=comment, preset=preset)

        # ===============================================================

            # Attach caches
            self._show_status("Attaching caches...", True)
            for item in dyn_items:
                abc_attr = f"{item.alembic_target()}.filename"
                mu.executeInMainThreadWithResult(
                    cmds.setAttr,
                    abc_attr, item.cache_file(0, ""),
                    type='string'
                )

            # Refresh view
            if self.mode_selector.currentIndex() == 0:
                mu.executeDeferred(self.cache_tree.build_cache_list)

            self._hide_status()

        except Exception as e:
            self._show_status(f"Error creating Alembic cache: {str(e)}", False)
            logger.error(f"Alembic cache creation failed: {e}")


    def createCache(self):
        """
        Creates an nCache for selected nCloth items and updates metadata.
        This function supports multiple selections for nCloth items.
        """
        # cacheDir cacheFile()
        dyn_items = self.dyn_eval_tree.selectedItems()
        if not dyn_items:
            cmds.warning("No items selected for nCache creation.")
            return

        self._show_status("Preparing cache creation...", True)

        try:
            current_iter, futurdir, ncloth = self._prepare_cache_items(dyn_items, is_abc=False)
            tmpdir = dyn_items[0].cache_dir(0) if dyn_items else ''

            # Create directories
            for path in futurdir:
                Path(path).parent.mkdir(parents=True, exist_ok=True)

            # Clear existing caches
            cmds.waitCursor(state=1)
            self._show_status("Removing existing caches...", True)
            mu.executeInMainThreadWithResult(sim_cmds.delete_caches, ncloth)
            cmds.waitCursor(state=0)

            # Create new caches
            self._show_status("Creating caches...", True)
            caches = mu.executeInMainThreadWithResult(sim_cmds.create_cache, ncloth, tmpdir)

            # Handle metadata
            if comment := self.comments_tab.getComment():
                self._update_cache_metadata(dyn_items[0], {}, current_iter, comment=comment)

            # Attach caches
            self._show_status("Attaching caches...", True)
            self._attach_ncache(caches, futurdir, ncloth, tmpdir)

            # Refresh view
            if self.mode_selector.currentIndex() == 0:  # Cache mode
                mu.executeDeferred(self.cache_tree.build_cache_list)

            self._hide_status()

        except Exception as e:
            self._show_status(f"Error creating cache: {str(e)}", False)
            logger.error(f"Cache creation failed: {e}")
    # ====================================================================
    # CACHE ITEM PREPARATION AND ATTACHMENT HELPERS
    # ====================================================================

    def _prepare_cache_items(self, dyn_items, is_abc=True):
        """
        Prepares items for caching, including calculating cache paths and collecting meshes.

        Args:
            dyn_items (list): Selected dynamic items for caching.
            is_abc (bool): Flag to differentiate between Alembic and nCache.

        Returns:
            tuple: A tuple containing current iteration, future cache directories, and node/mesh lists.
        """
        suffix = ''
        _iter_list = sorted([str(i.get_iter() + 1) for i in dyn_items])
        current_iter = int(_iter_list[-1])

        futurdir = []
        nodes_or_meshes = []

        for i in dyn_items:
            shape = i.get_meshes() if is_abc else i.node
            nodes_or_meshes += shape if isinstance(shape, list) else [shape]

            # Determine cache mode based on iteration
            mode = current_iter - i.get_iter() if current_iter != i.get_iter() else 1
            cache_path = i.cache_file(mode, suffix)
            futurdir.append(cache_path)

        return current_iter, list(set(futurdir)), list(set(nodes_or_meshes))

    def _update_cache_metadata(self, item: QtWidgets.QTreeWidgetItem,
                               recap_dic: dict,
                               current_iter: str,
                               comment=None,
                               preset=None):
        """
        Helper to update cache metadata with comments and presets.

        Args:
            item (QtWidgets.QTreeWidgetItem): Tree item representing the cached object.
            current_iter (int): Current iteration/version of the cache.
            comment (str, optional): User-specified comment for the cache.
            preset (dict, optional): Preset data for the cache.
        """

        recap_dic = recap_dic or {'comment': {}, 'preset': {}}
        solver_name = item.solver_name

        if comment:
            recap_dic['comment'][solver_name] = {current_iter: comment}

        if preset:
            recap_dic['preset'][solver_name] = {current_iter: preset}

        json_file = item.metadata()
        json_file_path = Path(json_file)

        # Use deferred JSON save or merge based on file existence
        if json_file_path.exists():
            dw_json.merge_json(json_file, recap_dic, indent=4, defer=True)
        else:
            dw_json.save_json(json_file, recap_dic, indent=4, defer=True)

    def _attach_ncache(self, caches, futurdir, ncloth, tmpdir):
        """
        Attaches nCaches to nCloth nodes.

        Args:
            caches (list): List of cache files.
            futurdir (list): List of target cache directories.
            ncloth (list): List of nCloth nodes.
            tmpdir (str): Temporary directory for caches.
        """
        file_list = [p.name for p in Path(tmpdir).iterdir()]

        for cache_name, target_dir, ncloth_node in zip(caches, futurdir, ncloth):
            try:
                src_path = Path(tmpdir)
                cache_files = [f for f in src_path.iterdir() if f.name.startswith(cache_name)]

                for src in cache_files:
                    dst = Path(target_dir).with_suffix(src.suffix)
                    mu.executeDeferred(
                        self._move_and_attach_cache,
                        str(src), str(dst),
                        target_dir, ncloth_node
                    )

            except Exception as e:
                logger.error(f"Failed to attach cache {cache_name}: {e}")

    def _move_and_attach_cache(self, src, dst, target_dir, ncloth_node):
        """
        Moves the cache file to the target directory and attaches it to the nCloth node.

        Args:
            src (str): Path to the source file to move.
            dst (str): Destination path for the moved file.
            target_dir (str): Target directory for cache attachment.
            ncloth_node (str): The nCloth node to which the cache will be attached.
        """
        try:
            # Move the file
            shutil.move(src, dst)
            # Attach the cache to the nCloth node
            sim_cmds.attach_ncache(target_dir, ncloth_node)
            print(f"Successfully moved {src} to {dst} and attached to {ncloth_node}")
        except Exception as e:
            cmds.warning(f"Failed to move {src} to {dst} or attach to {ncloth_node}. Error: {e}")

    # ====================================================================
    # COMMENTS
    # ====================================================================

    def set_comment(self, dyn_item):
        """
        Sets the comment in the UI for the selected dynamic item, if applicable.

        Args:
            dyn_item: The dynamic item selected in the main tree view.
        """
        if not dyn_item or dyn_item.node_type not in ['zSolverTransform', 'nCloth', 'hairSystem']:
            self.comments_tab.setTitle(None)
            self.comments_tab.setComment(None)
            return

        cache_item = self.cache_tree.selected()
        if cache_item:
            metadata = dyn_item.metadata()
            metadata_path = Path(metadata)
            self.comments_tab.setTitle(dyn_item.short_name)
            if metadata_path.exists():
                # Load and set the comment if metadata exists
                data = dw_json.load_json(metadata)
                comment = data.get('comment', {}).get(dyn_item.solver_name, {}).get(cache_item.version, "")
                self.comments_tab.setComment(comment)
            else:
                # Clear comment if no cache item is selected or metadata is missing
                self.comments_tab.setComment(None)

    def save_comment(self, comment):
        """
        Saves a user-provided comment for selected cache versions of the selected item.

        Args:
            comment (str): The comment text to save.
        """
        item = self.get_selected_tree_item()
        if not item:
            cmds.warning("No item selected to save comment.")
            return

        json_metadata = item.metadata()
        json_metadata_path = Path(json_metadata)
        solver = item.solver_name
        sel_caches = self.cache_tree.cache_tree.selectedItems()

        json_recap_dic = {'comment': {}}
        if comment:
            for cache in sel_caches:
                json_recap_dic['comment'][solver] = {cache.version: comment}
                if json_metadata_path.exists():
                    dw_json.merge_json(json_metadata, json_recap_dic, defer=True)
                else:
                    dw_json.save_json(json_metadata, json_recap_dic, defer=True)

    # ====================================================================
    # CACHE AND MAP MODE TOGGLING
    # ====================================================================

    def cache_map_on_change(self):
        """
        Changes the UI mode between cache and maps based on the mode picker selection.
        """
        # Set edit mode based on current selection in the mode picker
        self.edit_mode = 'cache' if self.cb_mode_picker.currentIndex() == 0 else 'maps'
        self.cache_map_sel()  # Update the display based on the selected mode

    def cache_map_sel(self):
        """
        Updates the display to show either the cache tree or the maps tree,
        based on the current edit mode.
        """
        dyn_item = self.get_selected_tree_item()

        # Toggle visibility of cache and maps trees
        if self.edit_mode == 'cache':
            self.maps_tree.hide() # apparently there is a method setVisible(bool)
            self.cache_tree.show()
            self.cache_tree.set_node(dyn_item)
            self.set_comment(dyn_item)
        else:
            self.cache_tree.hide()
            self.maps_tree.show()
            self.maps_tree.set_node(dyn_item)

    # ====================================================================
    # SELECTION METHOD
    # ====================================================================

    def select(self):
        """
        Selects the appropriate transform or node for the current item in the dyn_eval_tree.
        """
        dyn_item = self.dyn_eval_tree.currentItem()
        if not dyn_item or not dyn_item.node:
            cmds.warning("No item selected or item has no associated node.")
            return

        # Determine the transform based on node type
        _filter = ['nRigid', 'dynamicConstraint']
        if dyn_item.node_type in _filter:
            transform = cmds.listRelatives(dyn_item.node, p=1)
        elif dyn_item.node_type == 'nCloth':
            # transform = cmds.listRelatives(item.node, p=1)
            transform = dyn_item.mesh_transform
        else:
            transform = dyn_item.node

        # Execute selection command with the determined transform
        cmds.select(transform, r=True)

    # ====================================================================
    # TREE ITEM SELECTION GUESSING
    # ====================================================================

    def guess_sel_tree_item(self, _type='nCloth', sel_input=None):
        """
        Attempts to auto-select a tree item in the UI based on a guessed selection.

        Args:
            type (str): The type of item to select ('nCloth', 'hairSystem', or 'refresh').
            sel_input: Optional input to directly set as selected if type is 'refresh'.

        Returns:
            bool: True if a matching item was found and selected, False otherwise.
        """

        selected = None
        all_items = get_all_treeitems(self.dyn_eval_tree)
        selected = self._get_selected_node(_type, sel_input)

        if selected:
            for item in all_items:
                if item.node == selected:
                    # Auto-select the matching tree item in the UI
                    self.dyn_eval_tree.setCurrentItem(item)

                    # Expand parent items to make the selection visible
                    self._expand_parents(item)
                    return True
        return False

    def _get_selected_node(self, _type, sel_input):
        """
        Determines the selected node based on the provided type and input.

        Args:
            type (str): The type of item to select ('nCloth', 'hairSystem', or 'refresh').
            sel_input: Optional input to directly set as selected if type is 'refresh'.

        Returns:
            str or None: The name of the selected node, or None if not found.
        """
        if type == 'refresh':
            return sel_input
        elif type in ['nCloth', 'hairSystem']:
            # Retrieve nucleus shape node for both 'nCloth' and 'hairSystem'
            return sim_cmds.get_nucleus_sh_from_sel()
        return None

    def _expand_parents(self, item):
        """
        Expands the parent items of the specified tree item to make it visible.

        Args:
            item: The tree item to expand parents for.
        """
        # Recursively expand parents to reveal the item in the tree view
        parent = item.parent()
        while parent:
            parent.setExpanded(True)
            parent = parent.parent()

    # ====================================================================
    # SIGNAL RECONNECTION
    # ====================================================================

    def reconnect(self, signal, newhandler=None, oldhandler=None):
        """
        Safely reconnects a signal to a new handler, optionally disconnecting a specific old handler.

        Args:
            signal (QtCore.Signal): The signal to reconnect.
            newhandler (callable, optional): The new handler function to connect to the signal.
            oldhandler (callable, optional): The specific old handler function to disconnect.
                                             If not provided, all existing connections are removed.
        """
        # Disconnect the old handler(s) safely, accounting for multiple connections
        while True:
            try:
                if oldhandler is not None:
                    # Disconnect only the specified handler, one connection at a time
                    signal.disconnect(oldhandler)
                else:
                    # Disconnect all connections if no specific old handler is provided
                    signal.disconnect()
            except TypeError:
                # Break loop when no more connections of oldhandler are found
                break

        # Connect the new handler if provided
        if newhandler is not None:
            signal.connect(newhandler)

    def _setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        self.undo_shortcut = QtWidgets.QShortcut(self)
        self.redo_shortcut = QtWidgets.QShortcut(self)

        # Connect shortcuts
        self.undo_shortcut.activated.connect(self._handle_undo)
        self.redo_shortcut.activated.connect(self._handle_redo)

        # Initial state
        self._update_shortcuts_state(False)

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


def show_ui():
    if MODE == 0:
        # Create the Qt Application
        app = QtWidgets.QApplication(sys.argv)
        # Create and show the form
        form = DynEvalUI()
        form.show()
        # Run the main Qt loop
        sys.exit(app.exec_())
    else:
        if MODE == 1:
            parent = get_maya_window()
        if MODE == 2:
            parent = get_houdini_window()

        try:
            simtoolui.deleteLater()
        except:
            pass
        simtoolui = DynEvalUI(parent)
        simtoolui.show()
        return simtoolui


# try:
#     ex.deleteLater()
# except:
#     pass
# ex = DynEvalUI()
# ex.show()

