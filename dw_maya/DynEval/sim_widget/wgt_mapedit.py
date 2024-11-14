# built-in
import sys, os
# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from PySide6 import QtWidgets, QtCore, QtGui

class MapEdit(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        # Main layout
        main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(main_layout)

        # Radio buttons for choosing edit mode
        self.rbVtxRange = QtWidgets.QRadioButton("Range")
        self.rbVtxRange.setChecked(True)
        main_layout.addWidget(self.rbVtxRange)

        self.rbVtxValue = QtWidgets.QRadioButton("Value")
        main_layout.addWidget(self.rbVtxValue)

        # Widget range selection
        self.range_layout = QtWidgets.QHBoxLayout()

        self.leMinRange = QtWidgets.QLineEdit()
        self.leMaxRange = QtWidgets.QLineEdit()

        self.range_layout.addWidget(QtWidgets.QLabel("Min:"))
        self.range_layout.addWidget(self.leMinRange)
        self.range_layout.addWidget(QtWidgets.QLabel("Max:"))
        self.range_layout.addWidget(self.leMaxRange)

        main_layout.addLayout(self.range_layout)

        # Update range visibility based on selection
        self.rbVtxRange.toggled.connect(self.update_range_visibility)
        self.rbVtxValue.toggled.connect(self.update_range_visibility)

        # Initialize visibility
        self.update_range_visibility()

    def update_range_visibility(self):
        """
        Toggle visibility of min and max range line edits based on radio selection.
        """
        is_range_mode = self.rbVtxRange.isChecked()
        self.leMinRange.setVisible(is_range_mode)
        self.leMaxRange.setVisible(is_range_mode)