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
from PySide6.QtGui import QStandardItem
import maya.cmds as cmds
from pathlib import Path

# external
import dw_maya_utils as dwu

#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#

class BaseSimulationItem(QtGui.QStandardItem):
    """Base item class for simulation nodes."""

    def __init__(self, name):
        super().__init__(name)
        self.node = name
        self.namespace = self.get_ns(name)
        self.solver_name = self.get_solver(name)
        self.setEditable(False)

        # Model data properties
        self.setData(name, QtCore.Qt.DisplayRole)
        self.setData(self.solver_name, QtCore.Qt.UserRole + 1)
        self.setData(self.namespace, QtCore.Qt.UserRole + 2)

    def get_ns(self, node_name):
        """Retrieve namespace from node."""
        return node_name.split(':')[0] if ':' in node_name else ''

    def get_solver(self, node_name):
        """Find connected solver."""
        connections = cmds.listConnections(node_name, type="nucleus")
        return connections[0].split(':')[-1] if connections else ''

    @property
    def state(self):
        return cmds.getAttr(f"{self.node}.{self.state_attr}")

    def set_state(self, state):
        cmds.setAttr(f"{self.node}.{self.state_attr}", state)

    @property
    def short_name(self):
        return self.node.split('|')[-1].split(':')[-1].split('_Sim')[0]

    @property
    def state_attr(self):
        """Derived classes should define specific attributes to track the node's state."""
        return 'enable'

    def toggle_state(self):
        """Toggles the node's state between enabled and disabled."""
        self.set_state(not self.state)
