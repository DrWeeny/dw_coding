"""
DataHubPub - Singleton Publish/Subscribe Pattern for Widget Communication

A centralized data hub that allows widgets to communicate without direct
references to each other. Based on the Observer pattern.

Usage:
    # Get the singleton instance
    hub = DataHubPub.Get()

    # Publish data
    hub.publish("my_key", my_value, overwrite=True)

    # Subscribe to changes
    def on_change(old_value, new_value):
        print(f"Changed from {old_value} to {new_value}")

    hub.subscribe("my_key", on_change)

    # Retrieve current value
    value = hub.retrieve("my_key")

    # Unsubscribe
    hub.unsubscribe("my_key", on_change)

    # Clear a key
    hub.unpublish("my_key")
"""

from typing import Any, Callable, Dict, List, Optional, Set
import weakref
from functools import wraps


class DataHubPub:
    """
    Singleton class for publish/subscribe data communication.

    This is the central hub for widget communication in DynEval.
    Widgets publish data here and subscribe to keys they're interested in.
    When data changes, all subscribers are notified.
    """

    _Instance: Optional['DataHubPub'] = None
    _debug: bool = False

    @classmethod
    def Get(cls) -> 'DataHubPub':
        """
        Get the singleton instance of DataHubPub.

        Returns:
            DataHubPub: The singleton instance
        """
        if cls._Instance is None:
            cls._Instance = DataHubPub.__new__(DataHubPub)
            cls._Instance._init_instance()
        return cls._Instance

    @classmethod
    def Reset(cls):
        """
        Reset the singleton instance. Useful for testing.
        """
        if cls._Instance is not None:
            cls._Instance._data.clear()
            cls._Instance._listeners.clear()
        cls._Instance = None

    @classmethod
    def SetDebug(cls, enabled: bool):
        """Enable or disable debug logging."""
        cls._debug = enabled

    def __init__(self):
        """
        Private constructor - use Get() instead.
        """
        if self.__class__._Instance is not None:
            raise RuntimeError(
                "DataHubPub is a singleton. Use DataHubPub.Get() instead of direct instantiation."
            )

    def _init_instance(self):
        """Initialize instance variables."""
        self._data: Dict[str, Any] = {}
        self._listeners: Dict[str, List[Callable]] = {}
        self._listener_refs: Dict[str, List[weakref.ref]] = {}  # For weak references

    def publish(self, key: str, value: Any, overwrite: bool = False, notify: bool = True) -> bool:
        """
        Publish/store a value with a specific key.

        Args:
            key: The key to store the value under
            value: The value to store (cannot be None as it's reserved for "no value")
            overwrite: If False, won't update existing values
            notify: If True, notify all subscribers of the change

        Returns:
            bool: True if the value was published, False if skipped

        Raises:
            ValueError: If value is None (reserved value)
        """
        if value is None:
            # Allow None to clear values
            return self.unpublish(key)

        old_value = self._data.get(key)

        # Check if we should update
        if old_value is not None and not overwrite:
            if self._debug:
                print(f"[DataHub] Skipped publish {key} (exists, overwrite=False)")
            return False

        # Store the value
        self._data[key] = value

        if self._debug:
            print(f"[DataHub] Published {key}: {type(value).__name__}")

        # Notify listeners
        if notify:
            self._notify_listeners(key, old_value, value)

        return True

    def unpublish(self, key: str) -> bool:
        """
        Remove a value from the hub.

        Args:
            key: The key to remove

        Returns:
            bool: True if the key existed and was removed
        """
        if key in self._data:
            old_value = self._data.pop(key)
            self._notify_listeners(key, old_value, None)

            if self._debug:
                print(f"[DataHub] Unpublished {key}")

            return True
        return False

    def retrieve(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a value from the hub.

        Args:
            key: The key to retrieve
            default: Value to return if key doesn't exist

        Returns:
            The stored value or default
        """
        return self._data.get(key, default)

    def subscribe(self, key: str, listener: Callable, weak: bool = False):
        """
        Subscribe to changes for a specific key.

        Args:
            key: The key to subscribe to
            listener: Callback function(old_value, new_value)
            weak: If True, use weak reference (listener can be garbage collected)

        Raises:
            ValueError: If listener is not callable
        """
        if not callable(listener):
            raise ValueError(f"Listener must be callable, got {type(listener)}")

        if weak:
            # Use weak references to prevent memory leaks
            if key not in self._listener_refs:
                self._listener_refs[key] = []

            ref = weakref.ref(listener)
            if ref not in self._listener_refs[key]:
                self._listener_refs[key].append(ref)
        else:
            if key not in self._listeners:
                self._listeners[key] = []

            if listener not in self._listeners[key]:
                self._listeners[key].append(listener)

        if self._debug:
            print(f"[DataHub] Subscribed to {key}: {listener}")

    def unsubscribe(self, key: str, listener: Callable):
        """
        Unsubscribe from a key.

        Args:
            key: The key to unsubscribe from
            listener: The callback to remove
        """
        # Check regular listeners
        if key in self._listeners:
            try:
                self._listeners[key].remove(listener)
                if self._debug:
                    print(f"[DataHub] Unsubscribed from {key}")
            except ValueError:
                pass  # Listener not found

        # Check weak references
        if key in self._listener_refs:
            self._listener_refs[key] = [
                ref for ref in self._listener_refs[key]
                if ref() is not None and ref() != listener
            ]

    def _notify_listeners(self, key: str, old_value: Any, new_value: Any):
        """
        Notify all listeners of a value change.

        Args:
            key: The key that changed
            old_value: Previous value
            new_value: New value
        """
        # Notify regular listeners
        for listener in self._listeners.get(key, []):
            try:
                listener(old_value, new_value)
            except Exception as e:
                if self._debug:
                    print(f"[DataHub] Error in listener for {key}: {e}")

        # Notify weak reference listeners (and clean up dead refs)
        if key in self._listener_refs:
            live_refs = []
            for ref in self._listener_refs[key]:
                listener = ref()
                if listener is not None:
                    live_refs.append(ref)
                    try:
                        listener(old_value, new_value)
                    except Exception as e:
                        if self._debug:
                            print(f"[DataHub] Error in weak listener for {key}: {e}")

            self._listener_refs[key] = live_refs

    def clear_listeners(self, key: Optional[str] = None):
        """
        Clear listeners for a specific key or all keys.

        Args:
            key: The key to clear listeners for, or None to clear all
        """
        if key is None:
            self._listeners.clear()
            self._listener_refs.clear()
            if self._debug:
                print("[DataHub] Cleared all listeners")
        else:
            self._listeners.pop(key, None)
            self._listener_refs.pop(key, None)
            if self._debug:
                print(f"[DataHub] Cleared listeners for {key}")

    def get_keys(self) -> Set[str]:
        """Get all published keys."""
        return set(self._data.keys())

    def get_listener_count(self, key: str) -> int:
        """Get number of listeners for a key."""
        count = len(self._listeners.get(key, []))
        count += len([r for r in self._listener_refs.get(key, []) if r() is not None])
        return count

    def dump_state(self) -> Dict[str, Any]:
        """
        Get current state for debugging.

        Returns:
            Dict with keys, values, and listener counts
        """
        state = {}
        for key, value in self._data.items():
            state[key] = {
                'value': repr(value)[:100],
                'type': type(value).__name__,
                'listeners': self.get_listener_count(key)
            }
        return state


# Convenience function for quick access
def get_hub() -> DataHubPub:
    """Convenience function to get the DataHub singleton."""
    return DataHubPub.Get()
