"""
User Filtering Widget for Houdini File Management Tool
------------------------------------------------------

This module provides a UI component built with PySide2 for filtering Houdini files by usernames.
It includes token-based username input, fuzzy autocompletion, and support for dynamic filtering.

The widget is intended for use in DCC pipelines where users may need to manage or isolate work
based on artists' names. It is designed to be user-friendly for artists while maintaining flexibility
and extensibility for technical users.

Main Features:
- Token-based filtering by usernames with delete buttons.
- Fuzzy autocompletion for username input.
- Customizable completer logic and styling.
- Emits signals when filters are updated for easy integration with other tools.

author:  np-c-alexis
"""

from PySide2 import QtCore, QtGui, QtWidgets
import difflib

class UserCompleter(QtWidgets.QCompleter):
    """
    Autocompleter for usernames.

    Extends QCompleter to provide fuzzy matching and improved text insertion.
    """
    def __init__(self, words:list[str]=None, parent=None):
        super().__init__(words or [], parent)

    def setWords(self, words:list[str]):
        """Set the list of words for autocompletion."""
        self.model().setStringList(words)

    def insertCompletion(self, completion):
        """Insert the selected username into the input field."""
        tc = self.widget().textCursor()
        extra_length = len(completion) - len(self.completionPrefix())
        tc.movePosition(QtGui.QTextCursor.Left)
        tc.movePosition(QtGui.QTextCursor.EndOfWord)
        tc.insertText(completion[-extra_length:])
        self.widget().setTextCursor(tc)

class LineEditWithBackspace(QtWidgets.QLineEdit):
    """
    A QLineEdit subclass that emits a signal when backspace is pressed on empty input.

    Useful for triggering token deletion.
    """
    backspacePressed = QtCore.Signal()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Backspace and not self.text():
            if self.tokens:  # Check if there are tokens
                self.remove_token(self.token_widgets[-1])  # Remove the last token
            self.backspacePressed.emit()
        else:
            super().keyPressEvent(event)

class LineEditToken(QtWidgets.QWidget):
    """
    A user filtering widget that allows filtering by username using token-based input.

    Provides features such as:
    - Username token management with delete buttons.
    - Fuzzy autocomplete support.
    - Signal emission when filters change.

    Signals:
        filterChanged (list[str]): Emitted when the active user filter list is updated.
    """
    filterChanged = QtCore.Signal(list)  # Emits list of current tokens (usernames)

    def __init__(self, parent=None):
        super(LineEditToken, self).__init__(parent)

        self.completer_selected = False

        self.tokens = []
        self.token_widgets = []

        # Layout to hold both tokens and the QLineEdit
        self.token_layout = QtWidgets.QHBoxLayout()
        self.token_layout.setContentsMargins(5, 5, 5, 5)
        self.token_layout.setSpacing(5)

        self.user_filter_input = QtWidgets.QLineEdit()
        self.user_filter_input.setPlaceholderText("Filter by user...")
        self.user_filter_input.setStyleSheet("border: none;")
        self.user_filter_input.setMinimumWidth(100)

        # Add input to layout last so it stays at the end
        self.token_layout.addWidget(self.user_filter_input)
        self.setLayout(self.token_layout)

        # Completer setup
        # self.completer = QtWidgets.QCompleter([], self)
        self.completer = CustomQCompleter(self)
        self.completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.completer.activated.connect(self.handle_completer_selection)
        self.user_filter_input.setCompleter(self.completer)

        # Connections
        # self.user_filter_input.returnPressed.connect(self.add_token_from_input)
        self.user_filter_input.returnPressed.connect(self.on_return_pressed)
        self.user_filter_input.installEventFilter(self)

    def set_user_list(self, user_list:list):
        """Set the list of available usernames for autocompletion."""
        model = QtCore.QStringListModel(user_list)
        self.completer.setModel(model)

    def on_return_pressed(self):
        """Handle Enter key press, supporting both typing and completer selection."""
        # Wait a bit before adding token to let completer.activated finish
        QtCore.QTimer.singleShot(0, self.add_token_from_input)

    def add_token_from_input(self):
        """Add a new token based on current input text."""
        if self.completer_selected:
            # Reset flag and skip — the completer already handled it
            self.completer_selected = False
            return

        text = self.user_filter_input.text().strip()
        if text:
            self.add_token(text)

    def handle_completer_selection(self, name:str):
        """Handle selection from the autocomplete dropdown."""
        self.completer_selected = True
        QtCore.QTimer.singleShot(0, lambda: self.add_token(name, clear_input=True))

    def add_token(self, name:str, clear_input:bool=True):
        """Add a token to the widget if not already present."""

        if name in self.tokens:
            if clear_input:
                self.user_filter_input.clear()
            return

        # Disable updates temporarily
        self.setUpdatesEnabled(False)

        token_widget = UserToken(name, self.remove_token)
        self.token_widgets.append(token_widget)
        self.tokens.append(name)

        self.token_layout.insertWidget(self.token_layout.count() - 1, token_widget)
        if clear_input:
            self.user_filter_input.clear()
        self.filterChanged.emit(self.tokens)

        # Re-enable updates after the changes are made
        self.setUpdatesEnabled(True)

    def remove_token(self, token_widget: 'UserToken'):
        """Remove the given token widget from the filter."""
        if token_widget.name in self.tokens:
            self.tokens.remove(token_widget.name)
            self.token_widgets.remove(token_widget)
            self.token_layout.removeWidget(token_widget)
            token_widget.deleteLater()
            self.filterChanged.emit(self.tokens)

    def clear_tokens(self):
        """Remove all tokens from the widget."""
        for token in self.token_widgets:
            self.token_layout.removeWidget(token)
            token.deleteLater()
        self.token_widgets.clear()
        self.tokens.clear()
        self.filterChanged.emit([])

    def get_tokens(self):
        """Return the current list of username tokens."""
        return list(self.tokens)

    def eventFilter(self, source, event):
        # Only process key events for the user_filter_input QLineEdit
        if source == self.user_filter_input and event.type() == QtCore.QEvent.KeyPress:
            if event.key() == QtCore.Qt.Key_Tab:  # Check for Tab key
                text = self.user_filter_input.text().strip()
                if text:
                    self.completer.complete()  # Show the completer for auto-completion
                return True  # Consume the event
        return super(LineEditToken, self).eventFilter(source, event)

