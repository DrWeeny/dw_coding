from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from core.slug import slug_filename

# Flat: everything lands directly in download_dir. Organization is by tag
# in the library database, not by folder. This is yt-dlp's intermediate
# download name (needed since outtmpl only understands %(field)s syntax,
# not arbitrary transforms) — download_audio renames the result to a
# slugified filename afterward; the raw title is kept as the display name
# in the database either way.
OUTPUT_TEMPLATE = "%(title)s [%(id)s].%(ext)s"

ProgressHook = Callable[[dict], None]


class DownloadError(Exception):
    pass


@dataclass
class TrackResult:
    path: Path
    video_id: str
    title: str
    artist: str
    duration: Optional[float]
    webpage_url: str
    similar_titles: list[str] = field(default_factory=list)  # filled in after download, see DownloadWorker


def format_speed(speed: Optional[float]) -> str:
    if not speed:
        return ""
    for unit in ("B/s", "KB/s", "MB/s"):
        if speed < 1024:
            return f"{speed:.0f} {unit}"
        speed /= 1024
    return f"{speed:.1f} GB/s"


def download_media(
    url: str,
    download_dir: Path,
    progress_hook: Optional[ProgressHook] = None,
    playlist: bool = False,
    video: bool = False,
    cookies_browser: str = "",
) -> list[TrackResult]:
    """Download from url — audio converted to MP3 by default (needs
    ffmpeg), or the full video (merged to MP4) when video=True. The video
    option exists for the rare case of pulling down your own uploads, not
    for general use — this app is an audio library first.

    With playlist=False (default), a playlist URL downloads only the single
    linked track. With playlist=True, every track in it is downloaded; a
    failed entry (private/deleted video) is skipped rather than aborting
    the whole batch.

    cookies_browser, if set, is a yt-dlp browser key ("chrome", "firefox",
    "edge", "brave") to pull auth cookies from — needed when YouTube gates
    a video behind an age/login check. Off by default since it reads from
    your browser's cookie store.
    """
    ydl_opts = {
        "outtmpl": str(download_dir / OUTPUT_TEMPLATE),
        "noplaylist": not playlist,
        "ignoreerrors": "only_download" if playlist else False,
        "windows_filenames": True,
        "progress_hooks": [progress_hook] if progress_hook else [],
        "quiet": True,
        "no_warnings": True,
    }

    if video:
        ydl_opts["format"] = "bestvideo+bestaudio/best"
        ydl_opts["merge_output_format"] = "mp4"
    else:
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]

    if cookies_browser:
        ydl_opts["cookiesfrombrowser"] = (cookies_browser,)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(str(exc)) from exc

    entries = info.get("entries") if info.get("_type") == "playlist" else [info]

    results = []
    for entry in entries:
        if not entry:
            continue
        requested = entry.get("requested_downloads") or [{}]
        filepath = requested[0].get("filepath")
        if not filepath:
            continue

        video_id = entry.get("id") or ""
        title = entry.get("title") or Path(filepath).stem
        path = Path(filepath)
        slug_path = path.with_name(slug_filename(title, video_id, path.suffix))
        if slug_path != path:
            path = path.replace(slug_path)  # Path.replace() overwrites atomically, unlike rename()

        results.append(
            TrackResult(
                path=path,
                video_id=video_id,
                title=title,
                artist=entry.get("artist") or entry.get("uploader") or "",
                duration=entry.get("duration"),
                webpage_url=entry.get("webpage_url") or url,
            )
        )
    return results
