import re

# internal
from PySide6 import QtCore, QtGui
import maya.cmds as cmds

# external
from .base_standarditem import BaseSimulationItem


class HairTreeItem(BaseSimulationItem):
    """Item class for hair simulation nodes."""

    def __init__(self, name):
        super().__init__(name)
        self.setText(self.short_name)
        self.setIcon(QtGui.QIcon("path/to/hair_icon.png"))

        self._setup_item()

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


