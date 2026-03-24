"""
Mind Map Tool — interactive node-graph mind mapper for workflow documentation.

Classes

- MindMapWindow: Top-level QMainWindow — menu bar, tool bar, status bar.
- MindMapScene: QGraphicsScene holding NodeItem and EdgeItem objects.
- MindMapView:  QGraphicsView with zoom / pan support and minimap.
- NodeItem:     QGraphicsItem for a single node (shape, label, colour).
- EdgeItem:     QGraphicsPathItem for a directed or undirected edge.
- NodeEditor:   Inline text-editor dialog (plain text + Markdown preview).
- UndoStack:    Lightweight undo/redo manager wrapping QUndoStack.

Integration

Runs standalone (``python -m dw_utils.mindmap``) or embedded inside any Qt-based
cfxTools panel.  No DCC context required.

"""

from dw_utils.mindmap.main_window import MindMapWindow

from dw_logger import get_logger
log = get_logger()

__version__ = "1.0.0"
__all__ = ["MindMapWindow", "launch"]


def launch(parent=None):
    """
    Launch the Mind Map tool as a standalone window.

    When no QApplication exists (i.e. running as a plain script) this function
    creates one, shows the window, enters the event loop and only returns once
    the window is closed.  When a QApplication is already running (embedded
    inside another panel / DCC) it simply creates and shows the window
    and returns immediately so the caller keeps the reference alive.

    Args:
        parent: Optional Qt parent widget.

    Returns:
        MindMapWindow: The window instance.  The caller MUST keep a reference to
        this object, otherwise Qt will garbage-collect the C++ peer and crash.
    """
    from PySide6 import QtWidgets
    import sys

    # Keep strong module-level references so Qt never GC's the objects while
    # the event loop is running.
    global _app_ref, _win_ref  # noqa: PLW0603

    app = QtWidgets.QApplication.instance()
    _standalone = app is None
    if _standalone:
        _app_ref = QtWidgets.QApplication(sys.argv)
        app = _app_ref

    # Build window AFTER QApplication exists, hold a module-level ref.
    _win_ref = MindMapWindow(parent=parent)
    _win_ref.show()
    _win_ref.raise_()

    if _standalone:
        # Block here until the window is closed, then exit cleanly.
        ret = app.exec_()
        _win_ref = None
        _app_ref = None
        sys.exit(ret)

    return _win_ref


# Module-level refs — prevents premature GC when running selector_widget.
_app_ref = None
_win_ref = None

