#!/usr/bin/env python
#----------------------------------------------------------------------------#
#------------------------------------------------------------------ HEADER --#

"""
@author:
    abtidona

@description:
    this is a description

@applications:
    - groom
    - cfx
    - fur
"""

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#

# built-in
import sys, os
import re
# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from operator import itemgetter

MODE = 0

# internal
try:
    import hou
    from PySide6 import QtWidgets, QtGui, QtCore

    MODE = 2
except:
    pass

if not MODE > 0:
    try:
        import maya.cmds as cmds
        from PySide6 import QtWidgets, QtGui, QtCore
        from dw_maya.DynEval.dendrology.cache_leaf import CacheItem
        from  dw_maya.DynEval import ncloth_cmds, ziva_cmds

        import dw_maya.dw_presets_io as dw_json
        MODE = 1
    except:
        pass

# external
if MODE == 0:
    from PySide6 import QtWidgets, QtGui, QtCore


def get_all_treeitems(qtreewidget):
    """Get all QTreeWidgetItem of given QTreeWidget

    Args:
        qtreewidget(class): QTreeWidget object

    Returns:
        list: QTreeWidgetItem
    """

    items = []
    iterator = QtWidgets.QTreeWidgetItemIterator.All
    all_items = QtWidgets.QTreeWidgetItemIterator(qtreewidget,
                                                 iterator) or None
    if all_items is not None:
        while all_items.value():
            item = all_items.value()
            items.append(item)
            all_items += 1
    return items


