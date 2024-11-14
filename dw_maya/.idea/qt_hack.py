from PySide2 import QtCore, QtGui, QtWidgets
import shiboken2
import maya.OpenMayaUI as OpenMayaUI


def mayaToQT(name):
    # Maya -> QWidget
    ptr = OpenMayaUI.MQtUtil.findControl(name)
    if ptr is None:         ptr = OpenMayaUI.MQtUtil.findLayout(name)
    if ptr is None:         ptr = OpenMayaUI.MQtUtil.findMenuItem(name)
    if ptr is not None:     return shiboken2.wrapInstance(long(ptr), QtWidgets.QWidget)

class ButtonTrick():
    def __init__(self, name):


class SpecialButton():
    def __init__(self, parent):
        super(SpecialButton, self).__init__(parent)


    def mousePressEvent(self, event):
        """ Detect left or right click on QPushButton
            :param event: event
            :type event: QtGui.QEvent """
        if event.button() == QtCore.Qt.LeftButton:
            self.on_leftClick()
        elif event.button() == QtCore.Qt.RightButton:
            self.on_rightClick()

btn = cmds.button()
ptr_btn = mayaToQT(btn)
SpecialButton(ptr_btn)