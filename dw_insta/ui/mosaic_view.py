from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QAbstractItemView, QListView, QListWidget, QListWidgetItem, QWidget

from core.paths import resolve_group_cover
from core.series import SeriesState

from .thumbnails import get_thumbnail

DEFAULT_ICON_SIZE = 120


class MosaicView(QListWidget):
    """Grid of every post in the series — drag to reorder the posting
    sequence directly. Always shows the full series regardless of the
    hide-archived filter, since reordering needs the true absolute order
    (see MainWindow._set_as_today for the same concern elsewhere)."""

    reordered = Signal(list)  # new order of group ids, top-left to bottom-right

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Snap)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSpacing(8)
        self.setWordWrap(True)
        self.set_icon_size(DEFAULT_ICON_SIZE)

    def set_icon_size(self, size: int) -> None:
        self.setIconSize(QSize(size, size))
        self.setGridSize(QSize(size + 24, size + 44))

    def populate(self, state: SeriesState) -> None:
        self.blockSignals(True)
        self.clear()
        for group in state.groups:
            cover = resolve_group_cover(state, group)
            item = QListWidgetItem()
            if cover is not None:
                item.setIcon(QIcon(get_thumbnail(cover, self.iconSize().width())))
            label = group.date
            if len(group.photos) > 1:
                label += f" ({len(group.photos)})"
            if group.is_posted:
                label += " ✓"
            item.setText(label)
            item.setData(Qt.ItemDataRole.UserRole, group.id)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.addItem(item)
        self.blockSignals(False)

    def dropEvent(self, event) -> None:
        super().dropEvent(event)
        order = [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]
        self.reordered.emit(order)
