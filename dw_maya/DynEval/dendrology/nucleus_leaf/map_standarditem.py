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
from PySide6 import QtCore, QtGui, QtWidgets


class MapItemModel(QtGui.QStandardItem):
    """Model item representing a paintable map in the tree view."""

    def __init__(self, node_name, map_attr):
        super().__init__()
        self.node_name = node_name
        self.map_name = map_attr[0]
        self.map_index = map_attr[1]

        # Set text display
        self.setText(self.map_name)
        self.setEditable(False)

        # Storing full attribute for painting
        self.setData(self.get_attr_full(), QtCore.Qt.UserRole)
        # Store the map index for display in the combobox
        self.setData(self.map_index, QtCore.Qt.UserRole + 1)

    def get_attr_full(self):
        """Constructs the full attribute path."""
        map_type = {0: '', 1: 'PerVertex', 2: 'Map'}.get(self.map_index, '')
        return f"{self.node_name}.{self.map_name}{map_type}"



class MapTypeDelegate(QtWidgets.QStyledItemDelegate):
    """Delegate for managing the combobox, label color, and painting functionality."""

    COLOR_MAP = {0: "color: rgb(175, 175, 175);", 1: "color: rgb(0, 255, 0);", 2: "color: rgb(0, 125, 255);"}

    def createEditor(self, parent, option, index):
        """Creates a combobox editor for map type selection."""
        editor = QtWidgets.QComboBox(parent)
        editor.addItems(["None", "Vertex", "Texture"])
        current_index = index.data(QtCore.Qt.UserRole + 1)
        editor.setCurrentIndex(current_index if current_index is not None else 0)
        editor.currentIndexChanged.connect(lambda idx, i=index: self.on_map_type_changed(i, idx))
        return editor

    def setEditorData(self, editor, index):
        """Sets the editor data, updating colors and initial value."""
        current_index = index.data(QtCore.Qt.UserRole + 1)
        editor.setCurrentIndex(current_index if current_index is not None else 0)

    def setModelData(self, editor, model, index):
        """Stores selected map type in model, applies coloring and sets updated values."""
        new_index = editor.currentIndex()
        model.setData(index, new_index, QtCore.Qt.UserRole + 1)  # Update the stored map type
        model.setData(index, self.COLOR_MAP[new_index], QtCore.Qt.ForegroundRole)

    def paint(self, painter, option, index):
        """Custom painting to handle color updates on text and double-click behavior."""
        painter.save()
        map_type_index = index.data(QtCore.Qt.UserRole + 1) or 0
        color = self.COLOR_MAP.get(map_type_index, "color: rgb(175, 175, 175);")
        option.font.setItalic(True)  # Optional for styling
        painter.setPen(QtGui.QColor(color))
        super().paint(painter, option, index)
        painter.restore()

    def on_map_type_changed(self, index, map_type_idx):
        """Updates the map type on change."""
        node_name = map_type_idx.data(QtCore.Qt.DisplayRole)
        map_name = map_type_idx.data(QtCore.Qt.UserRole)
        ncloth_cmds.set_vtx_map_type(node_name, f"{map_name}MapType", index)

    def editorEvent(self, event, model, option, index):
        """Handles double-click events to initiate map painting."""
        if event.type() == QtCore.QEvent.MouseButtonDblClick:
            attr_full = index.data(QtCore.Qt.UserRole)
            cloth_mesh = index.data(QtCore.Qt.UserRole + 2)  # Stored if needed for painting
            if attr_full:
                ncloth_cmds.paint_vtx_map(attr_full, cloth_mesh)
        return super().editorEvent(event, model, option, index)