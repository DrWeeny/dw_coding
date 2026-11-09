from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication

from config import AppConfig
from core.process_4x5 import process_series
from core.scanner import sync_series
from core.series import SeriesState


class SeriesStore(QObject):
    """The one SeriesState every widget shares. Each widget used to load its
    own copy and save the whole file, so whichever saved last wiped what the
    others had written.

    Every change goes through mutate(): re-read the file if something else
    wrote it (an AI suggestion pass edits it directly), apply the change,
    save, then tell everyone. A state object can be replaced by that re-read,
    so widgets look groups up by id inside the callable and re-fetch what
    they hold on changed."""

    changed = Signal()
    flush_requested = Signal()  # write any edit still waiting on a debounce
    warning = Signal(str)  # something the user should read, e.g. a recovered file

    def __init__(self, config: AppConfig, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.config = config
        self._state: Optional[SeriesState] = None
        self._disk_stamp: Optional[int] = None
        self._day = date.today()

        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_application_state_changed)

    @property
    def state(self) -> Optional[SeriesState]:
        return self._state

    def open_series(self, name: str) -> dict[str, list[str]]:
        """Process and load a series folder, make it the active one, and
        return process_series' report."""
        self.flush()
        series_dir = Path(self.config.root_dir) / name
        report = process_series(series_dir)
        state = sync_series(series_dir)
        state.save()
        self._adopt(state)
        self._disk_stamp = self._read_stamp()
        self.config.active_series = name
        self.config.save()
        self.changed.emit()
        return report

    def clear(self) -> None:
        self.flush()
        self._state = None
        self._disk_stamp = None
        self.changed.emit()

    def flush(self) -> None:
        self.flush_requested.emit()

    def mutate(self, change: Callable[[SeriesState], object]) -> object:
        """Apply change(state), save, notify, and return what it returned. If
        change raises, nothing is saved and the exception reaches the caller."""
        if self._state is None:
            return None
        reloaded = self._reload_from_disk()
        try:
            result = change(self._state)
        except Exception:
            if reloaded:
                self.changed.emit()
            raise
        self._state.save()
        self._disk_stamp = self._read_stamp()
        self.changed.emit()
        return result

    def reload_if_changed(self) -> bool:
        """Pick up a change another program made to the state file."""
        reloaded = self._reload_from_disk()
        if reloaded:
            self.changed.emit()
        return reloaded

    def _adopt(self, state: SeriesState) -> None:
        self._state = state
        if state.load_warning:
            self.warning.emit(state.load_warning)

    def _state_path(self) -> Path:
        return SeriesState.state_path(Path(self._state.source_dir))

    def _read_stamp(self) -> Optional[int]:
        try:
            return self._state_path().stat().st_mtime_ns
        except OSError:
            return None

    def _reload_from_disk(self) -> bool:
        if self._state is None:
            return False
        stamp = self._read_stamp()
        if stamp is None or stamp == self._disk_stamp:
            return False  # a deleted file is rewritten by the next save
        self._adopt(sync_series(Path(self._state.source_dir)))
        self._disk_stamp = self._read_stamp()
        return True

    def _on_application_state_changed(self, app_state: Qt.ApplicationState) -> None:
        if app_state != Qt.ApplicationState.ApplicationActive:
            return
        day_changed = date.today() != self._day
        self._day = date.today()
        if not self.reload_if_changed() and day_changed:
            self.changed.emit()
