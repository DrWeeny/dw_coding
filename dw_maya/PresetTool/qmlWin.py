import os
import sys
from PySide2 import QtQuick, QtCore, QtGui

# Locate main.qml
source = QtCore.QUrl.fromLocalFile('/home/abtidona/private/PycharmProjects/RND/dw_tools/maya/RFX/presetTool/main.qml')

# Load main.qml
window = QtQuick.QQuickView()
window.setSource(source)
window.show()


#
# view = QtQuick.QQuickView()
# url = QtCore.QUrl("view.qml")
# view.setSource(url)
