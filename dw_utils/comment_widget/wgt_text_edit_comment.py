"""
Module for Autocompletion and Syntax Highlighting in Text Editing

This module provides a custom QTextEdit widget with advanced features such as
autocompletion for mentions (e.g., roles and names) and syntax highlighting.
It is designed to integrate seamlessly with PyQt/PySide applications and supports
dynamic updates to keywords.

Features:
- Autocompletion for mentions triggered by '@'.
- Syntax highlighting for roles and names with customizable styles.
- Dynamic keyword updates via a registry and watcher.
- Compatibility with multiple host environments (e.g., Maya, Houdini, standalone).
- Customizable UI with support for Qt item delegates.

Usage:
```python
from Qt.QtWidgets import QApplication
from dw_utils.comment_widget.wgt_text_edit_comment import MainWindow

if __name__ == "__main__":
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec_()
"""

from PySide6 import QtWidgets, QtGui, QtCore
import re
import sys
import json, hashlib

try:
    from PySide6.QtCore import QRegularExpression
    USE_QREGULAREXPRESSION = True
except ImportError:
    USE_QREGULAREXPRESSION = False

# Define your role and name word lists
word_roles = ["supervisor", "lead", "td", "artist", "coordinator"]
word_names = ["johndoe", "janedoe", "alice"]

def make_format(color, style=''):
    """Create a QTextCharFormat for styling."""
    fmt = QtGui.QTextCharFormat()
    fmt.setForeground(QtGui.QColor(color))
    if 'bold' in style:
        fmt.setFontWeight(QtGui.QFont.Bold)
    if 'italic' in style:
        fmt.setFontItalic(True)
    return fmt

# Define syntax highlighting styles
ROLE_FORMAT = make_format('#FFD700', 'bold')  # Roles in yellow and bold
NAME_FORMAT = make_format('#00FFFF', 'italic')  # Names in cyan and italic


class KeywordRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.roles = ["supervisor", "lead", "td", "artist", "coordinator"]
            cls._instance.names = []
            cls._instance.local_data_md5 = cls._instance.generate_data_md5(cls._instance.roles + cls._instance.names)
        return cls._instance

    def set_keywords(self, roles, names):
        self.roles = roles
        self.names = names
        self.local_data_md5 = self.generate_data_md5(self.roles + self.names)

    def set_names(self, names):
        self.names = names
        self.local_data_md5 = self.generate_data_md5(self.roles + self.names)

    def get_all(self):
        return self.roles + self.names

    def get_roles(self):
        return self.roles

    def get_names(self):
        return self.names

    @staticmethod
    def generate_data_md5(data):
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.md5(data_str.encode('utf-8')).hexdigest()

    def fetch_data_md5(self):
        return "some_md5_hash_from_server"

    def fetch_latest_keywords(self):
        return ["supervisor", "lead", "td", "artist", "coordinator"], []

    def update_keywords(self):
        new_roles, new_names = self.fetch_latest_keywords()
        new_md5 = self.generate_data_md5(new_roles + new_names)

        if new_md5 != self.local_data_md5:
            self.roles = new_roles
            self.names = new_names
            self.local_data_md5 = new_md5
            return True  # Indicate that changes occurred
        return False

class KeywordWatcher(QtCore.QObject):
    data_updated = QtCore.Signal()

    def __init__(self, interval_ms=600000, parent=None):
        super().__init__(parent)
        self.registry = KeywordRegistry()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.check_for_updates)
        self.timer.start(interval_ms)

    def check_for_updates(self):
        if self.registry.update_keywords():
            self.data_updated.emit()

class CompleterItemDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, roles, names, parent=None):
        super().__init__(parent)
        self.roles = set([r.lower() for r in roles])
        self.names = set([n.lower() for n in names])

    def paint(self, painter, option, index):
        text = index.data(QtCore.Qt.DisplayRole)
        color = QtGui.QColor("white")

        if text.lower() in self.roles:
            color = QtGui.QColor("#FFD700")  # Yellow for roles
        elif text.lower() in self.names:
            color = QtGui.QColor("#00FFFF")  # Cyan for names

        painter.save()
        if option.state & QtWidgets.QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        painter.setPen(color)
        painter.drawText(option.rect.adjusted(5, 0, 0, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, text)
        painter.restore()

class MentionHighlighter(QtGui.QSyntaxHighlighter):
    """Custom highlighter for role and name mentions."""
    def __init__(self, document, names=None, roles=None):
        super().__init__(document)
        self.rules = []

        registry = KeywordRegistry()
        self.word_names = names if names is not None else registry.get_names()
        self.word_roles = roles if roles is not None else registry.get_roles()

        # Create regex rules for role mentions
        for word in self.word_roles:
            pattern = QRegularExpression(r'@' + word + r'\b', QRegularExpression.CaseInsensitiveOption)
            self.rules.append((pattern, ROLE_FORMAT))

        # Create regex rules for name mentions
        for word in self.word_names:
            pattern = QRegularExpression(r'@' + re.escape(word) + r'\b', QRegularExpression.CaseInsensitiveOption)
            self.rules.append((pattern, NAME_FORMAT))

    def highlightBlock(self, text):
        """Apply the formatting rules to each block of text."""
        for pattern, fmt in self.rules:
            match_iter = pattern.globalMatch(text)
            while match_iter.hasNext():
                match = match_iter.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)

    def get_mentions(self, text):
        mentions = set()
        for pattern, _ in self.rules:
            match_iter = pattern.globalMatch(text)
            while match_iter.hasNext():
                match = match_iter.next()
                mention = match.captured()
                if mention.startswith('@'):
                    mention = mention[1:]  # Strip @
                mentions.add(mention)
        return list(mentions)

class HighlighterLegacy(QtGui.QSyntaxHighlighter):
    def __init__(self, document, names=None, roles=None):
        super().__init__(document)
        self.rules = []

        registry = KeywordRegistry()
        self.word_names = names if names is not None else registry.get_names()
        self.word_roles = roles if roles is not None else registry.get_roles()

        for word in self.word_roles:
            regex = QtCore.QRegExp(r'@' + word + r'\b')
            self.rules.append((regex, ROLE_FORMAT))
        for word in self.word_names:
            regex = QtCore.QRegExp(r'@' + word + r'\b')
            self.rules.append((regex, NAME_FORMAT))

    def highlightBlock(self, text):
        for regex, fmt in self.rules:
            index = regex.indexIn(text)
            while index >= 0:
                length = regex.matchedLength()
                self.setFormat(index, length, fmt)
                index = regex.indexIn(text, index + length)


HIGHLIGHTER = MentionHighlighter if USE_QREGULAREXPRESSION else HighlighterLegacy


class TextEdit(QtWidgets.QTextEdit):
    """Custom QTextEdit with autocompletion and syntax highlighting."""
    def __init__(self, parent=None, names=None, roles=None):
        super().__init__(parent)
        self.setPlainText("")
        self.completer = None
        self.highlighter = None
        self.just_completed = False
        self.post_complete_space_count = 0

        self.word_names = names if names else []
        self.word_roles = roles if roles else word_roles

        self._setupCompleter()
        self._setupHighlighter()

    def _setupCompleter(self):
        self.word_list = self.word_roles + self.word_names
        completer = QtWidgets.QCompleter(self.word_list, self)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.setCompleter(completer)

    def _setupHighlighter(self):
        highlighter_class = MentionHighlighter if USE_QREGULAREXPRESSION else HighlighterLegacy
        self.setHighlighter(highlighter_class(self.document(), self.word_roles, self.word_names))

    def get_mentions(self):
        return self.highlighter.get_mentions(self.toPlainText())

    def setCompleter(self, completer):
        """Set the completer for the QTextEdit."""
        if self.completer:
            self.completer.disconnect(self)
        self.completer = completer
        if not self.completer:
            return
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self.completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.completer.activated.connect(self.insertCompletion)

        # Customize popup size
        self.completer.popup().setFixedWidth(400)  # Set the width of the popup
        self.completer.popup().setFixedHeight(300)  # Set the height of the popup

        # Add the delegate for coloring
        delegate = CompleterItemDelegate(self.word_roles, self.word_names, self)
        completer.popup().setItemDelegate(delegate)

    def insertCompletion(self, completion):

        """
        Inserts the selected completion into the text editor,
        replacing the currently typed word (after '@').
        """

        if self.completer.widget() != self:
            return

        tc = self.textCursor()
        prefix = self.completer.completionPrefix()
        prefix_len = len(prefix)

        if prefix_len > 0:
            # Move cursor back to cover the prefix (and select it)
            for _ in range(prefix_len):
                tc.movePosition(QtGui.QTextCursor.Left, QtGui.QTextCursor.KeepAnchor)

        # Replace with the full completion
        tc.insertText(completion)
        self.setTextCursor(tc)

    def keyPressEvent(self, event):
        if self.completer and self.completer.popup().isVisible():
            if event.key() in (
                    QtCore.Qt.Key_Enter, QtCore.Qt.Key_Return,
                    QtCore.Qt.Key_Escape, QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab
            ):
                event.ignore()
                return

        isShortcut = event.modifiers() & QtCore.Qt.ControlModifier and event.key() == QtCore.Qt.Key_E
        if not self.completer or not isShortcut:
            super().keyPressEvent(event)

        ctrlOrShift = event.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier)
        if not self.completer or (ctrlOrShift and not event.text()):
            return

        completionPrefix = self.textUnderCursor()

        # 🧠 INSERT THIS BLOCK HERE:
        if not completionPrefix or not self.toPlainText()[
                                           self.textCursor().position() - len(completionPrefix) - 1] == '@':
            self.completer.popup().hide()
            return

        if completionPrefix != self.completer.completionPrefix():
            self.completer.setCompletionPrefix(completionPrefix)
            self.completer.popup().setCurrentIndex(self.completer.completionModel().index(0, 0))

        cr = self.cursorRect()
        cr.setWidth(self.completer.popup().sizeHintForColumn(0) +
                    self.completer.popup().verticalScrollBar().sizeHint().width())
        self.completer.complete(cr)

    def textUnderCursor(self):
        cursor = self.textCursor()
        text = cursor.block().text()[:cursor.positionInBlock()]
        match = re.search(r'@([^\s@]*)$', text)
        return match.group(1) if match else ""

    def setHighlighter(self, highlighter):
        """Set the syntax highlighter for the QTextEdit."""
        self.highlighter = highlighter

    def focusInEvent(self, event):
        """Focus event to ensure completer is set up."""
        if self.completer:
            self.completer.setWidget(self)
        super().focusInEvent(event)


