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
    caption: Optional[str] = None  # confirmed English caption
    caption_ja: Optional[str] = None  # optional Japanese translation
    hashtags: Optional[str] = None  # None -> fall back to SeriesState.hashtags
    suggested_caption: Optional[str] = None  # AI-drafted, not yet accepted
    suggested_hashtags: Optional[str] = None  # AI-drafted, not yet accepted
    posted_at: Optional[str] = None  # ISO datetime, set on archive

    @property
    def is_posted(self) -> bool:
        return self.posted_at is not None

    @property
    def has_suggestion(self) -> bool:
        return bool(
            (self.suggested_caption and self.suggested_caption != self.caption)
            or (self.suggested_hashtags and self.suggested_hashtags != self.hashtags)
        )


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
        groups = [Group(**g) for g in data.pop("groups", [])]
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
