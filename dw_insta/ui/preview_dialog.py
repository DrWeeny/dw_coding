from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .thumbnails import get_thumbnail

PREVIEW_SIZE = 800


class PreviewDialog(QDialog):
    """A larger look at one photo, opened via double-click or the table's
    right-click menu. Left/Right arrow keys (or the on-screen buttons) step
    through every row in the table without closing and reopening."""

    def __init__(
        self,
        items: list[tuple[str, Optional[Path]]],
        start_index: int = 0,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.items = items
        self.index = max(0, min(start_index, len(items) - 1)) if items else 0

        layout = QVBoxLayout(self)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(300, 300)
        layout.addWidget(self.image_label, 1)

        nav_row = QHBoxLayout()
        self.prev_btn = QPushButton("‹ Previous")
        self.prev_btn.clicked.connect(self.show_previous)
        nav_row.addWidget(self.prev_btn)
        self.position_label = QLabel()
        self.position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_row.addWidget(self.position_label, 1)
        self.next_btn = QPushButton("Next ›")
        self.next_btn.clicked.connect(self.show_next)
        nav_row.addWidget(self.next_btn)
        layout.addLayout(nav_row)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self.resize(700, 760)
        self._update_view()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Left:
            self.show_previous()
        elif event.key() == Qt.Key.Key_Right:
            self.show_next()
        else:
            super().keyPressEvent(event)

    def show_previous(self) -> None:
        if self.items:
            self.index = (self.index - 1) % len(self.items)
            self._update_view()

    def show_next(self) -> None:
        if self.items:
            self.index = (self.index + 1) % len(self.items)
            self._update_view()

    def _update_view(self) -> None:
        if not self.items:
            self.setWindowTitle("Preview")
            self.image_label.setText("(nothing to preview)")
            self.position_label.setText("")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return

        label, path = self.items[self.index]
        self.setWindowTitle(label)
        if path is not None and path.is_file():
            self.image_label.setPixmap(get_thumbnail(path, PREVIEW_SIZE))
        else:
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText("(photo not available — it may have been archived)")

        self.position_label.setText(f"{self.index + 1} / {len(self.items)}")
        multiple = len(self.items) > 1
        self.prev_btn.setEnabled(multiple)
        self.next_btn.setEnabled(multiple)
