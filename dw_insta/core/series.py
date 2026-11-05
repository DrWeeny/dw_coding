from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime
from pathlib import Path
from typing import Optional

STATE_FILENAME = ".insta_state.json"
BACKUP_SUFFIX = ".bak"

# What a damaged or incompatible state file can raise while being parsed.
_PARSE_ERRORS = (ValueError, TypeError, AttributeError, KeyError)


@dataclass
class Group:
    id: str
    date: str  # ISO date from EXIF grouping (informational)
    photos: list[str]  # filenames, in post order
    caption: Optional[str] = None  # confirmed English caption for the whole post
    caption_ja: Optional[str] = None  # optional Japanese translation
    hashtags: Optional[str] = None  # None -> fall back to SeriesState.hashtags
    # AI-drafted, not yet accepted — keyed by filename rather than a single
    # value so that merging photos into a carousel doesn't collide/discard
    # drafts, and each photo's suggestion survives a later split.
    suggested_captions: dict[str, str] = field(default_factory=dict)
    suggested_hashtags: dict[str, str] = field(default_factory=dict)
    posted_at: Optional[str] = None  # ISO datetime, set on archive
    skipped: bool = False  # decided not worth posting; files stay where they are

    @property
    def is_posted(self) -> bool:
        return self.posted_at is not None

    @property
    def is_pending(self) -> bool:
        """Still waiting in the posting queue."""
        return not self.is_posted and not self.skipped

    @property
    def has_suggestion(self) -> bool:
        return bool(self.suggested_captions or self.suggested_hashtags)

    def primary_suggested_caption(self) -> Optional[tuple[str, str]]:
        """(filename, text) for the earliest-in-post-order photo with a
        pending suggested caption, or None. Used wherever a suggestion is
        shown/accepted at the whole-post level (e.g. the series table) as
        opposed to for one specific photo (e.g. the Today widget carousel)."""
        for filename in self.photos:
            if filename in self.suggested_captions:
                return filename, self.suggested_captions[filename]
        return None

    def primary_suggested_hashtags(self) -> Optional[tuple[str, str]]:
        for filename in self.photos:
            if filename in self.suggested_hashtags:
                return filename, self.suggested_hashtags[filename]
        return None


def _migrate_group(raw: dict) -> dict:
    """Upgrade a group dict loaded from an older .insta_state.json, where
    suggested_caption/suggested_hashtags were single strings, to the
    current per-photo dict shape — keyed by the group's first photo, since
    that's the only photo a pre-migration group could have had a pending
    suggestion for. Leaves already-migrated (dict-shaped) data untouched."""
    raw = dict(raw)
    photos = raw.get("photos") or []
    first_photo = photos[0] if photos else None

    old_caption = raw.pop("suggested_caption", None)
    captions = raw.get("suggested_captions")
    captions = dict(captions) if isinstance(captions, dict) else {}
    if isinstance(old_caption, str) and old_caption and first_photo:
        captions.setdefault(first_photo, old_caption)
    raw["suggested_captions"] = captions

    old_hashtags = raw.get("suggested_hashtags")
    if isinstance(old_hashtags, dict):
        hashtags = dict(old_hashtags)
    elif isinstance(old_hashtags, str) and old_hashtags and first_photo:
        hashtags = {first_photo: old_hashtags}
    else:
        hashtags = {}
    raw["suggested_hashtags"] = hashtags

    return raw


def _known_fields(cls: type, raw: dict) -> dict:
    """Drop keys the dataclass doesn't declare, so a state or config file
    written by a newer copy of the tool on another computer still loads."""
    names = {f.name for f in fields(cls)}
    return {key: value for key, value in raw.items() if key in names}


@dataclass
class SeriesState:
    series_name: str
    source_dir: str
    caption_template: str = ""  # vibe/context notes to ground AI suggestions
    hashtags: str = ""  # recurring hashtag block for the whole series
    include_gear_line: bool = False  # append a "Shot on ..." line from EXIF
    start_date: Optional[str] = None  # ISO date; don't plan posts before this day
    groups: list[Group] = field(default_factory=list)

    # Not a dataclass field (no annotation), so it never reaches the json.
    # Set when load() had to recover from a damaged state file.
    load_warning = None

    @property
    def out_dir(self) -> Path:
        return Path(self.source_dir) / "out_4x5"

    @property
    def archive_source_dir(self) -> Path:
        return Path(self.source_dir) / "archived"

    @property
    def archive_out_dir(self) -> Path:
        return self.out_dir / "archived"

    @staticmethod
    def state_path(source_dir: Path) -> Path:
        return Path(source_dir) / STATE_FILENAME

    @classmethod
    def _parse(cls, path: Path) -> "SeriesState":
        data = dict(json.loads(path.read_text(encoding="utf-8")))
        groups = [Group(**_known_fields(Group, _migrate_group(g))) for g in data.pop("groups", [])]
        state = cls(groups=groups, **_known_fields(cls, data))
        state._repair_duplicate_ids()
        return state

    @classmethod
    def load(cls, source_dir: Path) -> Optional["SeriesState"]:
        path = cls.state_path(Path(source_dir))
        if not path.is_file():
            return None
        try:
            return cls._parse(path)
        except _PARSE_ERRORS as exc:
            return cls._recover(Path(source_dir), exc)

    @classmethod
    def _recover(cls, source_dir: Path, error: Exception) -> "SeriesState":
        """A damaged state file must not stop the app, and must not be
        overwritten either: it holds the only record of what was posted. Move
        it aside, then fall back to the backup save() keeps."""
        path = cls.state_path(source_dir)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        aside = path.with_name(f"{STATE_FILENAME}.corrupt-{stamp}")
        os.replace(path, aside)

        backup = path.with_name(STATE_FILENAME + BACKUP_SUFFIX)
        try:
            state = cls._parse(backup)
            outcome = "Restored the last backup, so the most recent change may be missing."
        except (OSError,) + _PARSE_ERRORS:
            state = cls(series_name=source_dir.name, source_dir=str(source_dir))
            outcome = "No usable backup was found, so the series starts empty."
        state.load_warning = (
            f"{path.name} in {source_dir.name} could not be read ({error}).\n"
            f"{outcome}\nThe damaged file was kept as {aside.name}."
        )
        return state

    def find_group(self, group_id: str) -> Optional[Group]:
        return next((g for g in self.groups if g.id == group_id), None)

    def next_group_id(self) -> str:
        """An id no current group uses. Never derive one from len(groups)
        alone: a merge shrinks the list while the higher ids stay in use, so
        the length points straight back at an id that's already taken."""
        taken = {g.id for g in self.groups}
        index = len(self.groups)
        while f"{self.series_name}-{index:04d}" in taken:
            index += 1
        return f"{self.series_name}-{index:04d}"

    def _repair_duplicate_ids(self) -> None:
        """Heal state files written while the scanner could reissue a taken
        id. The first occurrence keeps its id and later ones get a new one.
        Deterministic, so reloading the same file always gives the same ids.
        Nothing outside this file refers to a group id, so renaming one is
        safe."""
        seen: set[str] = set()
        for group in self.groups:
            if group.id in seen:
                group.id = self.next_group_id()
            seen.add(group.id)

    def save(self) -> None:
        path = self.state_path(Path(self.source_dir))
        data = asdict(self)
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            if path.is_file():
                shutil.copy2(path, path.with_name(STATE_FILENAME + BACKUP_SUFFIX))
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
