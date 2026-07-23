try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    # Fallback for older Maya versions shipping PySide2
    from PySide2 import QtCore, QtGui, QtWidgets
# ---------------------------------------------------------------------------
# Qt signals relay (needed because controller has no QObject parent)
# ---------------------------------------------------------------------------

class SlimfastSignals(QtCore.QObject):
    """Qt signals emitted by SlimfastController."""

    #: Emitted when the source list changes.
    #: Payload: (node_labels: list[str], map_lists: list[list[str]])
    sources_changed = QtCore.Signal(list, list, list)
    #: Emitted when the active mesh changes. Payload: mesh name string.
    mesh_changed = QtCore.Signal(str)
    #: Emitted when the active WeightSource changes. Payload: WeightSource or None.
    active_changed = QtCore.Signal(object)
    maps_changed = QtCore.Signal(int)