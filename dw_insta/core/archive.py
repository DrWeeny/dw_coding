from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from .series import Group, SeriesState


def archive_group(state: SeriesState, group: Group) -> None:
    source_dir = Path(state.source_dir)
    out_dir = state.out_dir
    state.archive_source_dir.mkdir(exist_ok=True)
    state.archive_out_dir.mkdir(parents=True, exist_ok=True)

    for filename in group.photos:
        src_original = source_dir / filename
        if src_original.is_file():
            shutil.move(str(src_original), str(state.archive_source_dir / filename))

        src_out = out_dir / filename
        if src_out.is_file():
            shutil.move(str(src_out), str(state.archive_out_dir / filename))

    group.posted_at = datetime.now().isoformat(timespec="seconds")
    state.save()


def unarchive_group(state: SeriesState, group: Group) -> None:
    source_dir = Path(state.source_dir)
    out_dir = state.out_dir

    for filename in group.photos:
        archived_original = state.archive_source_dir / filename
        if archived_original.is_file():
            shutil.move(str(archived_original), str(source_dir / filename))

        archived_out = state.archive_out_dir / filename
        if archived_out.is_file():
            shutil.move(str(archived_out), str(out_dir / filename))

    group.posted_at = None
    state.save()
