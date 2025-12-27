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


class HubMixin:
    """
    Mixin providing DataHub functionality.

    Can be used with any QObject-derived class.
    Handles subscription tracking and cleanup automatically.
    """

    def init_hub(self):
        """
        Initialize hub connection.
        Called automatically by DynEvalWidget/DynEvalMainWindow.
        """
        self._hub = DataHubPub.Get()
        self._hub_subscriptions: Dict[str, List[Callable]] = {}
        self._hub_initialized = True

    @property
    def hub(self) -> DataHubPub:
        """Get the DataHub instance."""
        if not getattr(self, '_hub_initialized', False):
            self.init_hub()
        return self._hub

    def hub_subscribe(self, key: str, callback: Callable):
        """
        Subscribe to a hub key.

        Args:
            key: HubKeys constant
            callback: Function(old_value, new_value) to call on change
        """
        if not getattr(self, '_hub_initialized', False):
            self.init_hub()

        if key not in self._hub_subscriptions:
            self._hub_subscriptions[key] = []

        if callback not in self._hub_subscriptions[key]:
            self._hub_subscriptions[key].append(callback)
            self.hub.subscribe(key, callback)
            logger.debug(f"{self.__class__.__name__} subscribed to {key}")

    def hub_unsubscribe(self, key: str, callback: Optional[Callable] = None):
        """
        Unsubscribe from a hub key.

        Args:
            key: HubKeys constant
            callback: Specific callback to remove, or None for all
        """
        if not getattr(self, '_hub_subscriptions', None):
            return

        if key in self._hub_subscriptions:
            if callback:
                if callback in self._hub_subscriptions[key]:
                    self._hub_subscriptions[key].remove(callback)
                    self.hub.unsubscribe(key, callback)
            else:
                for cb in self._hub_subscriptions[key]:
                    self.hub.unsubscribe(key, cb)
                self._hub_subscriptions[key] = []

    def hub_publish(self, key: str, value: Any, notify: bool = True):
        """
        Publish a value to the hub.

        Args:
            key: HubKeys constant
            value: Value to publish (None will unpublish)
            notify: Whether to notify subscribers
        """
        if value is None:
            self.hub.unpublish(key)
        else:
            self.hub.publish(key, value, overwrite=True, notify=notify)
            logger.debug(f"{self.__class__.__name__} published {key}")

    def hub_get(self, key: str, default: Any = None) -> Any:
        """
        Get current value from hub.

        Args:
            key: HubKeys constant
            default: Value to return if key not found

        Returns:
            Current value or default
        """
        value = self.hub.retrieve(key)
        return value if value is not None else default

    def cleanup_hub(self):
        """
        Unsubscribe from all hub keys.
        Called automatically on widget close.
        """
        if not getattr(self, '_hub_subscriptions', None):
            return

        for key, callbacks in self._hub_subscriptions.items():
            for callback in callbacks:
                try:
                    self.hub.unsubscribe(key, callback)
                except Exception as e:
                    logger.warning(f"Failed to unsubscribe {key}: {e}")

        self._hub_subscriptions.clear()
        logger.debug(f"{self.__class__.__name__} cleaned up hub subscriptions")


class DynEvalWidget(QtWidgets.QWidget, HubMixin):
    """
    Base QWidget with DataHub integration.

    Features:
        - Automatic hub initialization
        - Automatic cleanup on close
        - Subscription tracking
        - Convenient publish/subscribe/get methods

    Usage:
        class MyCacheWidget(DynEvalWidget):
            def __init__(self, parent=None):
                super().__init__(parent)

                # Setup UI
                self._setup_ui()

                # Subscribe to hub
                self.hub_subscribe(HubKeys.SELECTED_ITEM, self._on_selection)

            def _on_selection(self, old_val, new_val):
                self.update_for_selection(new_val)
    """

    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.init_hub()

    def closeEvent(self, event: QtGui.QCloseEvent):
        """Clean up hub subscriptions on close."""
        self.cleanup_hub()
        super().closeEvent(event)


class DynEvalMainWindow(QtWidgets.QMainWindow, HubMixin):
    """
    Base QMainWindow with DataHub integration.

    Same features as DynEvalWidget but for main windows.
    """

    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.init_hub()

    def closeEvent(self, event: QtGui.QCloseEvent):
        """Clean up hub subscriptions on close."""
        self.cleanup_hub()
        super().closeEvent(event)


class DynEvalDockWidget(QtWidgets.QDockWidget, HubMixin):
    """
    Base QDockWidget with DataHub integration.

    Useful for dockable tool panels.
    """

    def __init__(self, title: str = "", parent: QtWidgets.QWidget = None):
        super().__init__(title, parent)
        self.init_hub()

    def closeEvent(self, event: QtGui.QCloseEvent):
        """Clean up hub subscriptions on close."""
        self.cleanup_hub()
        super().closeEvent(event)


