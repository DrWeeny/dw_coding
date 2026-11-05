from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget


class HashtagChip(QWidget):
    """A single removable hashtag pill, e.g. '#paris  x'. A chip past the
    hashtag cap is dimmed since it won't be copied; clicking it brings it
    back in."""

    removed = Signal(str)
    promoted = Signal(str)

    def __init__(self, tag: str, over_cap: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.tag = tag
        self.over_cap = over_cap
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

        if over_cap:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Over the hashtag cap, so it won't be copied. Click to use it instead of the last one.")

        background = "#1c1c1c" if over_cap else "#2a2a2a"
        text = "#777" if over_cap else "#eee"
        self.setStyleSheet(
            f"HashtagChip {{ background-color: {background}; border-radius: 12px; }}"
            f"QLabel {{ color: {text}; background: transparent; }}"
            "QToolButton { color: #999; border: none; background: transparent; }"
            "QToolButton:hover { color: #ff5fa2; }"
        )

    def mouseReleaseEvent(self, event) -> None:
        if self.over_cap and event.button() == Qt.MouseButton.LeftButton:
            self.promoted.emit(self.tag)
        super().mouseReleaseEvent(event)
