"""Entry point: python -m dw_utils.mindmap"""
import sys

# Hold module-level references — Qt will GC the C++ peer if these go out of
# scope before the event loop exits.
from PySide6 import QtWidgets
from dw_utils.mindmap.main_window import MindMapWindow

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
_win = MindMapWindow()
_win.show()
_win.raise_()

sys.exit(_app.exec_())
