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
rdPath = '/user_data/AMJB/coding/dw_tools/maya/DNEG2'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

# internal
from PySide2 import QtWidgets, QtCore, QtGui
# external

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

class CommentEditor(QtWidgets.QWidget):

    save = QtCore.Signal(str)

    def __init__(self, title=None,
                 size=[400, 40], parent=None):
        QtWidgets.QWidget.__init__(self, parent)

        _vl_main = QtWidgets.QVBoxLayout()

        self._comment = CommentTitle(title, [400, 50])

        self._le_dsp = QtWidgets.QTextEdit()
        self._le_dsp.setPlaceholderText("display comment area")
        self._le_dsp.setStyleSheet("font-weight: bold; "
                              "color: white; "
                              "background-color: rgb(64,64,64)")
        self._le_dsp.setReadOnly(True)

        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)

        self._le_write = QtWidgets.QTextEdit()
        self._le_write.setPlaceholderText('write a comment')

        _vl_main.addWidget(self._comment)
        _vl_main.addWidget(self._le_dsp)
        _vl_main.addWidget(line)
        _vl_main.addWidget(self._le_write)

        self._le_write.installEventFilter(self)
        self._le_write.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self._le_write.customContextMenuRequested.connect(self.menu_save_comment)

        self.setLayout(_vl_main)

    def setComment(self, txt=None):
        if txt:
            self._le_dsp.setText(txt)
        else:
            self._le_dsp.clear()

    def getComment(self):
        return self._le_write.toPlainText()

    def setTitle(self, title=None):
        self._comment.setTitle(title)

    def menu_save_comment(self, position):

        menu = self._le_write.createStandardContextMenu()
        save = QtWidgets.QAction(self)
        save.setText("Save To Selected Cache")
        save.setObjectName("foo")
        menu.setStyleSheet("QMenu::item#foo { color:red ;}")
        save.triggered.connect(self.save_comment)

        action_zero = menu.actions()[0]
        menu.insertAction(action_zero, save)
        menu.insertSeparator(action_zero)

        menu.exec_(self._le_write.viewport().mapToGlobal(position))

    def save_comment(self):
        self.save.emit(self.getComment())
        print("save comment")


class CommentTitle(QtWidgets.QFrame):

    imgpath = rdPath + '/../../ressources/pic_files'
    if not os.path.isdir(imgpath):
        imgpath = rdPath + '/../ressources/pic_files'

    def __init__(self, title, size=[400, 40], parent=None):
        super(CommentTitle, self).__init__(parent)

        pixmap = QtGui.QPixmap(self.imgpath + '/comment.png')
        pixmap_label = QtWidgets.QLabel(pixmap=pixmap, scaledContents=True)

        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignCenter)

        font = QtGui.QFont()
        font.setFamily("SF Pro Display")
        font.setPointSize(10)
        self.title_label.setFont(font)
        self.title_label.setWordWrap(True)

        self.setFixedSize(*size)

        self.background_label = QtWidgets.QLabel(pixmap_label)
        self.background_label.setFixedSize(*size)
        # self.background_label.move(0, 0)

        background_lay = QtWidgets.QVBoxLayout(self.background_label)
        background_lay.addWidget(self.title_label)
        background_lay.setMargin(0)
        background_lay.setSpacing(0)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(pixmap_label)

    def setTitle(self, txt=None):
        self.title_label.setText(txt)