class TextEditPlus(TextEdit):
    def __init__(self, parent=None):
        registry = KeywordRegistry()
        super().__init__(parent, names=registry.get_names(), roles=registry.get_roles())

        # Set up the completer for user and role mentions
        self.word_names = registry.get_names()
        self.word_roles = registry.get_roles()

        self.word_list = self.word_roles + self.word_names # Combine both lists into a single list for completion

        completer = QtWidgets.QCompleter(self.word_list, self)
        completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.setCompleter(completer)

        # Set up the highlighter
        # Setup highlighter
        highlighter_class = MentionHighlighter if USE_QREGULAREXPRESSION else HighlighterLegacy
        self.setHighlighter(highlighter_class(self.document(), self.word_names, self.word_roles))

    def update_keywords(self, names=None, roles=None):
        registry = KeywordRegistry()
        self.word_names = names if names is not None else registry.get_names()
        self.word_roles = roles if roles is not None else registry.get_roles()
        self._setupCompleter()
        self._setupHighlighter()


def get_maya_main_window():
    """
    Get Maya main window as QWidget.

    :return: Maya main window as a QWidget instance.
    """
    try:
        from shiboken6 import wrapInstance
    except ImportError:
        from shiboken2 import wrapInstance
    from maya import OpenMayaUI as omui

    main_window_ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(main_window_ptr), QtWidgets.QWidget)

def get_software_window():
    try:
        env = get_host_environment()
        if env == 'maya':
            try:
                from shiboken6 import wrapInstance
            except ImportError:
                from shiboken2 import wrapInstance
            from maya import OpenMayaUI as omui
            main_window_ptr = omui.MQtUtil.mainWindow()
            return wrapInstance(int(main_window_ptr), QtWidgets.QWidget)

        elif env == 'houdini':
            import hou
            return hou.ui.mainQtWindow()
    except Exception as e:
        print(f"Could not determine host window: {e}")
    return None  # fallback for standalone

def get_host_environment():
    if 'maya.cmds' in sys.modules:
        return 'maya'
    elif 'hou' in sys.modules:
        return 'houdini'
    else:
        return 'standalone'

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=get_software_window()):
        super(MainWindow, self).__init__(parent)
        self.setWindowTitle("Autocompletion and Syntax Highlighting Example")
        self.setGeometry(100, 100, 600, 300)

        self.textEdit = TextEditPlus(self)
        self.setCentralWidget(self.textEdit)


if __name__ == "__main__":
    app = None
    if not QtWidgets.QApplication.instance():
        app = QtWidgets.QApplication(sys.argv)

    parent = get_software_window()
    window = MainWindow(parent)
    window.show()

    if app:  # Only exec if we're running standalone
        sys.exit(app.exec_())