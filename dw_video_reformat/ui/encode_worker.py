"""Background queue runner: encodes the dropped videos one after another."""
from __future__ import annotations

import functools

from PySide6.QtCore import QThread, Signal

from core import encode


class EncodeWorker(QThread):
    job_started = Signal(int)                 # row index
    job_progress = Signal(int, float)         # row index, 0..1 (-1 = unknown)
    job_finished = Signal(int, str, str)      # row index, status, message
    all_done = Signal()

    def __init__(
            self,
            sources: list,
            settings: encode.EncodeSettings,
            parent=None):
        super().__init__(parent)
        self._sources = list(sources)   # encode.Source objects
        self._settings = settings
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def _should_cancel(self) -> bool:
        return self._cancel

    def _emit_progress(self, row: int, fraction: float) -> None:
        self.job_progress.emit(row, fraction)

    def run(self) -> None:
        for row, source in enumerate(self._sources):
            if self._cancel:
                self.job_finished.emit(row, "cancelled", "cancelled by user")
                continue
            self.job_started.emit(row)
            result = encode.run_encode(
                source,
                self._settings,
                on_progress=functools.partial(self._emit_progress, row),
                should_cancel=self._should_cancel,
            )
            self.job_finished.emit(row, result.status, result.message)
        self.all_done.emit()
