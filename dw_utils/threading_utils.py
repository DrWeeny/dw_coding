from PySide6 import QtCore  # Or PyQt5/Qt (if using Qt.py)

from functools import lru_cache, wraps
from threading import Lock

_avatar_lock = Lock()

def thread_safe_lru_cache(maxsize=128):
    def decorator(fn):
        cached_fn = lru_cache(maxsize=maxsize)(fn)

        @wraps(fn)
        def wrapper(*args, **kwargs):
            with _avatar_lock:
                return cached_fn(*args, **kwargs)
        return wrapper
    return decorator

class WorkerSignals(QtCore.QObject):
    finished = QtCore.Signal()  # Signal to notify when thread finishes
    error = QtCore.Signal(str)  # Signal to notify errors
    result = QtCore.Signal(object)  # Signal to return the result

class UserRegistrationThread(QtCore.QThread):
    def __init__(self, os_user_name=None):
        super().__init__()
        self.os_user_name = os_user_name
        self.signals = WorkerSignals()  # Create signals object
        self._result = None

    def run(self):
        try:
            from dw_utils.comment_widget.cmds_comment_shotgun import USER  # Adjust to actual import path
            user = USER(self.os_user_name)  # Create the USER instance
            self._result = user  # Store the result
            self.signals.result.emit(user)  # Emit result signal
        except Exception as e:
            self.signals.error.emit(str(e))  # Emit error signal
        finally:
            self.signals.finished.emit()  # Emit finished signal
