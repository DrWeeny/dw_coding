from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCalendarWidget,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class ActivateSeriesDialog(QDialog):
    """Shown the first time a series is activated, to confirm/pick the date
    its daily schedule counts from (scheduler.today_index counts elapsed
    calendar days from this date)."""

    def __init__(self, series_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f'Start posting from "{series_name}"')

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'Pick the start date for "{series_name}":'))

        self.calendar = QCalendarWidget(self)
        self.calendar.setSelectedDate(QDate.currentDate())
        layout.addWidget(self.calendar)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_date(self) -> date:
        qd = self.calendar.selectedDate()
        return date(qd.year(), qd.month(), qd.day())
