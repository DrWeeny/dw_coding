from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QListWidget

from ui.track_list_widget import TRACK_ID_MIME


class TagListWidget(QListWidget):
    """Tag list, multi-selectable for filtering, and a drop target: drag
    tracks from the library list onto a tag here to tag them."""

    tracks_dropped = Signal(str, list)  # tag name, list[int] track ids

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(TRACK_ID_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(TRACK_ID_MIME) and self.itemAt(event.position().toPoint()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        item = self.itemAt(event.position().toPoint())
        if not item:
            return
        raw = bytes(event.mimeData().data(TRACK_ID_MIME)).decode("utf-8")
        track_ids = [int(x) for x in raw.split(",") if x]
        if track_ids:
            self.tracks_dropped.emit(item.text(), track_ids)
        event.acceptProposedAction()
