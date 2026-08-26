from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.artist_lookup import suggest_artist


class ArtistLookupWorker(QThread):
    finished_ok = Signal(object)  # ArtistSuggestion | None
    failed = Signal(str)

    def __init__(self, webpage_url: str, title: str, parent=None):
        super().__init__(parent)
        self.webpage_url = webpage_url
        self.title = title

    def run(self) -> None:
        try:
            suggestion = suggest_artist(self.webpage_url, self.title)
        except Exception as exc:  # best-effort lookup — never let it crash the app
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(suggestion)
