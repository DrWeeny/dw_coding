
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
        from Qt import QtWidgets, QtGui, QtCore
        import maya.OpenMayaUI as omui
        import shiboken2

        MODE = 1
    except:
        pass

if MODE == 0:
    from Qt import QtWidgets, QtCore, QtGui

global etsui
etsui = None

########################################################################
# Replace the sample code below with your own to create a
# PyQt5 or PySide2 interface.  Your code must define an
# onCreateInterface() function that returns the root widget of
# your interface.
#
# The 'hutil.Qt' is for internal-use only.
# It is a wrapper module that enables the sample code below to work with
# either a Qt4 or Qt5 environment for backwards-compatibility.
#
# When developing your own Python Panel, import directly from PySide2
# or PyQt5 instead of from 'hutil.Qt'.
########################################################################

import sys
# ----- Edit sysPath -----#
rdPath = '/marza/proj/fuji2019/tools/maya/python/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

# import mzWorkFileManager as mzwfm
# import mzCfxSceneBuilder.mzCfxSceneBuilder_cmds as csbcmd
import mzCfxSceneBuilder.main_ui as csbui
from dw_sound import sox_play

import subprocess
import re
from functools import wraps
import os
import random
p = re.compile('^[A-Za-z0-9]+_\d{2}$')

def getMayaMainWindow():
    """
    Get maya main window
    :return: <<class>>
    """
    return shiboken2.wrapInstance(long(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)

def getHoudiniWindow():
    win = hou.ui.mainQtWindow()
    return win

def complete_sound(func):
    '''

    Args:
        func ():

    Returns:

    '''
    _sound_path = '/home/alexis/Documents/RND/dw_tools/ressources/audio_files/BattleblockTheater/'
    if not os.path.isdir(_sound_path):
        _sound_path = '/marza/proj/fuji2019/tools/maya/audio/BattleblockTheater/'
    _success = [_sound_path+'_happy/'+i for i in os.listdir(_sound_path+'_happy/') if i.endswith('.wav')]
    _fail = [_sound_path + '_death/' + i for i in os.listdir(_sound_path + '_death/') if i.endswith('.wav')]
    r = random.SystemRandom()

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            sox_play(r.choice(_success))
            return result
        except Exception as e:
            sox_play(r.choice(_fail))
            raise e
    return wrapper


class ExportSim(QtWidgets.QMainWindow):

    def __init__(self, parent=None):
        super(ExportSim, self).__init__(parent)
        self.setGeometry(579, 515, 647, 181)
        self.setWindowTitle('Export To Maya')
        self.initUI()

    def initUI(self):
        self.centralwidget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.centralwidget)
        mainLayout = QtWidgets.QVBoxLayout()

        vl_main = QtWidgets.QVBoxLayout()
        self.shotpicker = csbui.ShotPicker()
        self.le_namespace = LineEditLabel('namespace:', 'longclaw_01')
        self.le_lightrig = LineEditLabel('lightrig:', '_sb0120')

        self.le_abc_sim = LineEditLabel('SIM_ABC:', '/marza/proj/fuji2019/work/')
        self.le_abc_anim0 = LineEditLabel('ANIM_ABC:', '/marza/proj/fuji2019/work/')
        self.le_abc_anim1 = LineEditLabel('ANIM_ABC - optionnal -:', '/marza/proj/fuji2019/work/')

        self.line = QtWidgets.QFrame()
        self.line.setFrameShape(QtWidgets.QFrame.VLine)
        self.line.setFrameShadow(QtWidgets.QFrame.Sunken)

        self.pb_export = QtWidgets.QPushButton('export to maya')

        vl_main.addWidget(self.shotpicker)
        vl_main.addWidget(self.le_namespace)
        vl_main.addWidget(self.le_abc_sim)
        vl_main.addWidget(self.le_abc_anim0)
        vl_main.addWidget(self.le_abc_anim1)

        vl_main.addWidget(self.line)
        vl_main.addWidget(self.pb_export)

        mainLayout.addLayout(vl_main)
        self.centralwidget.setLayout(mainLayout)

        self.pb_export.clicked.connect(self.doIt)

    def data(self):
        namespace = self.le_namespace.text()
        if not p.search(namespace):
            QtWidgets.QMessageBox.about(self, "Data", 'please input a valid name : assetname_00')
            raise SyntaxError
        seq = self.shotpicker.seq
        shot = self.shotpicker.shot
        task = self.shotpicker.src_task
        user = self.shotpicker.src_user
        wp = self.shotpicker.src_workProject
        lightrig = self.le_lightrig.text()

        if self.le_abc_anim0.text() and self.le_abc_anim1.text():
            MY_ANIM_ABC = ','.join([self.le_abc_anim0.text(), self.le_abc_anim1.text()])
        else:
            MY_ANIM_ABC = self.le_abc_anim0.text() or self.le_abc_anim1.text()

        MY_SIM_ABC = self.le_abc_sim.text()

        mayaPath = '/usr/autodesk/maya2018/bin/mayapy'
        scriptPath = '/marza/proj/fuji2019/tools/maya/python/mzCfxSceneBuilder/test_sb120_batch.py'

        myArgs = [mayaPath, scriptPath, MY_SIM_ABC, MY_ANIM_ABC, seq, shot, task, user, wp, namespace, lightrig]

        return myArgs

    @complete_sound
    def doIt(self):

        data = self.data()
        # debug = '\n'.join(['{}-{}'.format(x,i) for x, i in enumerate(data)])
        # QtWidgets.QMessageBox.about(self, "Data", debug)

        maya_subprocess = subprocess.Popen(data, stdout = subprocess.PIPE, stderr = subprocess.PIPE)
        out, err = maya_subprocess.communicate()
        exitcode = maya_subprocess.returncode
        if str(exitcode) != '0':
            QtWidgets.QMessageBox.about(self, "ERROR", err)
        else:
            QtWidgets.QMessageBox.about(self, "SUCCESS", out)

def ShowUI():
    if MODE == 0:
        # Create the Qt Application
        app = QtWidgets.QApplication(sys.argv)
        # Create and show the form
        form = ExportSim()
        form.show()
        # Run the main Qt loop
        sys.exit(app.exec_())
    else:
        if MODE == 1:
            parent = getMayaMainWindow()
        if MODE == 2:
            parent = getHoudiniWindow()

        try:
            etsui.deleteLater()
        except:
            pass
        etsui = ExportSim(parent)
        etsui.show()

def onCreateInterface():
    return ExportSim(getHoudiniWindow())

class LineEditLabel(QtWidgets.QWidget):

    def __init__(self, label=str, textEdit=str):
        super(LineEditLabel, self).__init__()
        self.main_layout = QtWidgets.QVBoxLayout()

        _hl_filter = QtWidgets.QHBoxLayout()
        lb = QtWidgets.QLabel(label)
        lb.setAlignment(QtCore.Qt.AlignBottom | QtCore.Qt.AlignRight)
        self.le_text = QtWidgets.QLineEdit(textEdit)
        _hl_filter.addWidget(lb)
        _hl_filter.addWidget(self.le_text)
        lb.setBuddy(self.le_text)
        self.main_layout.addLayout(_hl_filter)
        self.setLayout(self.main_layout)

    def text(self):
        return str(self.le_text.text())

if __name__ == '__main__':
    # Create the Qt Application
    app = QtWidgets.QApplication(sys.argv)
    # Create and show the form
    form = ExportSim()
    form.show()
    # Run the main Qt loop
    sys.exit(app.exec_())

"""
try:
    csbui.deleteLater()
except:
    pass
csbui = mzShotBuilder()
csbui.show()
"""