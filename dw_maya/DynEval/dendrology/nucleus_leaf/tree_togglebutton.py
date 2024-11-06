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

#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#


class ToggleButtonDelegate(QtWidgets.QStyledItemDelegate):
    """Delegate for rendering an on/off button for dynamic state in the view."""

    toggled = QtCore.Signal(QtCore.QModelIndex, bool)  # Signal to notify toggle changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_icon = QtGui.QIcon("path/to/on_icon.png")  # Path to on icon
        self.off_icon = QtGui.QIcon("path/to/off_icon.png")  # Path to off icon

    def paint(self, painter, option, index):
        # Set up the button's rect (aligned to the right of the cell)
        button_rect = option.rect.adjusted(option.rect.width() - 24, 4, -4, -4)

        # Retrieve the button state from the model data
        is_on = index.data(QtCore.Qt.UserRole + 3)

        # Choose the icon based on the state
        icon = self.on_icon if is_on else self.off_icon
        icon.paint(painter, button_rect, QtCore.Qt.AlignCenter)

    def editorEvent(self, event, model, option, index):
        """Handle the toggle state when clicking on the icon."""
        if event.type() == QtCore.QEvent.MouseButtonRelease:
            # Calculate button rect and check if click is inside
            button_rect = option.rect.adjusted(option.rect.width() - 24, 4, -4, -4)
            if button_rect.contains(event.pos()):
                # Toggle the state
                is_on = index.data(QtCore.Qt.UserRole + 3)
                model.setData(index, not is_on, QtCore.Qt.UserRole + 3)
                # Emit signal for external handling if needed
                self.toggled.emit(index, not is_on)
                return True
        return False
