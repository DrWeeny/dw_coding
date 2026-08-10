from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt

from core.comment import accept_caption_suggestion, accept_hashtags_suggestion
from core.paths import resolve_group_cover
from core.series import Group, SeriesState

from .thumbnails import get_thumbnail

COL_PHOTOS = 0
COL_DATE = 1
COL_CAPTION = 2
COL_HASHTAGS = 3
COL_STATUS = 4

HEADERS = ["Photos", "Date", "Caption", "Hashtags", "Status"]
EDITABLE_COLUMNS = {COL_CAPTION, COL_HASHTAGS}
DEFAULT_THUMB_SIZE = 48

SUGGESTION_ROLE = Qt.ItemDataRole.UserRole + 1


class SeriesTableModel(QAbstractTableModel):
    """Thin Qt wrapper around SeriesState.groups. Every edit/accept saves
    the state file immediately (it's small JSON, no reason to batch)."""

    def __init__(
        self,
        state: SeriesState,
        thumb_size: int = DEFAULT_THUMB_SIZE,
        hide_archived: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.state = state
        self.thumb_size = thumb_size
        self.hide_archived = hide_archived
        self._visible_groups: list[Group] = []
        self._rebuild_visible()

    def _rebuild_visible(self) -> None:
        if self.hide_archived:
            self._visible_groups = [g for g in self.state.groups if not g.is_posted]
        else:
            self._visible_groups = list(self.state.groups)

    def set_thumb_size(self, size: int) -> None:
        self.thumb_size = size
        self.refresh()

    def set_hide_archived(self, hide: bool) -> None:
        self.hide_archived = hide
        self.refresh()

    def visible_groups(self) -> list[Group]:
        return list(self._visible_groups)

    def group_at(self, row: int) -> Group:
        return self._visible_groups[row]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._visible_groups)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        group = self.group_at(index.row())
        col = index.column()

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == COL_PHOTOS:
                return ", ".join(group.photos)
            if col == COL_DATE:
                return group.date
            if col == COL_CAPTION:
                return group.caption or ""
            if col == COL_HASHTAGS:
                return group.hashtags if group.hashtags is not None else ""
            if col == COL_STATUS:
                return "posted" if group.is_posted else "pending"

        if role == Qt.ItemDataRole.DecorationRole and col == COL_PHOTOS and group.photos:
            cover = resolve_group_cover(self.state, group)
            if cover is not None:
                return get_thumbnail(cover, self.thumb_size)

        if role == Qt.ItemDataRole.SizeHintRole and col == COL_PHOTOS:
            return QSize(self.thumb_size + 8, self.thumb_size + 8)

        if role == SUGGESTION_ROLE:
            if col == COL_CAPTION:
                pending = group.primary_suggested_caption()
                return pending[1] if pending else None
            if col == COL_HASHTAGS:
                pending = group.primary_suggested_hashtags()
                return pending[1] if pending else None

        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        group = self.group_at(index.row())
        col = index.column()

        if col == COL_CAPTION:
            group.caption = value or None
        elif col == COL_HASHTAGS:
            group.hashtags = value or None
        else:
            return False

        self.state.save()
        self.dataChanged.emit(index, index, [role])
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() in EDITABLE_COLUMNS:
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    def accept_suggestion(self, row: int, column: int) -> None:
        group = self.group_at(row)
        if column == COL_CAPTION:
            accepted = accept_caption_suggestion(group)
        elif column == COL_HASHTAGS:
            accepted = accept_hashtags_suggestion(group)
        else:
            return
        if not accepted:
            return
        self.state.save()
        idx = self.index(row, column)
        self.dataChanged.emit(idx, idx)

    def refresh(self) -> None:
        self.beginResetModel()
        self._rebuild_visible()
        self.endResetModel()
