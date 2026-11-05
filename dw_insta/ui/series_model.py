from __future__ import annotations

from datetime import date

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt

from core.comment import accept_caption_suggestion, accept_hashtags_suggestion
from core.paths import resolve_group_cover
from core.scheduler import planned_dates
from core.series import Group, SeriesState

from .series_store import SeriesStore
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
    """Thin Qt wrapper over the store's current series. Every edit goes
    through the store, which saves and calls refresh() back via MainWindow."""

    def __init__(
        self,
        store: SeriesStore,
        thumb_size: int = DEFAULT_THUMB_SIZE,
        hide_archived: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.thumb_size = thumb_size
        self.hide_archived = hide_archived
        self._visible_groups: list[Group] = []
        self._planned: dict[str, date] = {}
        self._rebuild_visible()

    @property
    def state(self) -> SeriesState | None:
        return self.store.state

    def _compute_visible(self) -> list[Group]:
        if self.state is None:
            return []
        if self.hide_archived:
            return [g for g in self.state.groups if g.is_pending]
        return list(self.state.groups)

    def _rebuild_visible(self) -> None:
        self._visible_groups = self._compute_visible()
        self._planned = planned_dates(self.state) if self.state else {}

    def set_thumb_size(self, size: int) -> None:
        self.thumb_size = size
        self._reset()

    def set_hide_archived(self, hide: bool) -> None:
        self.hide_archived = hide
        self._reset()

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

    def _status_text(self, group: Group) -> str:
        if group.is_posted:
            return "posted"
        if group.skipped:
            return "skipped"
        planned = self._planned.get(group.id)
        if planned is None:
            return "pending"
        return "today" if planned == date.today() else planned.strftime("%b %d")

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
                return self._status_text(group)

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
        col = index.column()
        if col not in EDITABLE_COLUMNS:
            return False
        group_id = self.group_at(index.row()).id

        def apply(state: SeriesState) -> None:
            group = state.find_group(group_id)
            if group is None:
                return
            if col == COL_CAPTION:
                group.caption = value or None
            else:
                group.hashtags = value or None

        self.store.mutate(apply)
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() in EDITABLE_COLUMNS:
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    def accept_suggestion(self, row: int, column: int) -> None:
        accept = {COL_CAPTION: accept_caption_suggestion, COL_HASHTAGS: accept_hashtags_suggestion}.get(column)
        if accept is None:
            return
        group_id = self.group_at(row).id

        def apply(state: SeriesState) -> None:
            group = state.find_group(group_id)
            if group is not None:
                accept(group)

        self.store.mutate(apply)

    def refresh(self) -> None:
        """Pick up the store's current content. A reset would drop the table's
        selection and scroll position, and this runs on every save, so it only
        happens when the rows themselves changed."""
        visible = self._compute_visible()
        if [g.id for g in visible] != [g.id for g in self._visible_groups]:
            self._reset()
            return
        self._rebuild_visible()
        if visible:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(visible) - 1, len(HEADERS) - 1)
            self.dataChanged.emit(top_left, bottom_right)

    def _reset(self) -> None:
        self.beginResetModel()
        self._rebuild_visible()
        self.endResetModel()
