from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget


class TagChip(QWidget):
    """One tag pill. Removable (active tag on a track — an x button drops
    it) or not (a suggestion — clicking the whole chip adds it)."""

    removed = Signal(str)
    activated = Signal(str)

    def __init__(self, tag: str, removable: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.tag = tag
        self.removable = removable
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("activeTagChip" if removable else "suggestedTagChip")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 6 if removable else 10, 3)
        layout.setSpacing(4)
        layout.addWidget(QLabel(tag))

        if removable:
            remove_btn = QToolButton()
            remove_btn.setText("✕")
            remove_btn.setAutoRaise(True)
            remove_btn.clicked.connect(lambda: self.removed.emit(self.tag))
            layout.addWidget(remove_btn)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip(f'Click to add "{tag}"')

        self.setStyleSheet(
            "#activeTagChip { background-color: #2a5d34; border-radius: 10px; }"
            "#suggestedTagChip { background-color: #3a3a3a; border-radius: 10px; }"
            "#suggestedTagChip:hover { background-color: #4a4a4a; }"
            "QLabel { background: transparent; }"
            "QToolButton { border: none; background: transparent; }"
            "QToolButton:hover { color: #ff5f5f; }"
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.removable:
            self.activated.emit(self.tag)
        super().mousePressEvent(event)
