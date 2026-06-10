"""
Base Widget Classes for DynEval

Provides base classes with built-in DataHub integration.
All DynEval widgets should inherit from these base classes.

Usage:
    class MyWidget(DynEvalWidget):
        def __init__(self, parent=None):
            super().__init__(parent)

            # Subscribe to hub keys
            self.hub_subscribe(HubKeys.SELECTED_ITEM, self._on_selection_changed)

        def _on_selection_changed(self, old_value, new_value):
            # Handle change
            pass

    # For QMainWindow:
    class MyMainWindow(DynEvalMainWindow):
        ...
"""

from typing import Callable, Dict, List, Any, Optional
from PySide6 import QtWidgets, QtCore, QtGui

from dw_utils.data_hub import DataHubPub
from dw_logger import get_logger

logger = get_logger()

class DynEvalWidgetBase(QtWidgets.QWidget):
    """
    Base for all DynEval panels.

    Subclasses interact with shared state only through `publish` / `subscribe`.
    No direct references between sibling widgets.
    """

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self._hub = hub
        self._subs: list[tuple] = []

    def subscribe(self, key: str, callback) -> None:
        self._hub.subscribe(key, callback)
        self._subs.append((key, callback))

    def publish(self, key: str, value) -> None:
        self._hub.set(key, value)

    def hub_get(self, key: str):
        return self._hub.get(key)

    def cleanup(self):
        for key, cb in self._subs:
            self._hub.unsubscribe(key, cb)
        self._subs.clear()

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)