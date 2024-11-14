from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *
from shiboken6 import wrapInstance

from maya import OpenMayaUI as omui
from maya.app.general.mayaMixin import MayaQWidgetBaseMixin

import sys
import os
import functools

import maya.cmds as cmds
import maya.mel as mm
import maya.standalone


class Form(QDialog):
    """A GUI for managing Ziva caches in Maya."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Widgets
        self.lCacheName = QLabel("Cache name")
        self.lCacheStart = QLabel("Start")
        self.lCacheEnd = QLabel("End")
        self.name = QLineEdit("zCache1")
        self.startFrame = QLineEdit("89")
        self.endFrame = QLineEdit("200")
        self.writeButton = QPushButton("Write Cache")
        self.loadButton = QPushButton("Load Cache")
        self.lResult = QLabel(" ")
        self.zivaCaches = QComboBox()

        # Populate Ziva caches in the scene
        self.zivaCaches.addItems([zCache for zCache in cmds.ls(type='zCache')])

        # Layout
        layout = QFormLayout(self)
        layout.addRow("Ziva Cache", self.zivaCaches)
        layout.addRow(self.lCacheName, self.name)
        layout.addRow(self.lCacheStart, self.startFrame)
        layout.addRow(self.lCacheEnd, self.endFrame)
        layout.addRow(self.writeButton, self.loadButton)
        layout.addRow(self.lResult)

        # Signals
        self.writeButton.clicked.connect(self.savefile)
        self.loadButton.clicked.connect(self.openfile)

    def savefile(self):
        """Save the current Ziva cache to disk frame by frame."""
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", "~",
                                                     QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks)
        if directory:
            try:
                start_frame = int(self.startFrame.text())
                end_frame = int(self.endFrame.text())
                cache_name = self.name.text()
                current_cache = self.zivaCaches.currentText()

                mm.eval(f"zCache -clear {current_cache}")
                for frame in range(start_frame, end_frame + 1):
                    cmds.currentTime(frame)
                    path = os.path.join(directory, f"{cache_name}.{frame:04d}.zCache")
                    print(f"{path} written to disk")
                    mm.eval(f'zCache -save "{path}" {current_cache}')
                    mm.eval(f"zCache -clear {current_cache}")

                self.lResult.setText("... SAVE SUCCESSFUL ...")

            except Exception as e:
                self.lResult.setText("Error saving cache")
                print(f"Error: {e}")

    def openfile(self):
        """Load a previously saved Ziva cache from disk."""
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", "~",
                                                     QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks)
        if directory:
            try:
                start_frame = int(self.startFrame.text())
                end_frame = int(self.endFrame.text())
                cache_name = self.name.text()
                current_cache = self.zivaCaches.currentText()

                cmds.currentTime(start_frame)

                for frame in range(start_frame, end_frame + 1):
                    path = os.path.join(directory, f"{cache_name}.{frame:04d}.zCache")
                    print(f"{path} loaded")
                    mm.eval(f'zCache -load "{path}" {current_cache}')

                self.lResult.setText("... LOAD SUCCESSFUL ...")

            except Exception as e:
                self.lResult.setText("Error loading cache")
                print(f"Error: {e}")

if __name__ == '__main__':
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    form = Form()
    form.show()
