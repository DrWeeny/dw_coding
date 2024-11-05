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
# ----- Edit sysPath -----#
import re

rdPath = '/user_data/AMJB/coding/dw_tools/maya/DNEG2'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

from operator import itemgetter

MODE = 0

# internal
try:
    import hou
    from PySide2 import QtWidgets, QtGui, QtCore

    MODE = 2
except:
    pass

if not MODE > 0:
    try:
        import maya.cmds as cmds
        from PySide2 import QtWidgets, QtGui, QtCore
        from SimTool.dendrology.cache_leaf import CacheItem
        from SimTool import ncloth_cmds, ziva_cmds

        import dw_json
        MODE = 1
    except:
        pass

# external
if MODE == 0:
    from PySide2 import QtWidgets, QtCore, QtGui


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
        super(CacheTree, self).__init__(parent)

        self.node = None

        _vl_main = QtWidgets.QVBoxLayout()

        self.cache_tree = QtWidgets.QTreeWidget()
        self.cache_tree.setMinimumWidth(280)
        self.cache_tree.setMaximumWidth(280)
        self.cache_tree.setColumnCount(1)
        self.cache_tree.setColumnWidth(0, 170)
        self.cache_tree.setIndentation(0)
        self.cache_tree.setItemsExpandable(False)
        self.cache_tree.setExpandsOnDoubleClick(False)
        self.cache_tree.setHeaderLabels([""])
        self.cache_tree.header().setDefaultAlignment(QtCore.Qt.AlignCenter)
        sel_mode = QtWidgets.QAbstractItemView.ExtendedSelection
        self.cache_tree.setSelectionMode(sel_mode)


        # Create a contextual menu
        self.cache_tree.installEventFilter(self)
        self.cache_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.cache_tree.customContextMenuRequested.connect(self.context_cache)

        _vl_main.addWidget(self.cache_tree)
        self.setLayout(_vl_main)

    def selected(self):
        return self.cache_tree.currentItem()

    def select(self, item_id=0):
        if self.cache_tree.topLevelItem(item_id):
            self.cache_tree.topLevelItem(item_id).setSelected(True)

    def set_node(self, treenode):
        self.node = treenode
        self.build_cache_list()

    def context_cache(self, position):
        """
        Contextual menu, for all the items:
        Args:
            position (QPos): position of the item in screen
        """
        menu = QtWidgets.QMenu(self)

        # Attach Cache
        act_attach = QtWidgets.QAction(self)
        act_attach.setText('attach cache')
        menu.addAction(act_attach)
        act_attach.triggered.connect(self.attach_selected_cache)

        # Materizlise the Cache
        _node_types = [node.node_type for node in self.node]
        if 'nCloth' in _node_types or 'zSolverTransform' in _node_types:
            act_materialize = QtWidgets.QAction(self)
            act_materialize.setText('materialize')
            menu.addAction(act_materialize)
            act_materialize.triggered.connect(self.materialize)

        # Restore Settings
        act_restore = QtWidgets.QAction(self)
        act_restore.setText('restore settings')
        menu.addAction(act_restore)
        act_restore.triggered.connect(self.restore)

        menu.exec_(self.cache_tree.viewport().mapToGlobal(position))

    def materialize(self):
        """
        for cloth mesh, it make a duplicate and assign selected cache
        Returns:

        """
        sel_caches = self.cache_tree.selectedItems()
        if self.node.node_type == 'zSolverTransform':
            ziva_cmds.materialize(sel_caches[0].path)
            return
        else:
            for cache_node in sel_caches:
                out = ncloth_cmds.materialize(cache_node.mesh,
                                              cache_node.path)

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

        # BUILD CACHE LIST
        self.cache_tree.clear()
        # For top level
        caches_tree = []
        # get cloth node selected
        # self.dyn_eval_tree.selectedItems()
        # TODO : hasattr(a, 'property')
        #  ----- a.property
        for dyn_item in self.node:

            if dyn_item.node_type in ['nCloth', 'hairSystem']:
                caches = dyn_item.get_cache_list()
                cachedir = dyn_item.cache_dir()
                json_metadata = dyn_item.metadata()
                if 'cacheType' in json_metadata:
                    cache_type = json_metadata['cacheType']
                else:
                    cache_type = 'nCache'
                node = dyn_item.node
                if caches:
                    for i in caches:
                        isvalid = False
                        if os.path.isfile(json_metadata):
                            data = dw_json.loadJson(json_metadata)
                            isvalid = False
                            if 'isvalid' in data:
                                if i in data['isvalid']:
                                    isvalid = True

                        attach = ncloth_cmds.cache_is_attached(dyn_item.node, i)
                        xml = cachedir + i + '.xml'

                        cache_item = CacheItem(name=i, cache_node=node,
                                              path=xml, isvalid=isvalid,
                                              attached=attach, _type=cache_type)
                        cache_item.setText(0, i)
                        caches_tree.append(cache_item)

                self.cache_tree.setHeaderLabels([str(dyn_item.short_name)])

            elif dyn_item.node_type == 'zSolverTransform':
                caches = dyn_item.get_cache_list()
                cachedir = dyn_item.cache_dir()
                json_metadata = dyn_item.metadata()
                if 'cacheType' in json_metadata:
                    cache_type = json_metadata['cacheType']
                else:
                    cache_type = 'alembic'

                node = dyn_item.node
                if caches:
                    for i in caches:
                        isvalid = False
                        if os.path.isfile(json_metadata):
                            data = dw_json.loadJson(json_metadata)
                            isvalid = False
                            if 'isvalid' in data:
                                if i in data['isvalid']:
                                    isvalid = True

                        targ = dyn_item.alembic_target()
                        attach = ziva_cmds.cache_is_attached(targ, i)
                        abc = cachedir + i + '.abc'

                        cache_item = CacheItem(name=i, cache_node=node,
                                              path=abc, isvalid=isvalid,
                                              attached=attach, _type=cache_type)
                        cache_item.setText(0, i)
                        caches_tree.append(cache_item)

                self.cache_tree.setHeaderLabels([str(dyn_item.short_name)])

        else:
            self.cache_tree.setHeaderLabels([""])

        id_list = []
        for cache in caches_tree:
            id = cache.version
            id_list.append(id)

        caches_ordered = [i[0] for i in
                         sorted(zip(caches_tree, id_list), key=itemgetter(1),
                                reverse=True)]

        self.cache_tree.addTopLevelItems(caches_ordered)
