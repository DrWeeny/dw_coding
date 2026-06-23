"""
wgt_base.py - DynForge base widget classes with built-in DataHub integration.

Mirrors DynEval's sim_widget/wgt_base.py: a small per-window observable hub plus
a QMainWindow base and a QWidget base that track their subscriptions and clean
them up on close.

Usage
-----
    class GuideListPanel(DynForgeWidgetBase):
        def __init__(self, hub, parent=None):
            super().__init__(hub, parent)
            self.subscribe(DynForgeKeys.GUIDE_SELECTED, self._on_selected)

        def _on_selected(self, old_value, new_value):
            ...
"""

from __future__ import annotations

from typing import Any, Callable

from dw_maya.DynForge.forge_cmds.compat import QtWidgets
from dw_logger import get_logger

logger = get_logger()


# ============================================================================
# DATA HUB
# ============================================================================

class DataHub:
    """
    Simple observable key-value store (per-window).

    set(key, value)     stores value and calls every subscriber with
                        (old_value, new_value); exceptions are logged, not raised.
    get(key, default)   returns the current value or default.
    subscribe(key, cb)  cb signature: (old_value, new_value) -> None.
    unsubscribe(key, cb) safe even if cb was never subscribed.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any]            = {}
        self._subs:  dict[str, list[Callable]] = {}

    def subscribe(self,
                  key:      str,
                  callback: Callable[[Any, Any], None],) -> None:
        bucket = self._subs.setdefault(key, [])
        if callback not in bucket:
            bucket.append(callback)

    def unsubscribe(self,
                    key:      str,
                    callback: Callable[[Any, Any], None],) -> None:
        try:
            self._subs.get(key, []).remove(callback)
        except ValueError:
            pass

    def set(self,
            key:   str,
            value: Any,) -> None:
        old = self._store.get(key)
        self._store[key] = value
        # Iterate over a copy - a callback may (un)subscribe during notification.
        for cb in list(self._subs.get(key, [])):
            try:
                cb(old, value)
            except Exception as e:
                logger.warning(f"DataHub: subscriber error on key {key!r}: {e}")

    def get(self,
            key:     str,
            default: Any = None,) -> Any:
        return self._store.get(key, default)


# ============================================================================
# MAIN WINDOW BASE
# ============================================================================

class DynForgeMainWindow(QtWidgets.QMainWindow):
    """Base for DynForgeUI: owns the DataHub and tracks its own subscriptions."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.hub = DataHub()
        self._subs: list = []

    def hub_subscribe(self,
                      key:      str,
                      callback: Callable[[Any, Any], None],) -> None:
        self.hub.subscribe(key, callback)
        self._subs.append((key, callback))

    def hub_publish(self,
                    key:   str,
                    value: Any,) -> None:
        self.hub.set(key, value)

    def hub_get(self,
                key:     str,
                default: Any = None,) -> Any:
        return self.hub.get(key, default)

    def closeEvent(self, event):
        for key, cb in self._subs:
            self.hub.unsubscribe(key, cb)
        self._subs.clear()
        super().closeEvent(event)


# ============================================================================
# PANEL BASE
# ============================================================================

class DynForgeWidgetBase(QtWidgets.QWidget):
    """Base for DynForge panels: receives the shared hub and cleans up its subs."""

    def __init__(self,
                 hub:    DataHub,
                 parent=None,) -> None:
        super().__init__(parent)
        self._hub = hub
        self._subs: list = []

    def subscribe(self,
                  key:      str,
                  callback: Callable[[Any, Any], None],) -> None:
        self._hub.subscribe(key, callback)
        self._subs.append((key, callback))

    def publish(self,
                key:   str,
                value: Any,) -> None:
        self._hub.set(key, value)

    def hub_get(self,
                key:     str,
                default: Any = None,) -> Any:
        return self._hub.get(key, default)

    def cleanup(self) -> None:
        for key, cb in self._subs:
            self._hub.unsubscribe(key, cb)
        self._subs.clear()

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)