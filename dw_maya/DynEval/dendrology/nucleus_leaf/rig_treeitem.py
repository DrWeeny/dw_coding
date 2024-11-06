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
from . import ncloth_cmds


# internal
from PySide6 import QtCore, QtGui, QtWidget
import maya.cmds as cmds

# external

#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#


class CharacterData:
    """
    Container for character information.
    """

    def __init__(self, name, node_type=None):
        self.name = name
        self.node_type = node_type
        self.short_name = self.get_short_name()
        self.character_name = name

    def get_short_name(self):
        """Return a short version of the name for cleaner display."""
        return self.name.split('|')[-1].split(':')[-1] if '|' in self.name else self.name


class CharacterTreeItem(QtWidgets.QTreeWidgetItem):
    """
    Represents a character in the tree. This item is a container for character data.
    """

    def __init__(self, character_data: CharacterData, parent=None):
        super().__init__(parent)

        self.character_data = character_data
        self.setText(0, self.character_data.short_name)

        # Set a bold font for the character name
        font = QtGui.QFont()
        font.setBold(True)
        self.setFont(0, font)

    @property
    def name(self):
        return self.character_data.name

    @property
    def character_name(self):
        return self.character_data.character_name

    @property
    def node_type(self):
        return self.character_data.node_type
