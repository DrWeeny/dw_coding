"""
Module for creating a comment panel widget with functionalities for saving, displaying,
and managing user comments.

Classes:
- CustomTextEdit: A subclass of QTextEdit that adds custom context menu actions.
- CommentPanel: A QWidget that displays a panel with user information, comment text, and metadata.

author : np-alexis
"""
import webbrowser
from PySide2 import QtCore, QtGui, QtWidgets
from .wgt_action_separator import ActionTextSeparator
from typing import Optional


class CustomTextEdit(QtWidgets.QTextEdit):
    """
    Custom QTextEdit widget with added functionality for a context menu
    and saving comments.

    Signals:
        text_saved (str): Emitted when the user saves the comment text.
    """
    text_saved = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def contextMenuEvent(self, event):
        """
        Override the context menu event to add custom actions at the beginning.

        Args:
            event (QtGui.QContextMenuEvent): The context menu event triggered by right-click.
        """
        # Create the default context menu (standard actions)
        context_menu = self.createStandardContextMenu()

        separator = ActionTextSeparator("Metadata Actions", self)

        # Create the 'Save Comment' action
        save_action = QtWidgets.QAction("Save Comment", self)
        save_action.triggered.connect(self.save_comment)

        separator2 = ActionTextSeparator("Default Actions", self)

        # Insert the 'Save Comment' action at the beginning of the context menu
        context_menu.insertAction(context_menu.actions()[0], separator2)
        context_menu.insertAction(context_menu.actions()[0], save_action)  # Insert before the first action
        context_menu.insertAction(context_menu.actions()[0], separator)  # Insert before the first action

        # Show the context menu at the cursor position
        context_menu.exec_(event.globalPos())

    def save_comment(self):
        """
        This method is called when the 'Save Comment' action is triggered.
        It saves the current text in the QTextEdit widget to a file.
        """
        comment_text = self.toPlainText()
        self.text_saved.emit(comment_text)


class CommentPanel(QtWidgets.QWidget):
    """
    A widget that displays a comment panel with user information, comment text, and metadata.

    Signals:
        comment_saved (str): Emitted when a comment is saved.
    """
    comment_saved = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.weblink = None

        self.layout = QtWidgets.QVBoxLayout(self)

        # user field, todo should be locked, should have a right click context to unlock
        self.user_name_label = QtWidgets.QLineEdit("User: ", self)
        self.user_name_label.setReadOnly(True)
        self.layout.addWidget(self.user_name_label)

        # date + weblink
        horizontalLayout = QtWidgets.QHBoxLayout()

        self.weblink_btn = QtWidgets.QPushButton("Weblink", self)
        self.weblink_btn.setFixedSize(40,40)
        self.date_created_label = QtWidgets.QLineEdit("Date: ", self)
        self.date_created_label.setReadOnly(True)
        self.date_created_label.setAlignment(QtCore.Qt.AlignRight)
        horizontalLayout.addWidget(self.date_created_label)
        horizontalLayout.addWidget(self.weblink_btn)
        self.layout.addLayout(horizontalLayout)
        # self.layout.addWidget(self.date_created_label)

        self.comment_text = CustomTextEdit(self)
        self.comment_text.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.comment_text.setMaximumHeight(10000)
        self.comment_text.setMaximumWidth(10000)
        self.layout.addWidget(self.comment_text)

        self.comment_text.text_saved.connect(self.comment_saved.emit)
        self.weblink_btn.clicked.connect(self.open_weblink)

        # # Tear-off button (top right)
        # self.tear_off_button = QtWidgets.QPushButton("Tear Off", self)
        # self.tear_off_button.clicked.connect(self.tear_off)
        # self.tear_off_button.setGeometry(self._width() - 70, 10, 60, 30)

        # Initially, hide the widget off-screen below the parent widget
        self.hide()

    def set_user(self, text:str):
        """
        Set the user name in the panel.

        Args:
            text (str): The user name to display.
        """
        self.user_name_label.setText(text)

    def set_date(self, text:str):
        """
        Set the creation date in the panel.

        Args:
            text (str): The date to display.
        """
        self.date_created_label.setText(text)
        self.date_created_label.adjustSize()

    def set_comment(self, text:str):
        """
        Set the comment text in the panel.

        Args:
            text (str): The comment text to display.
        """
        self.comment_text.setText(text)

    def set_weblink(self, weblink:str):
        """
        Set the weblink for the panel.

        Args:
            weblink (str): The weblink to display.
        """
        self.weblink = weblink
        if self.weblink:
            self.weblink_btn.setEnabled(True)
        else:
            self.weblink_btn.setEnabled(False)

    def open_weblink(self) -> None:
        """
        Open the weblink in Google Chrome (or fallback to default browser if Chrome is unavailable).
        """
        if self.weblink:
            try:
                # Try opening with Chrome first
                chrome_path = 'C:/Program Files/Google/Chrome/Application/chrome.exe %s'
                webbrowser.get(chrome_path).open(self.weblink)
            except Exception:
                # Fallback to the default browser if Chrome is not available
                webbrowser.open(self.weblink)
        else:
            QtWidgets.QMessageBox.warning(self, "Warning", "No web link set.")

    def reset_all_fields(self):
        """
        Reset all fields in the comment panel.
        """
        self.user_name_label.setText("")
        self.date_created_label.setText("")
        self.weblink=None
        self.comment_text.setText("")

    def set_all_fields(self, comment: str, user: str, creation_date: str, weblink: Optional[str]):
        """
        Set all fields (comment, user, date, weblink) in the panel.

        Args:
            comment (str): The comment text.
            user (str): The user name.
            creation_date (str): The creation date.
            weblink (Optional[str]): The weblink (can be None).
        """
        self.user_name_label.setText(user)
        self.date_created_label.setText(creation_date)
        self.weblink = weblink
        if self.weblink:
            self.weblink_btn.setEnabled(True)
        else:
            self.weblink_btn.setEnabled(False)
        self.comment_text.setText(comment)

    def tear_off(self):
        """
        Create a new window with the same content as the current panel (tear off).
        """
        # Create a new window with the same content
        tear_off_window = QtWidgets.QWidget()
        tear_off_window.setWindowTitle("Torn-Off Comment Panel")
        tear_off_layout = QtWidgets.QVBoxLayout(tear_off_window)

        # Add the same content from this widget to the new window
        tear_off_layout.addWidget(self.user_name_label)
        tear_off_layout.addWidget(self.date_created_label)
        tear_off_layout.addWidget(self.comment_text)

        tear_off_window.setLayout(tear_off_layout)
        tear_off_window.show()

    def show_panel(self):
        """
        Show the comment panel with an animation.
        """
        self.show()
        animation = QtCore.QPropertyAnimation(self, b"geometry")
        animation.setDuration(300)
        animation.setStartValue(QtCore.QRect(0, 0, 0, 0))
        animation.setEndValue(QtCore.QRect(0, 0, 687, 300))
        animation.start()

    def hide_panel(self):
        """
        Hide the comment panel with an animation.
        """
        animation = QtCore.QPropertyAnimation(self, b"geometry")
        animation.setDuration(300)
        animation.setStartValue(QtCore.QRect(0, 0, 687, 300))
        animation.setEndValue(QtCore.QRect(0, 0, 0, 0))
        animation.start()
        animation.finished.connect(self.hide)
        self.layout.addStretch()