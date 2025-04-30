"""
This module handle a list of string model
It has been subclassed so the last item which is the user category has a different color and bold font

Class:
    - CustomStringListModel : QtCore.QStringListModel

"""

from PySide2 import QtCore, QtGui, QtWidgets

class CustomStringListModel(QtCore.QStringListModel):
    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None

        # if role == QtCore.Qt.FontRole and index.row() == self.rowCount() - 1:
        #     font = QtGui.QFont()
        #     font.setBold(True)
        #     return font

        if role == QtCore.Qt.BackgroundRole and index.row() == self.rowCount() - 1:
            return QtGui.QBrush(QtGui.QColor("#f0f0f0"))  # light gray

        return super().data(index, role)
