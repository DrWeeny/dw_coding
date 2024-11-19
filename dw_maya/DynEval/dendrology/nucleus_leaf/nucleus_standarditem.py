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
import re

# internal
from PySide6 import QtCore, QtGui, QtWidgets
import maya.cmds as cmds

# external
from .base_standarditem import BaseSimulationItem
from pathlib import Path
from dw_maya.DynEval import sim_cmds


class NucleusStandardItem(BaseSimulationItem):
    """Item for representing nucleus nodes in the tree."""

    ICON_PATHS = {
        'nucleus': '',
        'nCloth': 'path/to/ncloth.png',
        'hairSystem': 'path/to/nhair.png',
        'nRigid': 'path/to/collider.png',
        'nConstraint': 'path/to/nconstraint.png'
    }
    COLOR_CODES = {
        'nucleus': (194, 177, 109),
        'nCloth': (224, 255, 202),
        'nRigid': (0, 150, 255),
        'hairSystem': (237, 150, 0),
        'nConstraint': ''
    }
    onIcon = QtGui.QIcon('path/to/on.png')
    offIcon = QtGui.QIcon('path/to/off.png')

    def __init__(self, node):
        super().__init__(node)
        self.setText(self.short_name)
        self.setForeground(QtGui.QBrush(self.node_color))
        self.setIcon(self.node_icon)
        self.setCheckable(True)
        self.setCheckState(QtCore.Qt.Checked if self.state else QtCore.Qt.Unchecked)

    @property
    def node_type(self):
        return cmds.nodeType(self.node)

    @property
    def node_icon(self):
        """Gets the appropriate icon based on node type."""
        icon_path = self.ICON_PATHS.get(self.node_type, "")
        return QtGui.QIcon(icon_path)

    @property
    def node_color(self):
        """Returns the color associated with the node type."""
        color_rgb = self.COLOR_CODES.get(self.node_type, (200, 200, 200))
        return QtGui.QColor(*color_rgb)

    def set_state(self, state):
        """Overrides base method to set icon based on state."""
        super().set_state(state)
        self.setIcon(self.onIcon if state else self.offIcon)
