from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class QueueRow(QWidget):
    """One row in the download queue: a status label, a small × button to
    drop the entry before it starts downloading, and a Retry button that
    only appears once the entry has failed."""

    remove_clicked = Signal()
    retry_clicked = Signal()

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)

        self.label = QLabel(text)
        layout.addWidget(self.label, stretch=1)

        self.retry_btn = QPushButton("Retry")
        self.retry_btn.setToolTip("Try this download again")
        self.retry_btn.clicked.connect(self.retry_clicked)
        self.retry_btn.hide()
        layout.addWidget(self.retry_btn)

        self.remove_btn = QPushButton("×")
        self.remove_btn.setFixedSize(20, 20)
        self.remove_btn.setToolTip("Remove from queue")
        self.remove_btn.clicked.connect(self.remove_clicked)
        layout.addWidget(self.remove_btn)

    def set_text(self, text: str) -> None:
        self.label.setText(text)

    def show_retry(self) -> None:
        self.retry_btn.show()
