from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from PIL import Image

from .series import Group, SeriesState

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

_DATETIME_ORIGINAL = 36867
_DATETIME_DIGITIZED = 36868
_EXIF_IFD = 0x8769


def read_capture_datetime(path: Path) -> datetime:
    try:
        img = Image.open(path)
        exif = img.getexif()
        if exif:
            exif_ifd = exif.get_ifd(_EXIF_IFD)
            raw = exif_ifd.get(_DATETIME_ORIGINAL) or exif_ifd.get(_DATETIME_DIGITIZED)
            if raw:
                return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def file_hash(path: Path, chunk_size: int = 1 << 16) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def sync_series(source_dir: Path, caption_template: str = "") -> SeriesState:
    """Load existing state (if any) and append newly discovered, already
    4x5-processed photos as new single-photo groups at the end, ordered by
    EXIF capture time. Grouping multiple photos into one carousel post is a
    manual UI action, not automatic here. Never touches or reorders existing
    groups."""
    source_dir = Path(source_dir)
    state = SeriesState.load(source_dir)
    if state is None:
        state = SeriesState(
            series_name=source_dir.name,
            source_dir=str(source_dir),
            caption_template=caption_template,
        )

    out_dir = state.out_dir
    known_photos = {p for g in state.groups for p in g.photos}

    candidates: list[tuple[str, datetime]] = []
    for entry in sorted(source_dir.iterdir()):
        if not entry.is_file() or entry.suffix.lower() not in IMAGE_EXTS:
            continue
        if entry.name in known_photos:
            continue
        processed = out_dir / entry.name
        if not processed.is_file():
            continue  # landscape / not yet processed -> skip for now
        candidates.append((entry.name, read_capture_datetime(entry)))

    candidates.sort(key=lambda item: item[1])

    next_index = len(state.groups)
    for name, dt in candidates:
        state.groups.append(
            Group(
                id=f"{source_dir.name}-{next_index:04d}",
                date=dt.date().isoformat(),
                photos=[name],
            )
        )
        next_index += 1

    return state