class UserToken(QtWidgets.QWidget):
    """
    A UI token representing a selected username with a delete button.

    Args:
        name (str): The username represented by this token.
        remove_callback (Callable[[UserToken], None]): Callback to remove the token from the UI.
    """
    def __init__(self, name, remove_callback):
        super().__init__()
        self.name = name

        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        label = QtWidgets.QLabel(name)
        label.setStyleSheet("font-weight: bold; color: black;")

        btn = QtWidgets.QPushButton("✖")
        btn.setFixedSize(16, 16)
        btn.setStyleSheet("QPushButton { border: none; }")
        btn.clicked.connect(lambda: remove_callback(self))

        layout.addWidget(label)
        layout.addWidget(btn)
        self.setLayout(layout)

        self.setStyleSheet("""
            QWidget {
                border: 1px solid #ccc;
                border-radius: 10px;
                background-color: #e0f0ff;
            }
        """)

class CustomQCompleter(QtWidgets.QCompleter):
    """
    Custom QCompleter with support for fuzzy matching using difflib.

    Attributes:
        fuzzy_enabled (bool): Whether fuzzy matching is active.
        local_completion_prefix (str): Current input text.
        source_model (QAbstractItemModel): The original model for autocompletion.
    """
    def __init__(self, parent=None):
        super(CustomQCompleter, self).__init__(parent)
        self.fuzzy_enabled = True
        self.local_completion_prefix = ""
        self.source_model = None
        self.cache = {}

    def setFuzzyEnabled(self, enabled: bool):
        """Enable or disable fuzzy matching."""
        self.fuzzy_enabled = enabled
        self.updateModel()  # Refresh current suggestions

    def setModel(self, model):
        """Set the base model and store all words for matching."""
        self.source_model = model
        self.all_words = model.stringList()
        super(CustomQCompleter, self).setModel(model)

    def updateModel(self):
        """Rebuild the list of matches based on the current input prefix."""
        query = self.local_completion_prefix
        if query in self.cache:
            matches = self.cache[query]
        else:
            if not query:
                matches = self.all_words
            else:
                if self.fuzzy_enabled:
                    matches = difflib.get_close_matches(query, self.all_words, n=10, cutoff=0.4)
                else:
                    matches = [word for word in self.all_words if query.lower() in word.lower()]
            # Cache the results
            self.cache[query] = matches

        model = QtCore.QStringListModel(matches)
        super(CustomQCompleter, self).setModel(model)

    def splitPath(self, path):
        """Intercept path splitting to provide fuzzy matches."""
        self.local_completion_prefix = path
        self.updateModel()
        return ""
