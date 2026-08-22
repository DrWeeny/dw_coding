from __future__ import annotations

import difflib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "library.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    filepath TEXT UNIQUE NOT NULL,
    video_id TEXT,
    title TEXT NOT NULL,
    artist TEXT,
    source_url TEXT,
    duration REAL,
    downloaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS track_tags (
    track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (track_id, tag_id)
);
"""


@dataclass
class TrackRecord:
    id: int
    title: str
    artist: str
    filepath: str
    source_url: str
    duration: Optional[float]
    downloaded_at: str
    tags: list[str]
    video_id: str = ""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


def _get_or_create_tag(conn: sqlite3.Connection, name: str) -> int:
    conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
    return conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()[0]


def upsert_track(
    *,
    filepath: str,
    title: str,
    artist: str = "",
    source_url: str = "",
    video_id: Optional[str] = None,
    duration: Optional[float] = None,
    tags: Iterable[str] = (),
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO tracks (filepath, video_id, title, artist, source_url, duration, downloaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(filepath) DO UPDATE SET
                video_id=excluded.video_id, title=excluded.title, artist=excluded.artist,
                source_url=excluded.source_url, duration=excluded.duration
            """,
            (filepath, video_id, title, artist, source_url, duration, datetime.now(timezone.utc).isoformat()),
        )
        track_id = conn.execute("SELECT id FROM tracks WHERE filepath = ?", (filepath,)).fetchone()[0]

        for tag in tags:
            tag = tag.strip().lower()
            if not tag:
                continue
            tag_id = _get_or_create_tag(conn, tag)
            conn.execute("INSERT OR IGNORE INTO track_tags (track_id, tag_id) VALUES (?, ?)", (track_id, tag_id))


def update_track_filepath(track_id: int, new_filepath: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE tracks SET filepath = ? WHERE id = ?", (new_filepath, track_id))


def delete_track(track_id: int) -> None:
    """Drop a track from the library. track_tags rows cascade via the FK."""
    with _connect() as conn:
        conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))


def add_tag_to_tracks(tag: str, track_ids: Iterable[int]) -> None:
    """Add one tag to several tracks without touching their other tags."""
    tag = tag.strip().lower()
    if not tag:
        return
    with _connect() as conn:
        tag_id = _get_or_create_tag(conn, tag)
        for track_id in track_ids:
            conn.execute("INSERT OR IGNORE INTO track_tags (track_id, tag_id) VALUES (?, ?)", (track_id, tag_id))


def set_track_tags(track_id: int, tags: Iterable[str]) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM track_tags WHERE track_id = ?", (track_id,))
        for tag in tags:
            tag = tag.strip().lower()
            if not tag:
                continue
            tag_id = _get_or_create_tag(conn, tag)
            conn.execute("INSERT OR IGNORE INTO track_tags (track_id, tag_id) VALUES (?, ?)", (track_id, tag_id))


def get_all_tags() -> list[str]:
    with _connect() as conn:
        return [row[0] for row in conn.execute("SELECT name FROM tags ORDER BY name").fetchall()]


def get_all_titles() -> list[str]:
    with _connect() as conn:
        return [row[0] for row in conn.execute("SELECT title FROM tracks").fetchall()]


def find_similar_titles(title: str, candidates: Iterable[str], threshold: float = 0.82) -> list[str]:
    """Fuzzy-match title against candidates (e.g. existing library titles).
    Threshold 0.82 catches near-duplicates (remixes/re-uploads with minor
    naming differences) without flagging genuinely different songs."""
    title_lower = title.lower()
    matches = []
    for candidate in candidates:
        ratio = difflib.SequenceMatcher(None, title_lower, candidate.lower()).ratio()
        if ratio >= threshold:
            matches.append(candidate)
    return matches


def known_filepaths() -> set[str]:
    with _connect() as conn:
        return {row[0] for row in conn.execute("SELECT filepath FROM tracks").fetchall()}


def get_tracks(tag_filter: Optional[list[str]] = None, search: str = "") -> list[TrackRecord]:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM tracks ORDER BY downloaded_at DESC").fetchall()

        records = []
        search_lower = search.lower().strip()
        for row in rows:
            tags = [
                r[0]
                for r in conn.execute(
                    "SELECT t.name FROM tags t JOIN track_tags tt ON tt.tag_id = t.id "
                    "WHERE tt.track_id = ? ORDER BY t.name",
                    (row["id"],),
                ).fetchall()
            ]
            if tag_filter and not (set(tag_filter) & set(tags)):
                continue
            if search_lower and search_lower not in row["title"].lower() and search_lower not in (row["artist"] or "").lower():
                continue
            records.append(
                TrackRecord(
                    id=row["id"],
                    title=row["title"],
                    artist=row["artist"] or "",
                    filepath=row["filepath"],
                    source_url=row["source_url"] or "",
                    duration=row["duration"],
                    downloaded_at=row["downloaded_at"],
                    tags=tags,
                    video_id=row["video_id"] or "",
                )
            )
    return records
