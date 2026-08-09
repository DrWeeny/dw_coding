from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from .series_model import SUGGESTION_ROLE

BADGE_SIZE = 10
BADGE_MARGIN = 4
BADGE_COLOR = QColor("#ff5fa2")


class SuggestionDelegate(QStyledItemDelegate):
    """Paints a small pink badge in the top-right corner of a cell that has
    a pending AI-drafted suggestion (see core.comment / Group.suggested_*).
    Clicking the badge accepts the suggestion, replacing the current value."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        super().paint(painter, option, index)
        if not index.data(SUGGESTION_ROLE):
            return

        rect = self._badge_rect(option)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(BADGE_COLOR)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(rect)
        painter.restore()

    def editorEvent(self, event, model, option: QStyleOptionViewItem, index) -> bool:
        if (
            isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and index.data(SUGGESTION_ROLE)
            and self._badge_rect(option).contains(event.position())
        ):
            accept = getattr(model, "accept_suggestion", None)
            if callable(accept):
                accept(index.row(), index.column())
            return True
        return super().editorEvent(event, model, option, index)

    @staticmethod
    def _badge_rect(option: QStyleOptionViewItem) -> QRectF:
        rect = option.rect
        x = rect.right() - BADGE_SIZE - BADGE_MARGIN
        y = rect.top() + BADGE_MARGIN
        return QRectF(x, y, BADGE_SIZE, BADGE_SIZE)
