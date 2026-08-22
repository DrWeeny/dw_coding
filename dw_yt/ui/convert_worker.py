from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from core import database
from core.convert import ConvertError, convert_to_mp3


class ConvertWorker(QThread):
    finished_ok = Signal(int, Path)  # track_id, new path
    failed = Signal(int, str)  # track_id, message

    def __init__(self, track_id: int, path: Path, parent=None):
        super().__init__(parent)
        self.track_id = track_id
        self.path = path

    def run(self) -> None:
        try:
            new_path = convert_to_mp3(self.path)
        except ConvertError as exc:
            self.failed.emit(self.track_id, str(exc))
            return
        database.update_track_filepath(self.track_id, str(new_path))
        self.finished_ok.emit(self.track_id, new_path)
