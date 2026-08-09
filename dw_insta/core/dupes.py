from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .scanner import IMAGE_EXTS, file_hash

SKIP_DIRS = {"out_4x5", "archived"}


def find_cross_series_duplicates(root_dir: Path) -> dict[str, list[Path]]:
    """Hash every top-level photo in every series folder and return groups
    of files that are byte-identical across two or more series."""
    root_dir = Path(root_dir)
    by_hash: dict[str, list[Path]] = defaultdict(list)

    for series_dir in sorted(p for p in root_dir.iterdir() if p.is_dir()):
        if series_dir.name in SKIP_DIRS:
            continue
        for entry in series_dir.iterdir():
            if not entry.is_file() or entry.suffix.lower() not in IMAGE_EXTS:
                continue
            by_hash[file_hash(entry)].append(entry)

    return {h: paths for h, paths in by_hash.items() if len({p.parent for p in paths}) > 1}
