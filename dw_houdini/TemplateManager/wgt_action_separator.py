"""
Module providing custom separator actions for use in Qt-based UIs.

This module defines a custom widget action `ActionTextSeparator`, which can be used to create
a separator with custom text, typically to be used in a toolbar or menu.

Classes:
- ActionTextSeparator: A custom action that displays a separator with customizable text.

Usage:
- This custom widget action can be added to a Qt widget's action list, such as in a menu or toolbar.
"""

from PySide2 import QtCore, QtGui, QtWidgets
from typing import Optional

class ActionTextSeparator(QtWidgets.QWidgetAction):
    """
    Args:
        text (str): The text that will appear as part of the separator.
        parent (Optional[QtWidgets.QWidget], optional): The parent widget of the action. Defaults to None.
    """
    def __init__(self, text, parent=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)  # Pass the parent widget

        # Create a QLabel to act as the separator
        label = QtWidgets.QLabel(f"「{text}」")
        label.setStyleSheet("background-color: #2f2f2f; color: white; height: 25px; font-size: 18px;")
        label.setAlignment(QtCore.Qt.AlignCenter)

        label.setFixedHeight(25)  # Set a fixed height for the line separator
        label.setMargin(0)  # Optional: Reduce margins if needed

        # Set the created QLabel as the default widget for this action
        self.setDefaultWidget(label)