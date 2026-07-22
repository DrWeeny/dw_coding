"""Generic python-callable undo bridge for Maya.

Some operations never register with Maya's undo queue no matter how they're
wrapped — raw ``maya.api.OpenMaya`` calls (e.g. ``MFnMesh.setVertexColors``)
are not ``cmds``/MEL commands and are not undoable on their own; wrapping
them in :func:`~dw_maya.dw_decorators.dw_undo.singleUndoChunk` only groups
whatever *does* land on the queue, it does not create entries. This module
plugs that gap with a tiny internal ``MPxCommand`` ("dwPyUndo") whose
``doIt``/``undoIt`` simply call back into arbitrary python callables, so one
push_undo() call becomes a normal Ctrl+Z-able undo-queue entry.

Functions:
    push_undo — run a redo callable now, register its undo callable on
                Maya's undo queue.

Example::

    from dw_maya.dw_decorators.dw_generic_undo import push_undo

    old_colors = fn_mesh.getVertexColors(color_set)
    def _redo():
        fn_mesh.setVertexColors(new_colors, indices)
    def _undo():
        fn_mesh.setVertexColors(old_colors, indices)
    push_undo(_redo, _undo)

Author: DrWeeny
"""

import os
from typing import Callable, List, Tuple

from maya import cmds
import maya.api.OpenMaya as om2

from dw_logger import get_logger

logger = get_logger()

_CMD_NAME = 'dwPyUndo'
# Stack of (redo, undo) callables — pushed by push_undo(), popped by doIt().
# Reset to empty every time this module is (re)imported, see _plugin_loaded.
_pending: List[Tuple[Callable[[], None], Callable[[], None]]] = []
# False on every fresh import/reload — forces _ensure_loaded() to rebind the
# plugin's command class to *this* module instance (dev iteration reloads
# dw_maya frequently; an already-loaded plugin would otherwise keep pointing
# at the stale module's _pending list).
_plugin_loaded = False


def maya_useNewAPI():
    pass


class _DwPyUndoCommand(om2.MPxCommand):
    """Runs one stored (redo, undo) callable pair as a normal undo entry."""

    def __init__(self) -> None:
        super().__init__()
        self._redo: Callable[[], None] = None
        self._undo: Callable[[], None] = None

    @staticmethod
    def creator():
        return _DwPyUndoCommand()

    def doIt(self, args) -> None:
        if _pending:
            self._redo, self._undo = _pending.pop()
        self.redoIt()

    def redoIt(self) -> None:
        if self._redo is not None:
            self._redo()

    def undoIt(self) -> None:
        if self._undo is not None:
            self._undo()

    def isUndoable(self) -> bool:
        return True


def initializePlugin(mobject) -> None:
    plugin_fn = om2.MFnPlugin(mobject)
    plugin_fn.registerCommand(_CMD_NAME, _DwPyUndoCommand.creator)


def uninitializePlugin(mobject) -> None:
    plugin_fn = om2.MFnPlugin(mobject)
    plugin_fn.deregisterCommand(_CMD_NAME)


def _ensure_loaded() -> bool:
    """Load (or reload, if bound to a stale module instance) the bridge plugin."""
    global _plugin_loaded
    if _plugin_loaded:
        return True

    plugin_file = os.path.abspath(__file__)
    plugin_name = os.path.splitext(os.path.basename(plugin_file))[0]
    try:
        if cmds.pluginInfo(plugin_name, query=True, loaded=True):
            # Loaded from a previous module instance (dev reload) — rebind.
            cmds.unloadPlugin(plugin_name, force=True)
        cmds.loadPlugin(plugin_file, quiet=True)
        _plugin_loaded = True
    except Exception as e:
        logger.error(f"Failed to load dwPyUndo bridge plugin: {e}")
        _plugin_loaded = False
    return _plugin_loaded


def push_undo(redo_func: Callable[[], None], undo_func: Callable[[], None]) -> bool:
    """Run *redo_func* now and register *undo_func* on Maya's undo queue.

    Args:
        redo_func: Called immediately, and again on any future Ctrl+Shift+Z.
        undo_func: Called on Ctrl+Z to reverse *redo_func*'s effect.

    Returns:
        True if the call was registered on Maya's undo queue. False if the
        bridge plugin failed to load — *redo_func* still runs regardless,
        it just won't be undoable.
    """
    if not _ensure_loaded():
        redo_func()
        return False

    _pending.append((redo_func, undo_func))
    try:
        cmds.dwPyUndo()
        return True
    except Exception as e:
        logger.error(f"dwPyUndo invocation failed: {e}")
        if _pending and _pending[-1] == (redo_func, undo_func):
            _pending.pop()
        redo_func()
        return False