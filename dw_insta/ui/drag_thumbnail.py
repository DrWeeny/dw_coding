from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDrag, QMouseEvent, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from .thumbnails import get_thumbnail


class DraggableThumbnail(QLabel):
    """Shows a photo thumbnail and lets it be dragged out onto another
    application (e.g. dropped onto Chrome's Instagram upload dropzone) as
    a real OS-level file drag, same as dragging from Explorer."""

    def __init__(
        self,
        photo_path: Optional[Path] = None,
        size: int = 200,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._photo_path: Optional[Path] = None
        self._size = size
        self._drag_start: Optional[QPoint] = None

        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #202020; border: 1px solid #444;")

        if photo_path is not None:
            self.set_photo(photo_path)

    def set_photo(self, photo_path: Path) -> None:
        self._photo_path = Path(photo_path)
        self.setPixmap(get_thumbnail(self._photo_path, self._size))
        self.setToolTip(self._photo_path.name)

    def clear_photo(self) -> None:
        self._photo_path = None
        self.clear()
        self.setToolTip("")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._photo_path is not None
            and self._drag_start is not None
            and bool(event.buttons() & Qt.MouseButton.LeftButton)
        ):
            distance = (event.position().toPoint() - self._drag_start).manhattanLength()
            if distance >= 10:
                self._start_drag()
                self._drag_start = None
        super().mouseMoveEvent(event)

    def _start_drag(self) -> None:
        if self._photo_path is None or not self._photo_path.is_file():
            return

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self._photo_path))])

        drag = QDrag(self)
        drag.setMimeData(mime)

        pixmap: QPixmap = self.pixmap()
        if pixmap is not None and not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))

        drag.exec(Qt.DropAction.CopyAction)
