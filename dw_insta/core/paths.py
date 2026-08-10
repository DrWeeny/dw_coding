from __future__ import annotations

from pathlib import Path
from typing import Optional

from .series import Group, SeriesState


def resolve_photo_path(state: SeriesState, filename: str) -> Optional[Path]:
    """Find where a photo currently lives: normally out_dir, but it may
    have moved to archived/out_dir if its group was marked posted."""
    for candidate in (state.out_dir / filename, state.archive_out_dir / filename):
        if candidate.is_file():
            return candidate
    return None


def resolve_original_photo_path(state: SeriesState, filename: str) -> Optional[Path]:
    """Find the original, pre-4x5-crop photo — for uses that don't need
    Instagram's aspect ratio, e.g. posting to Discord."""
    for candidate in (Path(state.source_dir) / filename, state.archive_source_dir / filename):
        if candidate.is_file():
            return candidate
    return None


def resolve_group_cover(state: SeriesState, group: Group) -> Optional[Path]:
    if not group.photos:
        return None
    return resolve_photo_path(state, group.photos[0])
