from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

STATE_FILENAME = ".insta_state.json"


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

    @property
    def is_posted(self) -> bool:
        return self.posted_at is not None

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


@dataclass
class SeriesState:
    series_name: str
    source_dir: str
    caption_template: str = ""  # vibe/context notes to ground AI suggestions
    hashtags: str = ""  # recurring hashtag block for the whole series
    include_gear_line: bool = False  # append a "Shot on ..." line from EXIF
    start_date: Optional[str] = None  # ISO date; set when series is activated
    groups: list[Group] = field(default_factory=list)

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
    def load(cls, source_dir: Path) -> Optional["SeriesState"]:
        path = cls.state_path(Path(source_dir))
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        groups = [Group(**_migrate_group(g)) for g in data.pop("groups", [])]
        return cls(groups=groups, **data)

    def save(self) -> None:
        path = self.state_path(Path(self.source_dir))
        data = asdict(self)
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
