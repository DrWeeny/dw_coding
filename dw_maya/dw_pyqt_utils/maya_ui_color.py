from maya import cmds
from maya import mel
from maya import OpenMayaUI as omui

import PySide6.QtWidgets as QtWidgets
import PySide6.QtGui as QtGui
from shiboken6 import wrapInstance

import colorsys

try:
    if myDicColors:
        print('already exist')

except:
    myDicColors = {}
    myDicColors['mySetColors'] = [(.02, .667, 69), (1, .5, 0), (.839, .475, .88), (.49, .127, .127), (.127, .236, .49),
                                  (.29, .127, .49), (.127, .49, .133), (.063, .326, .35), (.88, .853, .475)]
    myDicColors['index'] = 0


def defineColor():
    color = myDicColors['mySetColors'][myDicColors['index']]
    recall = color
    myHSV = colorsys.rgb_to_hsv(*color)
    newHSV = (myHSV[0], myHSV[1] * .35, .8)
    windowColor = ((myHSV[0] * 360 + 122.5) / 360, myHSV[1] * .35, .35)
    windowColor = colorsys.hsv_to_rgb(*windowColor)
    color = [i * 255 for i in color]
    windowColor = [i * 255 for i in windowColor]

    return color, windowColor


def changeMayaBackgroundColor(color='rgb(0, 0, 255)', fontStyle='italic', fontWeight='bold'):
    ptr = omui.MQtUtil.mainWindow()
    widget = wrapInstance(int(ptr), QtWidgets.QWidget)


    widget.setStyleSheet(
        "QPushButton {color:white;} QPushButton:checked{background-color: rgb(200, 150, 80); border: none;} QPushButton:hover{background-color: blue;border-style: outset;}")

    widget.setStyleSheet(
        "QCheckBox {color:white;} QCheckBox:checked{background-color: rgb(200, 150, 80); border: none;} QCheckBox:hover{background-color: blue; border-style: outset;}")

    widget.setStyleSheet(
        'font-family:BlackKnightFLF;' +
        'font-size:19px;' +
        f'color:{color};'
    )
    # widget->setStyleSheet(QString("first part of stylesheet") + path_string + QString("another part of stylesheet"));


def doIt():
    winColor = defineColor()[1]
    changeMayaBackgroundColor(f'rgb(220,220, 220)')

    base_palette = QtGui.QPalette()
    MENU_COLOR = QtGui.QColor(*winColor)
    base_palette.setBrush(QtGui.QPalette.ColorRole.Window, QtGui.QBrush(MENU_COLOR))
    QtWidgets.QApplication.setPalette(base_palette, 'QMenuBar')

    i = myDicColors['index']
    mycolor = myDicColors['mySetColors'][i]
    i += 1
    if i // 9 == 1:
        i = 0
    myDicColors['index'] = i


doIt()