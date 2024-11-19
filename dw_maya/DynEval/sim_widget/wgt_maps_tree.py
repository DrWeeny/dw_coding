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
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
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
        from PySide6 import QtWidgets, QtGui, QtCore
        from dw_maya.DynEval.dendrology.nucleus_leaf import MapItem
        from dw_maya.DynEval import sim_cmds
        MODE = 1
    except:
        pass
# external
if MODE == 0:
    from PySide6 import QtWidgets, QtCore, QtGui

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

class MapTree(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.node = None

        # Main layout and map tree setup
        main_layout = QtWidgets.QVBoxLayout(self)
        self.maps_tree = QtWidgets.QTreeWidget()
        self.maps_tree.setMinimumWidth(280)
        self.maps_tree.setMaximumWidth(280)
        self.maps_tree.setColumnCount(1)
        self.maps_tree.setIndentation(0)
        self.maps_tree.setItemsExpandable(False)
        self.maps_tree.setExpandsOnDoubleClick(False)
        self.maps_tree.setHeaderLabels([""])
        self.maps_tree.header().setDefaultAlignment(QtCore.Qt.AlignCenter)

        # Connect double-click to painting action
        self.maps_tree.itemDoubleClicked.connect(self.paint_map)

        main_layout.addWidget(self.maps_tree)

    def set_node(self, treenode):
        self.node = treenode
        self.build_map_list()

    def build_map_list(self):
        """Builds the list of vertex maps for the current node, if available."""
        self.maps_tree.clear()

        # Validate node and map information before building list
        if not (self.node and self.node.node_type in ['nCloth', 'nRigid']):
            self.maps_tree.setHeaderLabels([""])
            return

        # Gather maps and modes, and create MapItems
        map_items = []
        for map_name, map_mode in zip(self.node.get_maps(), self.node.get_maps_mode()):
            map_item = MapItem(self.node.node, (map_name, map_mode), self.maps_tree)
            map_item.cloth_mesh = self.node.mesh_transform
            map_items.append(map_item)

        # Populate tree and set header to node's short name
        self.maps_tree.addTopLevelItems(map_items)
        self.maps_tree.setHeaderLabels([self.node.short_name])

    def paint_map(self):
        """Activates Maya's paint tool on the selected cloth mesh's vertex map."""
        map_item = self.maps_tree.currentItem()
        if map_item and self.node and self.node.node_type in ['nCloth', 'nRigid']:
            sim_cmds.paint_vtx_map(map_item.map_to_paint, map_item.cloth_mesh, self.node.solver_name)
