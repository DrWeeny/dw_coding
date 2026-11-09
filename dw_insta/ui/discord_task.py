from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from core.discord_post import post_photo_to_discord


class _DiscordSignals(QObject):
    finished = Signal(str, str)  # filename, error message ("" when it worked)


class DiscordPostTask(QRunnable):
    """Posts one photo on a pool thread, so a slow upload can't freeze the UI.
    The caller keeps a reference until finished fires."""

    def __init__(self, webhook_url: str, photo_path: Path) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.webhook_url = webhook_url
        self.photo_path = photo_path
        self.signals = _DiscordSignals()

    def run(self) -> None:
        error = ""
        try:
            post_photo_to_discord(self.webhook_url, self.photo_path)
        except Exception as exc:
            error = str(exc)
        self.signals.finished.emit(self.photo_path.name, error)
