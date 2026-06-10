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
try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Slot
    from shiboken6 import wrapInstance
except ImportError:
    # Fallback for older Maya versions shipping PySide2
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Slot
    from shiboken2 import wrapInstance

from dw_utils.data_hub import DataHubPub
from dw_logger import get_logger

logger = get_logger()


# ============================================================================
# DATA HUB
# ============================================================================

class DataHub:
    """
    Simple observable key-value store.

    set(key, value)
        Stores value and calls every subscriber for that key with
        (old_value, new_value).  Callbacks are fired synchronously.
        Exceptions inside callbacks are logged but do not interrupt
        the remaining subscribers.

    get(key, default=None)
        Returns the current stored value, or default if not yet set.

    subscribe(key, callback)
        callback signature: (old_value, new_value) -> None

    unsubscribe(key, callback)
        Safe to call even if the callback was never subscribed.
    """

    def __init__(self):
        self._store: dict[str, Any] = {}
        self._subs: dict[str, list[Callable]] = {}

    # ------------------------------------------------------------------

    def subscribe(self, key: str, callback: Callable[[Any, Any], None]) -> None:
        bucket = self._subs.setdefault(key, [])
        if callback not in bucket:
            bucket.append(callback)

    def unsubscribe(self, key: str, callback: Callable[[Any, Any], None]) -> None:
        try:
            self._subs.get(key, []).remove(callback)
        except ValueError:
            pass

    def set(self, key: str, value: Any) -> None:
        old = self._store.get(key)
        self._store[key] = value
        # Iterate over a copy — a callback may (un)subscribe during notification
        for cb in list(self._subs.get(key, [])):
            try:
                cb(old, value)
            except Exception as e:
                logger.warning(f"DataHub: subscriber error on key {key!r}: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    # ------------------------------------------------------------------
    # Housekeeping

    def clear_key(self, key: str) -> None:
        """Remove a stored value without notifying subscribers."""
        self._store.pop(key, None)

    def reset(self) -> None:
        """Wipe all stored values and all subscribers."""
        self._store.clear()
        self._subs.clear()


# ============================================================================
# MAIN WINDOW BASE
# ============================================================================

class DynEvalMainWindow(QtWidgets.QMainWindow):
    """
    Base class for DynEvalUI.

    Creates and owns the DataHub.  Panels receive a reference to self.hub
    via DynEvalWidgetBase.__init__.

    The main window uses hub_subscribe / hub_publish for the small number of
    cross-tool concerns it handles directly (e.g. PAINT_REQUESTED → Slimfast).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hub = DataHub()
        self._subs: list[tuple[str, Callable]] = []

    # ------------------------------------------------------------------

    def hub_subscribe(self, key: str, callback: Callable[[Any, Any], None]) -> None:
        self.hub.subscribe(key, callback)
        self._subs.append((key, callback))

    def hub_publish(self, key: str, value: Any) -> None:
        self.hub.set(key, value)

    def hub_get(self, key: str, default: Any = None) -> Any:
        return self.hub.get(key, default)

    # ------------------------------------------------------------------

    def closeEvent(self, event):
        for key, cb in self._subs:
            self.hub.unsubscribe(key, cb)
        self._subs.clear()
        super().closeEvent(event)


# ============================================================================
# PANEL BASE
# ============================================================================

class DynEvalWidgetBase(QtWidgets.QWidget):
    """
    Base class for all DynEval panels (SimTreePanel, CacheVersionPanel, …).

    Receives the shared DataHub from DynEvalMainWindow and tracks every
    subscription it registers so they can be cleaned up automatically.

    Cleanup happens in two situations:
    - The panel's closeEvent fires (tab removed, window closed).
    - cleanup() is called explicitly.
    """

    def __init__(self, hub: DataHub, parent=None):
        super().__init__(parent)
        self._hub = hub
        self._subs: list[tuple[str, Callable]] = []

    # ------------------------------------------------------------------

    def subscribe(self, key: str, callback: Callable[[Any, Any], None]) -> None:
        self._hub.subscribe(key, callback)
        self._subs.append((key, callback))

    def publish(self, key: str, value: Any) -> None:
        self._hub.set(key, value)

    def hub_get(self, key: str, default: Any = None) -> Any:
        return self._hub.get(key, default)

    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        for key, cb in self._subs:
            self._hub.unsubscribe(key, cb)
        self._subs.clear()

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)
