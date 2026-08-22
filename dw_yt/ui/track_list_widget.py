from __future__ import annotations

from PySide6.QtCore import Qt, QMimeData, QUrl
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

TRACK_ID_MIME = "application/x-dwyt-track-ids"


class TrackListWidget(QListWidget):
    """Track list that supports multi-select. Drags carry both our internal
    tag-drop format (for TagListWidget) and standard file URLs, so dragging
    a track out to another application (DaVinci, Explorer, ...) works the
    same as dragging the file itself."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def mimeData(self, items: list[QListWidgetItem]) -> QMimeData:
        records = [item.data(Qt.ItemDataRole.UserRole) for item in items]
        mime = QMimeData()
        mime.setData(TRACK_ID_MIME, ",".join(str(r.id) for r in records).encode("utf-8"))
        mime.setUrls([QUrl.fromLocalFile(r.filepath) for r in records])
        return mime