class CacheTree(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.node = None

        # UI Setup
        self.cache_tree = QtWidgets.QTreeWidget()
        self.setup_ui()

        # Layout Setup
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addWidget(self.cache_tree)

    def setup_ui(self):
        self.cache_tree.setMinimumWidth(280)
        self.cache_tree.setMaximumWidth(280)
        self.cache_tree.setColumnCount(1)
        self.cache_tree.setColumnWidth(0, 170)
        self.cache_tree.setIndentation(0)
        self.cache_tree.setItemsExpandable(False)
        self.cache_tree.setExpandsOnDoubleClick(False)
        self.cache_tree.setHeaderLabels([""])
        self.cache_tree.header().setDefaultAlignment(QtCore.Qt.AlignCenter)
        self.cache_tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

        # Context menu setup
        self.cache_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.cache_tree.customContextMenuRequested.connect(self.context_cache)

    def selected(self):
        return self.cache_tree.currentItem()

    def select(self, item_id=0):
        if self.cache_tree.topLevelItem(item_id):
            self.cache_tree.topLevelItem(item_id).setSelected(True)

    def set_node(self, treenode):
        self.node = treenode
        self.build_cache_list()

    def add_menu_action(menu: QtWidgets.QMenu, title: str, handler: callable):
        action = QtWidgets.QAction(title, menu)
        action.triggered.connect(handler)
        menu.addAction(action)

    def context_cache(self, position: QtCore.QPoint):
        """Creates a context menu for cache items in the tree."""
        menu = QtWidgets.QMenu(self)
        add_menu_action(menu, 'Attach Cache', self.attach_selected_cache)

        node_types = [node.node_type for node in self.node]
        if 'nCloth' in node_types or 'zSolverTransform' in node_types:
            add_menu_action(menu, 'Materialize', self.materialize)

        add_menu_action(menu, 'Restore Settings', self.restore)
        menu.exec(self.cache_tree.viewport().mapToGlobal(position))

    def materialize(self):
        """Materializes the selected caches by duplicating the cloth mesh and assigning the selected cache."""
        selected_caches = self.cache_tree.selectedItems()
        if not selected_caches:
            return

        for cache_node in selected_caches:
            if self.node.node_type == 'zSolverTransform':
                ziva_cmds.materialize(cache_node.path)
            else:
                ncloth_cmds.materialize(cache_node.mesh, cache_node.path)

    def restore(self):
        dyn_item = self.node
        if isinstance(dyn_item, list):
            dyn_item = dyn_item[0]
        sel_caches = self.cache_tree.selectedItems()

        if not sel_caches:
            return

        for cache_item in sel_caches:
            name = cache_item.text(0)
            p = re.compile('v([0-9]{3})')
            _iter = str(int(p.search(name).group(0)[1:]))
            solver = dyn_item.solver_name
            metadata = dyn_item.metadata()

            if os.path.isfile(metadata):
                print('try loading {} - {}'.format(solver, _iter))
                data = dw_json.loadJson(metadata)
                if not solver in data['preset']:
                    return
                if not _iter in data['preset'][solver]:
                    return
                preset = data['preset'][solver][_iter]
                ziva_cmds.load_preset(solver,
                                      preset=preset,
                                      blend=1)
                print('loaded : {} - {}'.format(solver, _iter))

    def attach_selected_cache(self):

        sel_caches = self.cache_tree.selectedItems()
        for cache_node in sel_caches:

            _type = cache_node.cache_type

            if _type == 'nCloth':
                cmds.waitCursor(state=1)
                ncloth_cmds.delete_caches(cache_node.node)
                cmds.waitCursor(state=0)
                ncloth_cmds.attach_ncache(cache_node.path, cache_node.node)

            if _type == 'alembic':
                # attach cache for ziva
                for dyn_item in self.node:
                    suffix = ''
                    abc = dyn_item.alembic_target() + '.filename'
                    cmds.setAttr(abc,
                                 cache_node.cache_file(0, suffix),
                                 type='string')

            for item in get_all_treeitems(self.cache_tree):
                if item.is_attached:
                    item.set_color()
            cache_node.set_attached()

    def detach_selected_cache(self):
        sel_caches = self.cache_tree.selectedItems()
        for cache_node in sel_caches:
            _type = cache_node.cache_type
            if _type == 'nCloth':
                cmds.waitCursor(state=1)
                ncloth_cmds.delete_caches(cache_node.node)
                cmds.waitCursor(state=0)
            cache_node.set_color()

    def build_cache_list(self):
        """Builds the cache list based on the provided simulation node."""
        self.cache_tree.clear()
        caches_tree = []

        for dyn_item in self.node:
            if dyn_item.node_type in ['nCloth', 'hairSystem']:
                cache_items = self._build_cache_items(dyn_item, 'nCache', 'xml')
            elif dyn_item.node_type == 'zSolverTransform':
                cache_items = self._build_cache_items(dyn_item, 'alembic', 'abc')
            else:
                continue

            caches_tree.extend(cache_items)
            self.cache_tree.setHeaderLabels([str(dyn_item.short_name)])

        self._populate_cache_tree(caches_tree)

    def _build_cache_items(self, dyn_item, cache_type: str, file_extension: str) -> list:
        """Helper function to build cache items for a given dynamic item."""
        caches = dyn_item.get_cache_list()
        cachedir = dyn_item.cache_dir()
        json_metadata = dyn_item.metadata()
        node = dyn_item.node
        cache_items = []

        if caches:
            for cache_name in caches:
                isvalid, attach = self._cache_metadata(json_metadata, cache_name, dyn_item, file_extension)
                cache_path = os.path.join(cachedir, f"{cache_name}.{file_extension}")
                cache_item = CacheItem(name=cache_name, cache_node=node, path=cache_path, isvalid=isvalid,
                                       attached=attach, _type=cache_type)
                cache_item.setText(0, cache_name)
                cache_items.append(cache_item)

        return cache_items

    def _cache_metadata(self, json_metadata: str, cache_name: str, dyn_item, file_extension: str) -> tuple:
        """Retrieve cache validity and attachment status from metadata."""
        isvalid = False
        attach = False

        if os.path.isfile(json_metadata):
            data = dw_json.loadJson(json_metadata)
            isvalid = 'isvalid' in data and cache_name in data['isvalid']

        if dyn_item.node_type == 'nCloth':
            attach = ncloth_cmds.cache_is_attached(dyn_item.node, cache_name)
        elif dyn_item.node_type == 'zSolverTransform':
            attach = ziva_cmds.cache_is_attached(dyn_item.alembic_target(), cache_name)

        return isvalid, attach


    def _populate_cache_tree(self, caches_tree: list):
        """Sorts and populates cache items into the QTreeWidget."""

        # Get the version information for sorting, assuming the version is encoded as 'v###'
        sorted_caches = sorted(caches_tree, key=lambda item: item.version, reverse=True)

        # Add sorted items to the cache tree
        self.cache_tree.addTopLevelItems(sorted_caches)
