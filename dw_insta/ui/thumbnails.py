from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap

_cache: dict[tuple[str, float, int], QPixmap] = {}


def get_thumbnail(path: Path, max_size: int = 200) -> QPixmap:
    path = Path(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return QPixmap()

    key = (str(path), mtime, max_size)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    pixmap = QPixmap(str(path))
    if not pixmap.isNull():
        pixmap = pixmap.scaled(
            QSize(max_size, max_size),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    _cache[key] = pixmap
    return pixmap


def clear_cache() -> None:
    _cache.clear()
