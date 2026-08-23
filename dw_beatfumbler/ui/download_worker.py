from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from core import database
from core.downloader import DownloadError, download_media, format_speed


class DownloadWorker(QThread):
    progress = Signal(int, str)  # percent, status text (track counter + speed)
    finished_ok = Signal(list)  # list[TrackResult]
    failed = Signal(str)

    def __init__(
        self,
        url: str,
        download_dir: Path,
        playlist: bool = False,
        tags: list[str] | None = None,
        video: bool = False,
        cookies_browser: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.url = url
        self.download_dir = download_dir
        self.playlist = playlist
        self.tags = tags or []
        self.video = video
        self.cookies_browser = cookies_browser

    def run(self) -> None:
        try:
            results = download_media(
                self.url,
                self.download_dir,
                self._on_hook,
                playlist=self.playlist,
                video=self.video,
                cookies_browser=self.cookies_browser,
            )
        except DownloadError as exc:
            self.failed.emit(str(exc))
            return

        existing_titles = database.get_all_titles()
        for result in results:
            result.similar_titles = database.find_similar_titles(result.title, existing_titles)
            existing_titles.append(result.title)  # catch near-dupes within the same batch too

            database.upsert_track(
                filepath=str(result.path),
                title=result.title,
                artist=result.artist,
                source_url=result.webpage_url,
                video_id=result.video_id,
                duration=result.duration,
                tags=self.tags,
            )

        self.finished_ok.emit(results)

    def _on_hook(self, d: dict) -> None:
        status = d.get("status")
        if status not in ("downloading", "finished"):
            return

        # Only present when downloading as part of a playlist.
        info = d.get("info_dict") or {}
        index = info.get("playlist_index")
        count = info.get("n_entries")
        track = f"Track {index}/{count}  " if index and count else ""

        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            percent = int(downloaded / total * 100) if total else 0
            self.progress.emit(percent, f"{track}{format_speed(d.get('speed'))}".strip())
        else:
            self.progress.emit(100, track.strip())
