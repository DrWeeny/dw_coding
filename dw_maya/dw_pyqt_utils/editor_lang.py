#!/usr/bin/env python
#----------------------------------------------------------------------------#
#------------------------------------------------------------------ HEADER --#

"""
@description:
    This module provides a custom QTextEdit with Python syntax highlighting and word autocompletion.
"""

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#

# PySide6 imports and other necessary modules
from maya import cmds, mel
from PySide6 import QtWidgets, QtCore, QtGui
from . import syntax_py

#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#

class DictionaryCompleter(QtWidgets.QCompleter):
    """A QCompleter that autocompletes words from a provided dictionary list."""

    def __init__(self, words=None, parent=None):
        super().__init__(words or self.default_words(), parent)

    @staticmethod
    def default_words():
        """Return a default list of words for autocompletion."""
        return [
            'apple', 'aggresive', 'ball', 'bat', 'cat', 'cycle', 'dog', 'dumb',
            'elephant', 'engineer', 'food', 'file', 'good', 'great',
            'hippopotamus', 'hyper', 'india', 'ireland', 'just', 'key', 'kid',
            'lemon', 'lead', 'mute', 'magic', 'news', 'newyork', 'orange', 'oval',
            'parrot', 'patriot', 'question', 'queue', 'right', 'rest', 'smile',
            'simple', 'tree', 'urban', 'very', 'wood', 'xylophone', 'yellow', 'zebra'
        ]


class TextLang(QtWidgets.QTextEdit):
    """A QTextEdit with Python syntax highlighting and autocompletion."""

    def __init__(self, parent=None, text=None, syntax="python", completer=None):
        super().__init__(parent)

        # Initialize syntax highlighting
        if syntax == "python":
            self._syntax = syntax_py.PythonHighlighter(self.document())
        else:
            raise NotImplementedError("This editor currently supports only Python syntax highlighting.")

        self.completer = None  # Placeholder for completer
        if text:
            self.setText(text)
        if completer:
            self.setCompleter(completer)

    def setText(self, text):
        """Set plain text in the editor."""
        self.setPlainText(text)

    def setCompleter(self, words):
        """Set a new completer with a list of words."""
        completer = DictionaryCompleter(words)
        self._initialize_completion(completer)

    def _initialize_completion(self, completer):
        """Configure the completion behavior."""
        if self.completer:
            self.completer.activated.disconnect(self.insertCompletion)
        completer.setWidget(self)
        completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.completer = completer
        self.completer.activated.connect(self.insertCompletion)

    def insertCompletion(self, completion):
        """Insert the selected completion text into the editor."""
        tc = self.textCursor()
        extra_length = len(completion) - len(self.completer.completionPrefix())
        tc.movePosition(QtGui.QTextCursor.Left)
        tc.movePosition(QtGui.QTextCursor.EndOfWord)
        tc.insertText(completion[-extra_length:])
        self.setTextCursor(tc)

    def textUnderCursor(self):
        """Retrieve the text under the cursor for autocompletion purposes."""
        tc = self.textCursor()
        tc.select(QtGui.QTextCursor.WordUnderCursor)
        return tc.selectedText()
