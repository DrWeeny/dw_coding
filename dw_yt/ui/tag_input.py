from __future__ import annotations

from PySide6.QtCore import Qt, QStringListModel
from PySide6.QtWidgets import QCompleter, QLineEdit


class TagLineEdit(QLineEdit):
    """QLineEdit for comma-separated tags that autocompletes whichever tag
    segment the cursor is currently in against a suggestion list, instead
    of completing the whole field."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = QStringListModel([], self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setWidget(self)
        self._completer.activated.connect(self._insert_completion)
        self.textEdited.connect(self._update_prefix)

    def set_suggestions(self, tags: list[str]) -> None:
        self._model.setStringList(tags)

    def _current_prefix(self) -> str:
        return self.text()[: self.cursorPosition()].rsplit(",", 1)[-1].strip()

    def _update_prefix(self, _text: str) -> None:
        prefix = self._current_prefix()
        if prefix:
            self._completer.setCompletionPrefix(prefix)
            self._completer.complete()
        else:
            self._completer.popup().hide()

    def _insert_completion(self, completion: str) -> None:
        text = self.text()
        cursor = self.cursorPosition()
        before, after = text[:cursor], text[cursor:]
        head = before.rsplit(",", 1)[0] + ", " if "," in before else ""
        new_text = head + completion + after
        self.setText(new_text)
        self.setCursorPosition(len(head) + len(completion))