class DynEvalDialog(QtWidgets.QDialog, HubMixin):
    """
    Base QDialog with DataHub integration.

    Useful for popup dialogs that need hub access.
    """

    def __init__(self, parent: QtWidgets.QWidget = None):
        super().__init__(parent)
        self.init_hub()

    def closeEvent(self, event: QtGui.QCloseEvent):
        """Clean up hub subscriptions on close."""
        self.cleanup_hub()
        super().closeEvent(event)


# =============================================================================
# PUBLISHER HELPER
# =============================================================================

class HubPublisher:
    """
    Standalone publisher for non-widget code.

    Provides convenience methods for common publish patterns.

    Usage:
        publisher = HubPublisher()
        publisher.publish_selection(item)
        publisher.publish_status("Loading...", loading=True)
    """

    def __init__(self):
        self._hub = DataHubPub.Get()

    def publish(self, key: str, value: Any):
        """Publish a value."""
        if value is None:
            self._hub.unpublish(key)
        else:
            self._hub.publish(key, value, overwrite=True)

    def publish_selection(self, item_or_items):
        """
        Publish selection context.

        Publishes to multiple keys:
            - SELECTED_ITEM (single item)
            - SELECTED_ITEMS (list)
            - SELECTED_MESH (mesh transform)
            - SELECTED_NODE (simulation node)
            - SOLVER_CURRENT (solver node)
        """
        from .hub_keys import HubKeys, SelectionContext

        if isinstance(item_or_items, list):
            items = item_or_items
            item = items[0] if items else None
        else:
            item = item_or_items
            items = [item] if item else []

        # Create context
        context = SelectionContext.from_items(items) if items else SelectionContext()

        # Publish individual keys
        self._hub.publish(HubKeys.SELECTED_ITEM, item, overwrite=True)
        self._hub.publish(HubKeys.SELECTED_ITEMS, items, overwrite=True)
        self._hub.publish(HubKeys.SELECTED_MESH, context.mesh, overwrite=True)
        self._hub.publish(HubKeys.SELECTED_NODE, context.node, overwrite=True)
        self._hub.publish(HubKeys.SOLVER_CURRENT, context.solver, overwrite=True)

    def publish_cache_selection(self, cache_info):
        """Publish cache selection."""
        from .hub_keys import HubKeys

        self._hub.publish(HubKeys.CACHE_SELECTED, cache_info, overwrite=True)
        if cache_info:
            self._hub.publish(HubKeys.CACHE_ATTACHED,
                              getattr(cache_info, 'is_attached', False),
                              overwrite=True)

    def publish_map_selection(self, map_info):
        """Publish map selection."""
        from .hub_keys import HubKeys

        self._hub.publish(HubKeys.MAP_SELECTED, map_info, overwrite=True)

    def publish_paint_context(self, node: str, attribute: str, mesh: str,
                              solver: str = None, active: bool = True):
        """Publish paint context."""
        from .hub_keys import HubKeys, PaintContext

        context = PaintContext(
            node=node,
            attribute=attribute,
            mesh=mesh,
            is_active=active,
            solver=solver
        )
        self._hub.publish(HubKeys.PAINT_CONTEXT, context, overwrite=True)
        self._hub.publish(HubKeys.PAINT_ACTIVE, active, overwrite=True)

    def publish_status(self, message: str, loading: bool = False):
        """Publish UI status."""
        from .hub_keys import HubKeys

        self._hub.publish(HubKeys.UI_STATUS, message, overwrite=True)
        self._hub.publish(HubKeys.UI_LOADING, loading, overwrite=True)

    def publish_mode(self, mode: str):
        """Publish UI mode change."""
        from .hub_keys import HubKeys

        self._hub.publish(HubKeys.UI_MODE, mode, overwrite=True)

    def clear_selection(self):
        """Clear all selection keys."""
        from .hub_keys import HubKeys

        self._hub.unpublish(HubKeys.SELECTED_ITEM)
        self._hub.publish(HubKeys.SELECTED_ITEMS, [], overwrite=True)
        self._hub.unpublish(HubKeys.SELECTED_MESH)
        self._hub.unpublish(HubKeys.SELECTED_NODE)


# =============================================================================
# DECORATORS
# =============================================================================

def publishes(key: str):
    """
    Decorator that publishes method return value to hub.

    Usage:
        @publishes(HubKeys.SELECTED_ITEM)
        def get_selected(self):
            return self.tree.currentItem()
    """
    from functools import wraps

    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            result = func(self, *args, **kwargs)
            hub = DataHubPub.Get()
            hub.publish(key, result, overwrite=True)
            return result

        return wrapper

    return decorator


def on_hub_change(key: str):
    """
    Decorator marking a method as a hub callback.

    Note: Still need to call hub_subscribe() to activate.
    This is mainly for documentation/discovery.

    Usage:
        @on_hub_change(HubKeys.SELECTED_ITEM)
        def _on_selection_changed(self, old_val, new_val):
            pass
    """

    def decorator(func):
        func._hub_key = key
        return func

    return decorator