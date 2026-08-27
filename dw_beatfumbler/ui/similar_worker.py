from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.similar import SimilarError, fetch_similar


class SimilarWorker(QThread):
    finished_ok = Signal(list)  # list[SimilarTrack]
    failed = Signal(str)

    def __init__(self, artist: str, title: str, api_key: str, parent=None):
        super().__init__(parent)
        self.artist = artist
        self.title = title
        self.api_key = api_key

    def run(self) -> None:
        try:
            results = fetch_similar(self.artist, self.title, self.api_key)
        except SimilarError as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(results)
