from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    """A titled section with a colored header button that shows/hides its
    content when clicked. Used for the "AI" notes/actions block so it can
    be tucked away once you're done setting it up for a series."""

    def __init__(
        self,
        title: str,
        color: str = "#2f6fed",
        expanded: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._title = title

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(expanded)
        self.toggle_btn.clicked.connect(self._on_toggled)
        self.toggle_btn.setStyleSheet(
            f"QPushButton {{ background-color: {color}; color: white; font-weight: bold; "
            "text-align: left; padding: 6px 10px; border: none; border-radius: 3px; }}"
        )
        outer.addWidget(self.toggle_btn)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        outer.addWidget(self.content)

        self._update_title()
        self.content.setVisible(expanded)

    def _on_toggled(self, checked: bool) -> None:
        self.content.setVisible(checked)
        self._update_title()

    def _update_title(self) -> None:
        arrow = "▾" if self.toggle_btn.isChecked() else "▸"
        self.toggle_btn.setText(f"{arrow}  {self._title}")
