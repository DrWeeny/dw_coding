import re

# internal

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt, Signal, Slot
    from shiboken6 import wrapInstance
except ImportError:
    # Fallback for older Maya versions shipping PySide2
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Qt, Signal, Slot
    from shiboken2 import wrapInstance

import maya.cmds as cmds

# external
from .base_standarditem import BaseSimulationItem
from dw_logger import get_logger

logger = get_logger()


class HairTreeItem(BaseSimulationItem):
    """Item class for hair simulation nodes."""

    def __init__(self, name):
        super().__init__(name)
        self.setText(self.display_name)
        self.setIcon(QtGui.QIcon("path/to/hair_icon.png"))

        self._setup_item()

    @property
    def mesh_transform(self):
        """Transform that owns the hairSystem shape, or None if unresolved."""
        try:
            parent = cmds.listRelatives(self.node, p=True, f=True)
            return parent[0] if parent else None
        except Exception as e:
            logger.warning(f"mesh_transform lookup failed for {self.node!r}: {e}")
            return None

    @property
    def short_name(self):
        """A simplified name for the node, avoiding namespace clutter."""
        return self.node.split('|')[-1].split(':')[-1]

    @property
    def state_attr(self):
        """Returns the attribute used to toggle hair simulation."""
        return 'simulationMethod'


