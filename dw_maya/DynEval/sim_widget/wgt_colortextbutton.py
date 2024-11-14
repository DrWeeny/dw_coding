# built-in
import sys, os
# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from PySide6 import QtWidgets, QtCore, QtGui


class ColorTextButton(QtWidgets.QWidget):
    """
    A custom widget with a clickable button overlaid by a text label.
    Args:
        text (str): Text to display on the label.
        parent (QWidget, optional): Parent widget, if any.
    """

    def __init__(self, text, parent=None):
        super().__init__(parent)

        # Main stacked layout
        main_layout = QtWidgets.QStackedLayout()
        main_layout.setStackingMode(QtWidgets.QStackedLayout.StackAll)

        # Label displaying text
        self.label = QtWidgets.QLabel(text)
        self.label.setAlignment(QtCore.Qt.AlignCenter)

        # Button overlay
        self.button = QtWidgets.QPushButton()
        self.button.setStyleSheet("background-color: rgba(121, 121, 121, 60);")

        # Add to layout
        main_layout.addWidget(self.label)
        main_layout.addWidget(self.button)
        self.setLayout(main_layout)

    def clicked(self, function):
        """
        Connect a function to the button's clicked signal.
        Args:
            function (callable): Function to call on button click.
        """
        self.button.clicked.connect(function)

    def setStyleSheet(self, style):
        """
        Apply a stylesheet to the button.
        Args:
            style (str): Stylesheet string to apply.
        """
        self.button.setStyleSheet(style)