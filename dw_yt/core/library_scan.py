from __future__ import annotations

import re
import shutil
from pathlib import Path

from core import database

AUDIO_EXTENSIONS = {".webm", ".m4a", ".opus", ".mp3", ".ogg", ".wav", ".aac", ".flac"}

# Matches the app's own "Title [videoid].ext" naming so a rescan can recover
# the video id for files the app downloaded itself.
_ID_SUFFIX_RE = re.compile(r"^(?P<title>.+) \[(?P<video_id>[\w-]+)\]$")


def unique_destination(download_dir: Path, filename: str) -> Path:
    dest = download_dir / filename
    if not dest.exists():
        return dest
    stem, ext = Path(filename).stem, Path(filename).suffix
    n = 2
    while (download_dir / f"{stem} ({n}){ext}").exists():
        n += 1
    return download_dir / f"{stem} ({n}){ext}"


def sync_library(download_dir: Path) -> int:
    """Register any audio files under download_dir that aren't in the DB yet.

    Files nested in a subfolder (the old Artist/Title layout) are moved up
    to the flat root — the subfolder name is kept as the artist — and the
    now-empty subfolder is removed. Returns the number of newly registered
    tracks.
    """
    if not download_dir.is_dir():
        return 0

    known = database.known_filepaths()
    imported = 0

    for path in sorted(download_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue

        nested = path.parent != download_dir
        if nested:
            dest = unique_destination(download_dir, path.name)
            shutil.move(str(path), str(dest))
            artist = path.parent.name
            try:
                path.parent.rmdir()
            except OSError:
                pass  # not empty (other files left behind) — leave it
            path = dest
        else:
            artist = ""

        if str(path) in known:
            continue

        match = _ID_SUFFIX_RE.match(path.stem)
        title, video_id = (match.group("title"), match.group("video_id")) if match else (path.stem, None)

        database.upsert_track(
            filepath=str(path),
            title=title,
            artist=artist,
            video_id=video_id,
        )
        imported += 1

    return imported
