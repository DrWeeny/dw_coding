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
rdPath = '/user_data/AMJB/coding/dw_tools/maya/DNEG2'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

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
        from SimTool.dendrology.nucleus_leaf import MapItem
        from SimTool import ncloth_cmds
        MODE = 1
    except:
        pass
# external
if MODE == 0:
    from PySide2 import QtWidgets, QtCore, QtGui

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

class MapTree(QtWidgets.QWidget):

    def __init__(self,
                 parent=None):
        super(MapTree, self).__init__(parent)

        self.node = None

        _vl_main = QtWidgets.QVBoxLayout()

        self.maps_tree = QtWidgets.QTreeWidget()
        self.maps_tree.setMinimumWidth(280)
        self.maps_tree.setMaximumWidth(280)
        self.maps_tree.setColumnCount(1)
        self.maps_tree.setColumnWidth(0, 170)
        self.maps_tree.setIndentation(0)
        self.maps_tree.setItemsExpandable(False)
        self.maps_tree.setExpandsOnDoubleClick(False)
        self.maps_tree.setHeaderLabels([""])
        self.maps_tree.header().setDefaultAlignment(QtCore.Qt.AlignCenter)

        self.maps_tree.itemDoubleClicked.connect(self.paint_map)

        _vl_main.addWidget(self.maps_tree)
        self.setLayout(_vl_main)

    def set_node(self, treenode):
        if self.node:
            self._type = self.node.node_type
        self.node = treenode
        self.build_map_list(self.node)

    def build_map_list(self, dyn_item):
        self.maps_tree.clear()
        # For top level
        map_items = []
        # get cloth node selected
        if dyn_item.node_type in ['nCloth', 'nRigid']:
            vtx_maps = zip(dyn_item.get_maps(),
                           dyn_item.get_maps_mode())
            for map_type in vtx_maps:
                new_item = MapItem(dyn_item.node,
                                   map_type,
                                   self.maps_tree)
                new_item.cloth_mesh = dyn_item.mesh_transform
                map_items.append(new_item)
            self.maps_tree.addTopLevelItems(map_items)
            self.maps_tree.setHeaderLabels([str(dyn_item.short_name)])
        else:
            self.maps_tree.setHeaderLabels([""])

    def paint_map(self):
        """
        trigger the maya paint tool on selected cloth mesh
        (will keep component if some are selected)
        """
        map_item = self.maps_tree.currentItem()
        if self.node.node_type in ['nCloth', 'nRigid']:
            ncloth_cmds.paint_vtx_map(map_item.map_to_paint,
                                      map_item.cloth_mesh,
                                      self.node.solver_name)
