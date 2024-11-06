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
from PySide6 import QtCore, QtGui, QtWidget
import maya.cmds as cmds

# external
from .base_standarditem import BaseSimulationItem


class HairTreeItem(BaseSimulationItem):
    """Item class for hair simulation nodes."""

    def __init__(self, name):
        super().__init__(name)
        self.setText(self.short_name)
        self.setIcon(QtGui.QIcon("path/to/hair_icon.png"))

        # Set initial state for the button, specific to hair (simulationMethod attribute)
        self.setData(self.state, QtCore.Qt.UserRole + 3)  # Toggle state data


    @property
    def mesh_transform(self):
        """Returns the transform of the hair node's mesh."""
        parent = cmds.listRelatives(self.node, p=True, f=True)
        return parent[0] if parent else None

    @property
    def short_name(self):
        """A simplified name for the node, avoiding namespace clutter."""
        return self.node.split('|')[-1].split(':')[-1]

    @property
    def state_attr(self):
        """Returns the attribute used to toggle hair simulation."""
        return 'simulationMethod'

    @property
    def state(self):
        """Current state of the simulation (0 = Off, 1 = Static, 2+ = Dynamic)."""
        return cmds.getAttr(f"{self.node}.{self.state_attr}")

    def set_state(self, state):
        """Set the simulation state for hair."""
        cmds.setAttr(f"{self.node}.{self.state_attr}", state)
        self.setData(state, QtCore.Qt.UserRole + 3)  # Update model data for delegate use

