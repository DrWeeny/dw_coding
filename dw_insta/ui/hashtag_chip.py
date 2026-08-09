from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget


class HashtagChip(QWidget):
    """A single removable hashtag pill, e.g. '#paris  x'."""

    removed = Signal(str)

    def __init__(self, tag: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.tag = tag
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 6, 4)
        layout.setSpacing(4)

        layout.addWidget(QLabel(tag))

        remove_btn = QToolButton()
        remove_btn.setText("✕")
        remove_btn.setAutoRaise(True)
        remove_btn.clicked.connect(lambda: self.removed.emit(self.tag))
        layout.addWidget(remove_btn)

        self.setStyleSheet(
            "HashtagChip { background-color: #2a2a2a; border-radius: 12px; }"
            "QLabel { color: #eee; background: transparent; }"
            "QToolButton { color: #999; border: none; background: transparent; }"
            "QToolButton:hover { color: #ff5fa2; }"
        )
