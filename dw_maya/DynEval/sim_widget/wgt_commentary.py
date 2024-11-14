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

# internal
import sys
import os
from pathlib import Path
from PySide6 import QtWidgets, QtCore, QtGui
# external

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

class CommentEditor(QtWidgets.QWidget):
    save_requested = QtCore.Signal(str)  # Renamed for clarity

    def __init__(self, title=None, size=(400, 40), parent=None):
        super().__init__(parent)

        # Main layout
        main_layout = QtWidgets.QVBoxLayout(self)

        # Comment Title
        self.comment_title = CommentTitle(title, size)

        # Display Area
        self.display_area = QtWidgets.QTextEdit(readOnly=True)
        self.display_area.setPlaceholderText("Display comment area")
        self.display_area.setStyleSheet("font-weight: bold;")

        # Separator
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Sunken)

        # Write Area
        self.write_area = QtWidgets.QTextEdit()
        self.write_area.setPlaceholderText("Write a comment")
        self.write_area.installEventFilter(self)
        self.write_area.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.write_area.customContextMenuRequested.connect(self.show_context_menu)

        # Add widgets to layout
        main_layout.addWidget(self.comment_title)
        main_layout.addWidget(self.display_area)
        main_layout.addWidget(separator)
        main_layout.addWidget(self.write_area)
        self.setLayout(main_layout)

    def setComment(self, text=None):
        self.display_area.setText(text if text else "")

    def getComment(self):
        return self.write_area.toPlainText()

    def setTitle(self, title=None):
        self.comment_title.setTitle(title)

    def show_context_menu(self, position):
        menu = self.write_area.createStandardContextMenu()
        save_action = QtWidgets.QAction("Save To Selected Cache", self)
        save_action.triggered.connect(self.emit_save_comment)
        menu.insertAction(menu.actions()[0], save_action)
        menu.insertSeparator(menu.actions()[0])
        menu.exec(self.write_area.viewport().mapToGlobal(position))

    def emit_save_comment(self):
        self.save_requested.emit(self.getComment())


class CommentTitle(QtWidgets.QFrame):
    def __init__(self, title, size=(400, 40), parent=None):
        super().__init__(parent)

        # Load icon
        icon_path = Path('path/to/comment.png')
        icon_label = QtWidgets.QLabel()
        icon_label.setPixmap(QtGui.QPixmap(str(icon_path)).scaled(16, 16, QtCore.Qt.KeepAspectRatio))

        # Title Label
        self.title_label = QtWidgets.QLabel(title or "Comment")
        self.title_label.setFont(QtGui.QFont("SF Pro Display", 10))
        self.title_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        # Background layout
        title_layout = QtWidgets.QHBoxLayout(self)
        title_layout.addWidget(icon_label)
        title_layout.addWidget(self.title_label)
        title_layout.setContentsMargins(5, 5, 5, 5)
        self.setFixedSize(*size)

    def setTitle(self, text=None):
        self.title_label.setText(text if text else "Comment")
