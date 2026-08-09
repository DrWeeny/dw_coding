from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QWidget


class CarouselOrderWidget(QListWidget):
    """A small vertical stack of numbered tiles, one per photo in the
    current post. Drag to reorder — the numbers renumber to reflect the
    new position, since for a carousel post the order is exactly what you
    want direct control over (not just stepping through with prev/next).
    Click a tile to preview that photo."""

    reordered = Signal(list)  # new filename order, top to bottom
    photo_selected = Signal(int)  # newly selected row

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setFixedWidth(44)
        self.setSpacing(2)
        self.currentRowChanged.connect(self._on_current_row_changed)

    def set_photos(self, photos: list[str]) -> None:
        self.blockSignals(True)
        self.clear()
        for i, filename in enumerate(photos):
            item = QListWidgetItem(str(i + 1))
            item.setData(Qt.ItemDataRole.UserRole, filename)
            item.setToolTip(filename)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.addItem(item)
        if photos:
            self.setCurrentRow(0)
        self.blockSignals(False)

    def current_order(self) -> list[str]:
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]

    def dropEvent(self, event) -> None:
        super().dropEvent(event)
        self._renumber()
        self.reordered.emit(self.current_order())

    def _renumber(self) -> None:
        for i in range(self.count()):
            self.item(i).setText(str(i + 1))

    def _on_current_row_changed(self, row: int) -> None:
        if row >= 0:
            self.photo_selected.emit(row)
