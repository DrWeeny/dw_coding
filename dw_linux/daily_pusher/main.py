from __future__ import print_function

# DEFINE wh

MODE = 0

try:
    import hou
    from PySide2 import QtWidgets, QtGui, QtCore

    MODE = 2
except:
    pass

if not MODE > 0:
    try:
        import maya.cmds as cmds
        from PySide2 import QtWidgets, QtGui, QtCore
        import maya.OpenMayaUI as omui
        import shiboken2

        MODE = 1
    except:
        pass

if MODE == 0:
    from PySide2 import QtWidgets, QtCore, QtGui

import datetime
import os
import sys


def getMayaMainWindow():
    """
    Get maya main window
    Returns:
        pointer

    """
    return shiboken2.wrapInstance(long(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)


def getHoudiniWindow():
    """
    get houdini window
    Returns:
        pointer

    """
    win = hou.ui.mainQtWindow()
    return win


class DailyPusher(QtWidgets.QMainWindow):
    """The Result of the sim is Connected to Lookdev, Exported again, And prepare a Maya Render Scene File

    Args:
        parent (pointer): houdini window or maya window

    """

    def __init__(self, parent=None):
        super(DailyPusher, self).__init__(parent)
        self.setGeometry(579, 515, 840, 840)
        self.setWindowTitle('Daily Pusher')
        self.initUI()

    def initUI(self):
        '''
        main proc to create the ui
        '''

        self.centralwidget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.centralwidget)
        mainLayout = QtWidgets.QVBoxLayout()

        img_path = '/home/abtidona/private/PycharmProjects/RND/dw_tools/ressources/pic_files/banner_dailyPusher.jpg'
        # banner = QtGui.QImage(img_path)  # h: 110
        pixmap = QtGui.QPixmap(img_path)
        banner = QtWidgets.QLabel()
        banner.setPixmap(pixmap)

        picker = PushPage()

        mainLayout.addWidget(banner)
        mainLayout.addWidget(picker)
        self.centralwidget.setLayout(mainLayout)


class PushPage(QtWidgets.QWidget):

    def __init__(self):
        super(PushPage, self).__init__()
        main_layout = QtWidgets.QVBoxLayout()

        # the button + combobox
        hl_path_pick = QtWidgets.QHBoxLayout()
        self.btn_locker = QtWidgets.QPushButton()
        img_path = '/home/abtidona/private/PycharmProjects/RND/dw_tools/ressources/pic_files/lock_open.png'
        icon = QtGui.QIcon(img_path)
        self.btn_locker.setIcon(icon)
        self.btn_locker.setIconSize(QtCore.QSize(78, 65))

        # path to sel
        self.dailypath = '/work/21729_MOTH/dailies/CFX/PJ_Internal_Reviews'
        today = datetime.date.today()
        folder = '{}{:02d}{:02d}'.format(today.year, today.month, today.day)

        existing_dirs = os.listdir(self.dailypath)
        if folder not in existing_dirs:
            os.makedirs(os.path.join(self.dailypath, folder))
            existing_dirs.insert(0, folder)

        self.cb_pickFolder = QtWidgets.QComboBox()
        existing_dirs = sorted(existing_dirs)
        for f in existing_dirs[::-1]:
            self.cb_pickFolder.addItem(f)

        hl_path_pick.addWidget(self.btn_locker)
        hl_path_pick.addWidget(self.cb_pickFolder)
        main_layout.addLayout(hl_path_pick)
        self.setLayout(main_layout)

    def path(self):
        folder = self.cb_pickFolder.currentText()
        fullpath = os.path.join(self.dailypath, str(folder))
        return fullpath


def ShowUI():
    if MODE == 0:
        # Create the Qt Application
        app = QtWidgets.QApplication(sys.argv)
        # Create and show the form
        form = DailyPusher()
        form.show()
        # Run the main Qt loop
        sys.exit(app.exec_())
    else:
        if MODE == 1:
            parent = getMayaMainWindow()
        if MODE == 2:
            parent = getHoudiniWindow()

        try:
            dpui.deleteLater()
        except:
            pass
        dpui = DailyPusher(parent)
        dpui.show()
        return dpui


dpui = ShowUI()








