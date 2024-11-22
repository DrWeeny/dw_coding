
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

    def __init__(self, node):
        super().__init__(node)
        self.setText(self.short_name)
        self._setup_item()


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
