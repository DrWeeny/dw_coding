from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from ui.tag_input import TagLineEdit


class AddTagDialog(QDialog):
    """Tag(s) to add to whatever tracks are selected — additive, doesn't
    touch tags those tracks already have."""

    def __init__(self, suggestions: list[str], count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Tag")

        layout = QVBoxLayout(self)
        noun = "track" if count == 1 else "tracks"
        layout.addWidget(QLabel(f"Tag(s) to add to {count} {noun} (comma-separated):"))

        self.input = TagLineEdit()
        self.input.set_suggestions(suggestions)
        layout.addWidget(self.input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.input.setFocus()

    def tags(self) -> list[str]:
        return [t.strip() for t in self.input.text().split(",") if t.strip()]
