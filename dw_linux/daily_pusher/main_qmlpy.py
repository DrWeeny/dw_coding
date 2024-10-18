import os
import sys
from PySide2 import QtQuick, QtCore, QtGui


# Locate main.qml
qml = '/home/abtidona/private/PycharmProjects/RND/dw_tools/os/RFX/linux/daily_pusher/qml/test.qml'
source = QtCore.QUrl.fromLocalFile(qml)

# Load main.qml
window = QtQuick.QQuickView()

# model
my_py_model = QtGui.QStringListModel()

dailies_path = '/work/21729_MOTH/dailies/CFX/PJ_Internal_Reviews'
art_path = '/work/21729_MOTH/.session_builder_artwork/cfx'

dirs = os.listdir(dailies_path)

my_py_model.setStringList(dirs)
window.rootContext().setContextProperty("myModel", my_py_model)

window.setSource(source)

if window.status() == QtQuick.QQuickView.Error:
    sys.exit(-1)

window.show()


#
# view = QtQuick.QQuickView()
# url = QtCore.QUrl("view.qml")
# view.setSource(url)
