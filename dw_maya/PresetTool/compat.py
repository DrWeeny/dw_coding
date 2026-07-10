"""
forge_cmds/compat.py - PySide2 / PySide6 compatibility layer

Single source of truth for API differences between the two versions.
All DynForge files should import Qt from here rather than directly.

Known differences handled
-------------------------
QShortcut   QtWidgets (PySide2)  ->  QtGui (PySide6)
QAction     QtWidgets (PySide2)  ->  QtGui (PySide6)
exec_()     PySide2 convention   ->  exec() in PySide6
            (exec_() still works in PySide6 but emits DeprecationWarning)

Usage in any DynForge file
--------------------------
    from dw_maya.DynForge.forge_cmds.compat import (
        QtCore, QtGui, QtWidgets, Qt, Signal, Slot,
        wrapInstance, QShortcut, QAction, qt_exec, PYSIDE_VERSION,
    )
"""

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt, Signal, Slot
    from shiboken6 import wrapInstance

    # Moved to QtGui in PySide6
    QShortcut = QtGui.QShortcut
    QAction   = QtGui.QAction

    def qt_exec(obj, *args, **kwargs):
        """Call exec() - PySide6 dropped the trailing underscore."""
        return obj.exec(*args, **kwargs)

    PYSIDE_VERSION = 6

except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Qt, Signal, Slot
    from shiboken2 import wrapInstance

    # Still in QtWidgets in PySide2
    QShortcut = QtWidgets.QShortcut
    QAction   = QtWidgets.QAction

    def qt_exec(obj, *args, **kwargs):
        """Call exec_() - PySide2 convention."""
        return obj.exec_(*args, **kwargs)

    PYSIDE_VERSION = 2