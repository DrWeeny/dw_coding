import sys
from typing import List, Any

from PySide6.QtGui import QStandardItem

import shutil
from PySide6 import QtWidgets, QtGui, QtCore  # Use PySide6 for Maya compatibility with Python 3
from pathlib import Path
import maya.utils as mu
import mmap

# External module imports (always required)
import dw_maya.dw_presets_io as dw_json

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
    from .sim_widget import CacheTree, CommentEditor, MapTree, TreeViewWithToggle
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
        super(DynEvalUI, self).__init__(parent)
        self.setGeometry(867, 546, 900, 400)
        self.setWindowTitle('UI for Dynamic Systems')
        self.edit_mode = 'cache'
        self.cache_mode = 'override' or 'increment'

        self.central_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.central_widget)

        self.init_ui()


    def init_ui(self):

        """
        There is a tree node representing the solver
        A middle widget with maps, cache list or deformer stack
        A third widget with all the tabs and tools

        Returns:

        """
        main_layout = QtWidgets.QHBoxLayout()

        # Set up the main tree model
        self.dyn_eval_tree = TreeViewWithToggle()
        self.dyn_eval_tree.tree_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

        # Create a contextual menu
        self.dyn_eval_tree.installEventFilter(self)
        self.dyn_eval_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.dyn_eval_tree.customContextMenuRequested.connect(self.context_main)


        # Set up the cache and maps area
        self.cb_mode_picker = QtWidgets.QComboBox()
        # todo : deformer list
        self.cb_mode_picker.addItems(["Cache List", "Map List"])
        self.cache_tree = CacheTree()
        self.maps_tree = MapTree()
        self.maps_tree.hide()

        # Layout for Cache/Map
        vl_cachemap = QtWidgets.QVBoxLayout()
        vl_cachemap.addWidget(self.cb_mode_picker)
        vl_cachemap.addWidget(self.cache_tree)
        vl_cachemap.addWidget(self.maps_tree)
        vl_cachemap.setStretch(0)

        # Tab setup
        self.tabs = QtWidgets.QTabWidget()
        self.tab1_comment = CommentEditor()
        self.tabs.addTab(self.tab1_comment, "comments")
        # TODO : add other tabs: paint presets attributes wedging sim rig utils
        self.tabs.resize(200, 500)


        # Add layouts to main layout
        main_layout.addWidget(self.dyn_eval_tree)
        main_layout.addLayout(vl_cachemap)
        main_layout.addWidget(self.tabs)

        # Connections
        self.cb_mode_picker.currentIndexChanged.connect(self.cache_map_on_change)
        self.dyn_eval_tree.tree_view.selectionModel().selectionChanged.connect(self.cache_map_sel)
        self.tab1_comment.save.connect(self.save_comment)
        # Handle toggle actions with itemChanged signal
        self.dyn_eval_tree.model.itemChanged.connect(self.on_toggle)

        self.build_tree()


    # ====================================================================
    # TREE BUILDING METHODS
    # ====================================================================
    def build_tree(self):
        """
        Populates the model with items representing nucleus-based and Ziva elements.
        Clears the current model contents before rebuilding.
        """
        # Clear existing items to rebuild the tree
        self.dyn_eval_tree.model.clear()

        # Populate nucleus and ziva trees separately
        self._build_nucleus_tree()
        self._build_ziva_tree()

    def _build_nucleus_tree(self):
        """
        Helper to populate the tree with nucleus-based elements.
        This includes characters, solvers, and dynamic elements like nCloth and nHair.
        """
        # Retrieve the system hierarchy for nucleus items
        system_hierarchy = sim_cmds.dw_get_hierarchy()

        # Loop through each character to build the tree
        for character, solvers in system_hierarchy.items():
            char_item = CharacterTreeItem(character)  # Create the character item

            # Sort solvers and loop through each one, attaching dynamic elements
            for solver in sim_cmds.sort_list_by_outliner(solvers):
                solver_item = NucleusStandardItem(solver)
                char_item.appendRow(solver_item)
                elements = solvers[solver]

                # Populate cloth, hair, and rigid items
                self._populate_elements(elements, solver_item)

            # Add the character item to the main model
            self.dyn_eval_tree.model.appendRow(char_item)

    def _build_ziva_tree(self):
        """
        Helper to populate the tree with Ziva simulation elements.
        This includes characters, muscles, and skin nodes.
        """
        # Retrieve the Ziva system hierarchy
        ziva_hierarchy = ziva_cmds.ziva_sys()

        # Loop through each character to build Ziva-related elements
        for character, node_types in ziva_hierarchy.items():
            char_item = CharacterTreeItem(character)

            # Populate muscles and skins under the character item
            self._populate_items(node_types.get('muscle', []), FasciaTreeItem, char_item)
            self._populate_items(node_types.get('skin', []), SkinTreeItem, char_item)

            # Add the character item to the main model
            self.dyn_eval_model.appendRow(char_item)

    def _populate_elements(self, elements, parent_item):
        """
        Populates dynamic elements such as nCloth, hairSystem, and nRigid under a parent item.

        Args:
            elements (dict): Dictionary with element types as keys (e.g., 'nCloth') and nodes as values.
            parent_item (QtGui.QStandardItem): The parent tree item to attach elements to.
        """
        # Populate each element type
        self._populate_items(elements.get('nCloth', []), ClothTreeItem, parent_item)
        self._populate_items(elements.get('hairSystem', []), HairTreeItem, parent_item)
        self._populate_items(elements.get('nRigid', []), NRigidTreeItem, parent_item)

    def _populate_items(self, nodes, item_class, parent_item):
        """
        Helper function to populate items of a specific type under a given parent item.

        Args:
            nodes (list): List of node names to add as items.
            item_class (type): The class used to create items (e.g., ClothTreeItem).
            parent_item (QtGui.QStandardItem): The parent item to append nodes to.
        """
        # Sort and add each node to the parent item
        for node in sim_cmds.sort_list_by_outliner(nodes):
            item = item_class(node)
            parent_item.appendRow(item)

    # ====================================================================
    # SELECTION HELPERS
    # ====================================================================

    def get_selected_tree_item(self,
                               multiple_selection=False) -> list[Any]:
        """Get the first selected item in the QTreeView.

        Returns:
            QtGui.QStandardItem: The first selected item, if any.
        """
        indexes = self.dyn_eval_tree.tree_view.selectionModel().selectedRows()
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

    def context_main(self, position):

        '''
        Contextual menu, for all the items in the main tree :
        # Refresh
        # Create Cache : nCache, Abc, Geometry
        # Advanced Option for Cache : cacheable attributes, sim rate, x
        # Save Preset
        # Restore Preset
        # Show nRigid show NConstraint
        # Find Documentation by Characters
        # smart activation
        # select Rest Mesh select Input Mesh

        :param position: <<QPos>>
        '''

        items = self.dyn_eval_tree.selectedItems()
        menu = QtWidgets.QMenu(self)

        # Open Documentation
        docu = QtWidgets.QMenu('documentation', self)
        char = QtWidgets.QAction(self)
        char.setText('Character PlaceHolder')
        docu.addAction(char)
        menu.addMenu(docu)

        # Contextual Menu depending of selection
        if not items:
            menu.exec_(self.dyn_eval_tree.tree_view.viewport().mapToGlobal(position))
            return

        # see what type of Item we had : nCloth, Nucleus, nHairSystem, Ziva...
        # Check if items are all of the same type
        unique_types = {i.node_type for i in items}
        if len(unique_types) == 1:
            node_type = unique_types.pop() # Get the single unique node type
            self._context_add_cache_options(menu, node_type)

        menu.exec_(self.dyn_eval_tree.tree_view.viewport().mapToGlobal(position))

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
        """
        Creates an Alembic cache for selected items and updates metadata.
        This function supports multiple selections, typically for muscle and skin elements.
        """
        dyn_items = self.dyn_eval_tree.selectedItems()
        if not dyn_items:
            cmds.warning("No items selected for Alembic caching.")
            return
        current_iter, futurdir, meshes = self._prepare_cache_items(dyn_items)

        # even if an abc cache of one item, it should have only one abc
        # we support multiple selection if we cache muscle + skin
        print(futurdir)
        caches = ziva_cmds.create_cache(futurdir[0], meshes)
        if len(futurdir) > 1:
            for file in futurdir:
                copy_files_safely(caches, file)

        # ===============================================================
        # Comment + preset:
        comment = self.tab1_comment.getComment() or None
        preset = ziva_cmds.get_preset(dyn_items[0].solver_name) if self.save_preset else None
        if comment or preset:
            self._update_cache_metadata(dyn_items[0],
                                        {},
                                        current_iter,
                                        comment=comment,
                                        preset=preset)

        # ===============================================================
        # attach cache
        for i in dyn_items:
            abc = i.alembic_target() + '.filename'
            cmds.setAttr(abc, i.cache_file(0, suffix=""), type='string')

        # ===============================================================
        if self.edit_mode == 'cache':
            mu.executeDeferred(self.cache_tree.build_cache_list)


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

        current_iter, futurdir, ncloth = self._prepare_cache_items(dyn_items, is_abc=False)
        tmpdir = dyn_items[0].cache_dir(0) if dyn_items else ''

        # Ensure target directories exist
        for path in futurdir:
            Path(path).parent.mkdir(parents=True, exist_ok=True)

        # Delete existing caches and create new ones
        cmds.waitCursor(state=1)
        sim_cmds.delete_caches(ncloth)
        cmds.waitCursor(state=0)
        caches = sim_cmds.create_cache(ncloth, tmpdir)

        # ===============================================================
        # Update metadata with comments and presets if applicable
        comment = self.tab1_comment.getComment() or None
        preset = None  # Add logic to set preset if needed
        if comment or preset:
            self._update_cache_metadata(dyn_items[0], {}, current_iter, comment=comment, preset=preset)

        # Attach cache to nCloth nodes
        self._attach_ncache(caches, futurdir, ncloth, tmpdir)

        # Refresh cache list in edit mode
        if self.edit_mode == 'cache':
            mu.executeDeferred(self.cache_tree.build_cache_list)

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
            # Collect cache files to be moved
            cache_files = [f for f in file_list if f.startswith(cache_name)]
            for file_name in cache_files:
                src = Path(tmpdir) / file_name
                extension = src.suffix.lstrip('.')
                dst = Path(target_dir).with_suffix(f'.{extension}')

                # Defer both moving and attaching in a single operation
                mu.executeDeferred(self._move_and_attach_cache, str(src), str(dst), target_dir, ncloth_node)

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
            self.tab1_comment.setTitle(None)
            self.tab1_comment.setComment(None)
            return

        cache_item = self.cache_tree.selected()
        if cache_item:
            metadata = dyn_item.metadata()
            metadata_path = Path(metadata)
            self.tab1_comment.setTitle(dyn_item.short_name)
            if metadata_path.exists():
                # Load and set the comment if metadata exists
                data = dw_json.load_json(metadata)
                comment = data.get('comment', {}).get(dyn_item.solver_name, {}).get(cache_item.version, "")
                self.tab1_comment.setComment(comment)
            else:
                # Clear comment if no cache item is selected or metadata is missing
                self.tab1_comment.setComment(None)

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
        all_items = get_all_treeitems(self.dyn_eval_tree.tree_view)
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

