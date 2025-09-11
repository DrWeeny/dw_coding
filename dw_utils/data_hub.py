from typing import Any, Callable

class DataHubPub(object):
    """
    Singleton class to publish data and notify listeners on change
    Used to share data between different widgets
    Similar to Event/Signals/Slot in
    """
    _Instance = None

    @classmethod
    def Get(cls):
        """
        Get the singleton instance of the DataPublisher.
        """
        if cls._Instance is None:
            inst = DataHubPub()
            cls._Instance = inst
        return cls._Instance

    def __init__(self):
        if self.__class__._Instance is not None:
            raise RuntimeError(
                "DataPublisher class shouldn't be instanced directly. Use the 'Get' class method instead")
        self._data = {}
        self._listeners = {}

    def publish(self, key:str, value:Any, overwrite:bool=False, notify:bool=True):
        """
        Publish/store a value with a specific key/str. If the key already exists and overwrite is False, the value won't be updated.
        Args:
            key: like a dictionnary, you use a key/str "example"
            value:
            overwrite:
            notify:

        Returns:

        """
        if value is None:
            raise ValueError("None is a reserved value and cannot be published")
        oldvalue = self._data.get(key, None)
        if oldvalue is not None:
            if not overwrite:
                return False
        self._data[key] = value
        if notify:
            self._notify_listeners(key, oldvalue, value)
        return True

    def unpublish(self, key:str):
        if key in self._data:
            oldvalue = self._data.pop(key)
            self._notify_listeners(key, oldvalue, None)

    def retrieve(self, key:str):
        return self._data.get(key)

    def subscribe(self, key:str, listener:Callable):
        """Subscribe a listener to a key, ensuring no duplicates"""
        _listeners = self._listeners.get(key, [])
        if not callable(listener):
            raise ValueError("Listener must be callable")
        if listener not in _listeners:
            _listeners.append(listener)
            self._listeners[key] = _listeners

    def unsubscribe(self, key:str, listener:Callable):
        if key in self._listeners:
            self._listeners[key].remove(listener)

    def _notify_listeners(self, key:str, oldvalue, newvalue):
        for listener in self._listeners.get(key, []):
            listener(oldvalue, newvalue)

    def clear_listeners(self, key:str):
        """
        Clear all listeners for a specific key, or all listeners if key is None.

        Args:
            key: The key to clear listeners for. If None, clear all listeners.
        """
        if key is None:
            self._listeners = {}
        elif key in self._listeners:
            self._listeners[key] = []