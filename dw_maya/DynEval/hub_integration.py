"""
DataHub Integration for DynEval Widgets

Provides a mixin class and utilities for widgets to easily integrate
with the DataHubPub publish/subscribe system.

Usage:
    class MyWidget(QtWidgets.QWidget, HubSubscriberMixin):
        def __init__(self):
            super().__init__()
            self.init_hub()

            # Subscribe to keys
            self.hub_subscribe(HubKeys.SELECTED_ITEM, self._on_selection_changed)

        def _on_selection_changed(self, old_value, new_value):
            # Handle the change
            pass

        def closeEvent(self, event):
            self.cleanup_hub()  # Important! Unsubscribe on close
            super().closeEvent(event)
"""

from typing import Callable, Dict, List, Any, Optional
from functools import wraps
import weakref

from dw_utils.data_hub import DataHubPub
from .hub_keys import HubKeys, SelectionContext, PaintContext
from dw_logger import get_logger

logger = get_logger()


class HubSubscriberMixin:
    """
    Mixin class that provides easy DataHub integration for widgets.

    Automatically tracks subscriptions and provides cleanup method.
    """

    def init_hub(self):
        """Initialize hub connection. Call this in __init__"""
        self._hub = DataHubPub.Get()
        self._hub_subscriptions: Dict[str, List[Callable]] = {}

    @property
    def hub(self) -> DataHubPub:
        """Get the DataHub instance"""
        if not hasattr(self, '_hub'):
            self.init_hub()
        return self._hub

    def hub_subscribe(self, key: str, callback: Callable):
        """
        Subscribe to a hub key with automatic tracking.

        Args:
            key: HubKeys constant
            callback: Function to call on value change (old_value, new_value)
        """
        if not hasattr(self, '_hub_subscriptions'):
            self._hub_subscriptions = {}

        # Track subscription for cleanup
        if key not in self._hub_subscriptions:
            self._hub_subscriptions[key] = []

        self._hub_subscriptions[key].append(callback)
        self.hub.subscribe(key, callback)

        logger.debug(f"{self.__class__.__name__} subscribed to {key}")

    def hub_unsubscribe(self, key: str, callback: Optional[Callable] = None):
        """
        Unsubscribe from a hub key.

        Args:
            key: HubKeys constant
            callback: Specific callback to remove, or None to remove all
        """
        if not hasattr(self, '_hub_subscriptions'):
            return

        if key in self._hub_subscriptions:
            if callback:
                if callback in self._hub_subscriptions[key]:
                    self._hub_subscriptions[key].remove(callback)
                    self.hub.unsubscribe(key, callback)
            else:
                # Remove all callbacks for this key
                for cb in self._hub_subscriptions[key]:
                    self.hub.unsubscribe(key, cb)
                self._hub_subscriptions[key] = []

    def hub_publish(self, key: str, value: Any, notify: bool = True):
        """
        Publish a value to the hub.

        Args:
            key: HubKeys constant
            value: Value to publish
            notify: Whether to notify subscribers
        """
        self.hub.publish(key, value, overwrite=True, notify=notify)
        logger.debug(f"{self.__class__.__name__} published {key}: {type(value).__name__}")

    def hub_get(self, key: str) -> Any:
        """
        Get current value from hub.

        Args:
            key: HubKeys constant

        Returns:
            Current value or None
        """
        return self.hub.retrieve(key)

    def cleanup_hub(self):
        """
        Unsubscribe from all hub keys. Call this in closeEvent or destructor.
        """
        if not hasattr(self, '_hub_subscriptions'):
            return

        for key, callbacks in self._hub_subscriptions.items():
            for callback in callbacks:
                try:
                    self.hub.unsubscribe(key, callback)
                except Exception as e:
                    logger.warning(f"Failed to unsubscribe {key}: {e}")

        self._hub_subscriptions.clear()
        logger.debug(f"{self.__class__.__name__} cleaned up hub subscriptions")


class HubPublisher:
    """
    Standalone publisher class for non-widget code.

    Usage:
        publisher = HubPublisher()
        publisher.publish_selection(item)
    """

    def __init__(self):
        self._hub = DataHubPub.Get()

    def publish_selection(self, item_or_items):
        """Publish selection context from item(s)"""
        if isinstance(item_or_items, list):
            context = SelectionContext.from_items(item_or_items)
            self._hub.publish(HubKeys.SELECTED_ITEMS, item_or_items, overwrite=True)
        else:
            context = SelectionContext.from_item(item_or_items)
            self._hub.publish(HubKeys.SELECTED_ITEMS, [item_or_items] if item_or_items else [], overwrite=True)

        # Publish individual keys for widgets that only need specific data
        self._hub.publish(HubKeys.SELECTED_ITEM, context.item, overwrite=True)
        self._hub.publish(HubKeys.SELECTED_MESH, context.mesh, overwrite=True)
        self._hub.publish(HubKeys.SELECTED_NODE, context.node, overwrite=True)
        self._hub.publish(HubKeys.SOLVER_CURRENT, context.solver, overwrite=True)
        self._hub.publish(HubKeys.SOLVER_NAMESPACE, context.namespace, overwrite=True)

    def publish_cache_selection(self, cache_info):
        """Publish cache selection"""
        self._hub.publish(HubKeys.CACHE_SELECTED, cache_info, overwrite=True)
        if cache_info:
            self._hub.publish(HubKeys.CACHE_ATTACHED, cache_info.is_attached, overwrite=True)
            self._hub.publish(HubKeys.CACHE_VERSION, cache_info.version, overwrite=True)

    def publish_map_selection(self, map_info):
        """Publish map selection"""
        self._hub.publish(HubKeys.MAP_SELECTED, map_info, overwrite=True)
        if map_info:
            self._hub.publish(HubKeys.MAP_TYPE, map_info.map_type, overwrite=True)

    def publish_paint_context(self, node: str, attribute: str, mesh: str, solver: str = None):
        """Publish paint context"""
        context = PaintContext(
            node=node,
            attribute=attribute,
            mesh=mesh,
            is_active=True,
            solver=solver
        )
        self._hub.publish(HubKeys.PAINT_CONTEXT, context, overwrite=True)
        self._hub.publish(HubKeys.PAINT_ACTIVE, True, overwrite=True)

    def publish_paint_ended(self):
        """Publish that paint mode has ended"""
        self._hub.publish(HubKeys.PAINT_ACTIVE, False, overwrite=True)

    def publish_ui_mode(self, mode: str):
        """Publish UI mode change"""
        self._hub.publish(HubKeys.UI_MODE, mode, overwrite=True)

    def publish_status(self, message: str, loading: bool = False):
        """Publish status message"""
        self._hub.publish(HubKeys.UI_STATUS, message, overwrite=True)
        self._hub.publish(HubKeys.UI_LOADING, loading, overwrite=True)

    def clear_selection(self):
        """Clear all selection-related keys"""
        self._hub.publish(HubKeys.SELECTED_ITEM, None, overwrite=True)
        self._hub.publish(HubKeys.SELECTED_ITEMS, [], overwrite=True)
        self._hub.publish(HubKeys.SELECTED_MESH, None, overwrite=True)
        self._hub.publish(HubKeys.SELECTED_NODE, None, overwrite=True)


# Decorator for methods that should publish their result
def publishes(key: str):
    """
    Decorator that publishes the return value of a method to the hub.

    Usage:
        @publishes(HubKeys.SELECTED_ITEM)
        def get_selected_item(self):
            return self.tree.currentItem()
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            result = func(self, *args, **kwargs)
            hub = DataHubPub.Get()
            hub.publish(key, result, overwrite=True)
            return result
        return wrapper
    return decorator


# Decorator for methods that should react to hub changes
def subscribes_to(*keys: str):
    """
    Decorator that marks a method as a hub subscriber.
    Must be used with HubSubscriberMixin.

    Usage:
        @subscribes_to(HubKeys.SELECTED_ITEM)
        def _on_selection_changed(self, old_value, new_value):
            pass
    """
    def decorator(func):
        func._hub_subscriptions = keys
        return func
    return decorator


def auto_subscribe(widget_instance):
    """
    Automatically subscribe all methods decorated with @subscribes_to.

    Call this after widget initialization:
        auto_subscribe(self)
    """
    for name in dir(widget_instance):
        method = getattr(widget_instance, name, None)
        if callable(method) and hasattr(method, '_hub_subscriptions'):
            for key in method._hub_subscriptions:
                widget_instance.hub_subscribe(key, method)
