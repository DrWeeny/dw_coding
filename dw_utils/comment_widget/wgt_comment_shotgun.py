"""
Comment widget for internal review and collaboration.

Features
- Display, add and delete comments organised by versioned take folders
- Collapsible per-take sections with user avatars, timestamps and @-mentions
- Auto-discover versioned subfolders from a root path
- Optional DataHubPub integration (works standalone when unavailable)
- Standalone-friendly: only depends on Qt, os.path and the local JSON backend

Usage
    ```python
    from dw_utils.comment_widget.wgt_comment_shotgun import CommentSGStyleWidget

    widget = CommentSGStyleWidget()
    # Point to a root folder that contains versioned subdirectories
    widget.set_root_path("/project/shots/ep01/sq010/sh0010/work/charaFX")
    widget.show()
    ```

Classes
- CommentSGStyleWidget: Top-level widget embedding header, toggle bar and comment stack
- CommentStack: Container managing per-take collapsible comment sections
- CommentWidget: Single comment bubble (avatar + name + time + text + delete)
- AddCommentWidget: User input area for writing new comments
- HeaderComment: Thumbnail + task name + collapsible info header
- CollapsibleSection: Generic collapsible container
- CollapsibleTakeSection: Styled collapsible section for takes

Integration
- Publishes comment data via dw_utils.data_hub.DataHubPub when available
- Backend JSON operations handled by `cmds_comment_shotgun` module

Version: 1.2.0
"""
from PySide6 import QtGui, QtWidgets, QtCore
from dw_utils.comment_widget.wgt_text_edit_comment import TextEditPlus, KeywordRegistry
import os.path
from datetime import datetime
from typing import Optional
import re

from dw_utils.comment_widget.cmds_comment_shotgun import (get_conversation_from_path,
                                   get_user, extract_number_from_take_name, save_new_comment,
                                   mark_conversation_as_read, extract_mentions_from_html,
                                   update_mentions_on_comment, CurrentUser, USER, random_user_icon, highlight_mentions,
                                   delete_old_comment, remove_mentions_on_comment)

try:
    from dw_utils.data_hub import DataHubPub
    _HAS_DATA_HUB = True
except ImportError:
    _HAS_DATA_HUB = False

dir_path = os.path.dirname(__file__)

# Resolve the pic_files folder via dw_ressources (preferred), otherwise
# fall back to a sibling ``icon/`` directory next to dw_utils/.
try:
    from dw_ressources import get_resource_path as _get_resource_path
    _pic_path = str(_get_resource_path("pic_files"))
except Exception:
    _pic_path = None

if _pic_path and os.path.isdir(_pic_path):
    ICON_FOLDER = _pic_path
else:
    _legacy = os.path.join(os.path.dirname(dir_path), "icon")
    ICON_FOLDER = _legacy if os.path.isdir(_legacy) else None

_avatar_pixmap_cache = {}

def get_avatar_pixmap(image_path, size=(35, 35)):
    key = (image_path, size)
    if key not in _avatar_pixmap_cache:
        pixmap = QtGui.QPixmap(image_path)
        if pixmap.isNull():
            pixmap = QtGui.QPixmap(*size)
            pixmap.fill(QtGui.QColor("gray"))
        _avatar_pixmap_cache[key] = pixmap.scaled(*size,
                                                  QtCore.Qt.KeepAspectRatio,
                                                  QtCore.Qt.SmoothTransformation)
    return _avatar_pixmap_cache[key]


def _is_html(text):
    """Check if the given text contains HTML tags."""
    return bool(re.search(r'<.*?>', text))


def discover_versioned_folders(root_path):
    """
    Scan *root_path* for immediate subdirectories whose names look like
    version tokens (e.g. ``t001``, ``v003``, ``take_01``).

    Args:
        root_path: Directory that may contain versioned subfolders.

    Returns:
        list[str]: Sorted list of absolute paths to discovered version folders
                   (newest/highest version first).  Empty list when nothing is found
                   or the path does not exist.
    """
    import os

    if not root_path or not os.path.isdir(root_path):
        return []

    version_re = re.compile(r'^[tv]\d+$|^take_?\d+$', re.IGNORECASE)
    folders = []
    for name in os.listdir(root_path):
        full = os.path.join(root_path, name)
        if os.path.isdir(full) and version_re.match(name):
            folders.append(full)

    # Sort by the numeric part descending so the latest version comes first
    def _sort_key(p):
        nums = re.findall(r'\d+', os.path.basename(p))
        return int(nums[-1]) if nums else 0

    return sorted(folders, key=_sort_key, reverse=True)

class CommentSGStyleWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent)

        self.USER = CurrentUser() # Singleton of the current user
        self._data_hub = DataHubPub.Get() if _HAS_DATA_HUB else None

        self.comment_pix = None # for add comment, None is random

        # folder path is set externally (e.g. from a parent window signal)
        self.folder_path = None
        # episode sequence shot asset
        self.task = "project_sq000_sh000_taskname"

        main_layout = QtWidgets.QVBoxLayout(self)

        # first mini widget show the task
        header_wgt = HeaderComment()
        main_layout.addWidget(header_wgt)

        # second horizontal buttons
        ## button 1 for comments woth each takes
        ## button 2 for overview comments
        ## button 3 tickets ?
        container = QtWidgets.QWidget()
        container.setFixedHeight(100)
        toggle_layout = QtWidgets.QHBoxLayout()
        container.setStyleSheet("background-color:rgb(42, 42, 42);")
        container.setLayout(toggle_layout)
        if ICON_FOLDER:
            _icon_path = os.path.join(ICON_FOLDER, "comment_bubble.png")
            if not self.comment_pix:
                self.comment_pix = QtGui.QPixmap(_icon_path).scaled(
                    60, 60,
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation
                )
        pb_toggle_comment = QtWidgets.QPushButton(self)
        if self.comment_pix:
            pb_toggle_comment.setIcon(self.comment_pix)
            pb_toggle_comment.setIconSize(QtCore.QSize(60, 60))

        toggle_layout.addStretch()  # Push contents to the center
        toggle_layout.addWidget(pb_toggle_comment)  # Centered widget
        toggle_layout.addStretch()  # Push it from the other side too

        main_layout.addWidget(container)

        # Qlistview style but in a normal layotu with comments "Notes"
        ## collapsable items for each Take
        ### comment with this : user-photo |- name + time |- comment
        ### new comment placeholder
        self.comment_stack = CommentStack()
        self.comment_stack.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        scroll.setWidget(self.comment_stack)


        # Add to your layout (e.g., in main window or parent container)
        main_layout.addWidget(scroll, stretch=1)

        main_layout.addStretch()
        self.setLayout(main_layout)

        # COMMENT SIGNAL IS BEING SAVED
        self.comment_stack.commentSaved.connect(self.handle_comment_saved)
        self.comment_stack.commentDeleted.connect(self.handle_comment_deleted)

    def _publish_to_hub(self, data):
        """Publish comment data to the DataHub if available."""
        if self._data_hub is not None:
            self._data_hub.publish(key="dw_comment_widget",
                                   value=data,
                                   overwrite=True)

    def set_root_path(self, root_path):
        """
        Point the widget at a root directory and auto-discover versioned subfolders.

        The widget scans *root_path* for subdirectories whose names look like
        version tokens (``t001``, ``v003``, ``take_01``, …) and feeds the
        result into :meth:`set_folder_path`.

        Args:
            root_path: Directory that may contain versioned subfolders.
        """
        if not root_path or not os.path.isdir(root_path):
            self.clear()
            return

        versioned = discover_versioned_folders(root_path)
        if versioned:
            # Use the root that contains the versioned folders
            self.set_folder_path(root_path)
        else:
            # No versioned subfolders — try using root_path itself
            self.set_folder_path(root_path)

    def set_folder_path(self, path:str):
        if os.path.exists(path):
            self.folder_path = path
            self.update_comment_data()
        else:
            self.clear()

    def clear(self):
        self.comment_stack.clear_comments()

    def update_comment_data(self):
        self.clear()
        data_dic = get_conversation_from_path(self.folder_path)
        self.load_comment_data_from_dic(data_dic)
        mark_conversation_as_read(
                                  user_name=self.USER,
                                  scope_key=self.task,
                                  read_time=datetime.now())

    def set_task(self, shot_data=None, task_string=None, project=None):
        """
        Set the task key used for subscriptions and mentions.

        Args:
            shot_data: Tuple of (episode, sequence, shot, asset).
            task_string: Direct task key string (takes priority if both given).
            project: A ``dw_utils.dw_project.Project`` instance.  When given,
                     *task_string* and *folder_path* are derived automatically.
        """
        if project is not None:
            self.task = project.task_key
            self.set_folder_path(str(project.shot_path))
        elif task_string:
            self.task = task_string
        elif shot_data and len(shot_data) >= 4:
            episode, sequence, shot, asset = shot_data[:4]
            self.task = f"{episode}_{sequence}_{shot}_{asset}"
        else:
            print(f"set_task: invalid input — shot_data={shot_data}, task_string={task_string}")

    def set_user_name(self, user_name:str):
        """
        Manually switch the current user identity.

        Args:
            user_name: OS login name to look up in the user database.
        """
        self.USER = USER(user_name)

    def get_current_user(self):
        return CurrentUser()

    def load_comment_data_from_dic(self, data: dict):
        # Sort takes based on the numeric part of the take name in descending order
        sorted_data = sorted(data.items(), key=lambda x: extract_number_from_take_name(x[0]), reverse=True)

        for take_name, take_entry in sorted_data:
            comments = take_entry.get("comments", [])

            # Sort comments based on timestamp in descending order
            sorted_comments = sorted(comments, key=lambda c: datetime.fromisoformat(c.get("timestamp", "")))

            # Convert timestamps to datetime objects
            parsed_comments = []
            for c in sorted_comments:
                timestamp_str = c.get("timestamp")
                dt = datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.now()
                parsed_comments.append({
                    "user_name": c.get("user_name", "Unknown"),
                    "user_image": c.get("user_image", "placeholder_612x.png"),
                    "text": c.get("text", ""),
                    "text_html": c.get("text_html", ""),  # Use HTML text if available
                    "timestamp": dt,
                })

            # Create the take stack with sorted comments
            self.comment_stack.create_take_stack(
                take_name,
                parsed_comments,
                profile_pic=self.USER.avatar_path,
                username=self.USER.name
            )

        self.set_data_dic(data)

    def set_data_dic(self, data:dict):
        """
        Save the data dictionary and publish to the hub.
        """
        self.comment_stack_dic = data
        self._publish_to_hub(data)

    def handle_comment_saved(self, comment_data):
        # comment should be saved in json
        new_data = save_new_comment(self.folder_path, comment_data)
        # send this data to the hub so other widgets are aware new data has been set
        self._publish_to_hub(new_data)

        # should update subscription db with user name if it is different so we can get new messages notif
        self.USER.subscribe_to_scope(scope_key=self.task,
                                     folder_path=self.folder_path,
                                     timestamp=comment_data["timestamp"])

        mention = extract_mentions_from_html(comment_data.get("text_html", None))
        if mention:
            update_mentions_on_comment(
                folder_path=self.folder_path,
                scope_key=self.task,
                timestamp=comment_data["timestamp"],
                text=comment_data["text"],
                text_html=comment_data.get("text_html", None),
                mentions=mention
            )

    def handle_comment_deleted(self, comment_data):
        """
        Handles the deletion of a comment.

        Args:
            comment_data (dict): The comment data to delete.
        """
        # Delete the comment from the JSON database
        updated_data = delete_old_comment(self.folder_path, comment_data)

        # Remove mentions associated with the comment
        remove_mentions_on_comment(self.folder_path, comment_data)

        # Publish the updated data to the hub
        self._publish_to_hub(updated_data)


class HeaderComment(QtWidgets.QWidget):
    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent)

        default_task_name = "None"

        main_layout = QtWidgets.QHBoxLayout(self)

        # thumbnail is the first widget of the main layout
        _icon_path = os.path.join(ICON_FOLDER, "placeholder.png") if ICON_FOLDER else ""
        self.label_pix = QtWidgets.QLabel(self)
        thumbnail_pix = QtGui.QPixmap(_icon_path)
        self.set_thumbnail(thumbnail_pix)

        main_layout.addWidget(self.label_pix)

        # a vertical layout is needed with task description
        # and second element is a info collapsable element
        info_layout = QtWidgets.QVBoxLayout(self)

        self.task_name = QtWidgets.QLabel(self)
        self.task_name.setText(default_task_name)
        self.task_name.setAlignment(QtCore.Qt.AlignCenter)

        info_layout.addWidget(self.task_name)

        self.more_info = CollapsibleSection("More Infos", self)
        info_layout.addWidget(self.more_info)

        main_layout.addLayout(info_layout)

    def set_thumbnail(self, pixmap: QtGui.QPixmap):
        """
        Theorically it is supposed to receive Shotgrid thumbnail
        """
        width, height = self.label_pix.size().width(), self.label_pix.size().height()
        resized_pixmap = pixmap.scaled(width, height,
                                       QtCore.Qt.KeepAspectRatio,
                                       QtCore.Qt.SmoothTransformation)
        self.label_pix.setPixmap(resized_pixmap)

    def set_task_name(self, task_name:str):
        self.task_name.setText(task_name)

    def add_more_infos(self, text:str):
        new_info = QtWidgets.QLabel(self)
        new_info.setText(text)
        self.more_info.add_widget(widget=new_info)

class CommentStack(QtWidgets.QWidget):
    """
    global history with all the takes which are containing comments
    """
    commentSaved = QtCore.Signal(dict)
    commentDeleted = QtCore.Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.addStretch()
        self.data_comment = {}
        self.stack = {}

    def clear_comments(self):
        for take_name, take_info in self.stack.items():
            take_item = take_info["item"]

            # Disconnect any signals before deleting
            for i in range(take_item.content_layout.count()):
                item = take_item.content_layout.itemAt(i)
                if item and item.widget():
                    item.widget().deleteLater()

            self.main_layout.removeWidget(take_item)
            take_item.deleteLater()

        self.stack.clear()

    def create_take_stack(self, take_name, comment_data, profile_pic, username):
        """
        Create a stack for each take, adding comments and a new input field for comments.
        """
        # Sort comments by timestamp (oldest to newest)
        sorted_comments = sorted(comment_data, key=lambda c: c["timestamp"])

        counter = 0
        take_item = CollapsibleTakeSection(take_name)
        self.stack[take_name] = {"item": take_item,
                                 "counter":counter}

        # Add the existing comments for the take
        for entry in comment_data:

            # a fallback is necessary if user dont exists in shotgrid or has been deleted
            os_user_name = entry.get("os_user_name")

            if os_user_name:
                try:
                    user = USER(os_user_name)
                except Exception:
                    # fallback to placeholder
                    user = self._make_placeholder_user(entry)
            else:
                # no os_user_name in data
                user = self._make_placeholder_user(entry)

            comment = CommentWidget(
                user=user,
                timestamp=entry["timestamp"],
                comment=entry.get("text_html", None) or entry["text"],
                take = take_name
            )

            comment.commentDeleted.connect(self.delete_comment)
            take_item.add_widget(widget=comment)
            self.stack[take_name]["counter"] += 1

        # Add the widget for adding a new comment and connect the signal
        add_comment_widget = AddCommentWidget(user=CurrentUser(),
                                              take_name=take_name)

        add_comment_widget.commentSaved.connect(self._handler_comment_saved)  # Connect the signal

        take_item.add_widget(widget=add_comment_widget)
        self.main_layout.insertWidget(self.main_layout.count() - 1, take_item)

    def delete_comment(self, comment_data):
        """
        Deletes the comment matching the provided data.
        """
        take_name = comment_data.get("take")  # Retrieve the take name
        if take_name not in self.stack:
            print(f"Take '{take_name}' not found in the stack.")
            return

        take_item = self.stack[take_name]["item"]
        for i in range(take_item.content_layout.count()):
            item = take_item.content_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), CommentWidget):
                widget = item.widget()
                if (widget.comment == comment_data["comment"] and
                        widget.timestamp == comment_data["timestamp"] and
                        widget.USER.name == comment_data["user"]):
                    self.commentDeleted.emit(comment_data)
                    widget.deleteLater()
                    take_item.content_layout.removeItem(item)
                    return

    def _make_placeholder_user(self, entry):
        user = USER()
        user.name = entry.get("user_name", "Unknown")
        user.avatar_path = entry.get("user_image", "placeholder_612x.png")
        user.role = "guest"
        return user

    def _handler_comment_saved(self, data):
        self.commentSaved.emit(data)
        self.add_comment(data["take"], data)

    def add_comment(self, stack_name:str, comment:dict):

        # make sure time is the correct type
        ts = comment.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)

        comment_widget = CommentWidget(user=CurrentUser(),
                                timestamp=ts,
                                comment=comment.get("text_html") or comment.get("text"),
                                take=stack_name)
        stack = self.get_stack(stack_name)

        add_comment_widget_index = stack.content_layout.count() - 1
        stack.add_widget(widget=comment_widget, insert_id=add_comment_widget_index)
        # stack.add_widget(widget=comment_widget, insert_id=self.stack[stack_name]["counter"])
        self.stack[stack_name]["counter"]+=1

        # Connect the delete signal
        comment_widget.commentDeleted.connect(self.delete_comment)

    def get_stack(self, stack_name:str):
        return self.stack[stack_name]["item"]

    def get_comment_count(self, stack_name:str):
        return self.stack[stack_name]["counter"]


class CommentWidget(QtWidgets.QWidget):
    """
    used to represent each notes with a profile picture, name, date and the actual comment
    """
    commentDeleted = QtCore.Signal(dict)

    def __init__(self, user, timestamp, comment, take, parent=None):
        super().__init__(parent)

        self.USER = user
        self.comment = comment
        self.timestamp = timestamp
        self.take = take

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(2)

        # First line: profile pic, username, timestamp
        top_layout = QtWidgets.QHBoxLayout()
        profile_label = QtWidgets.QLabel()

        pixmap = get_avatar_pixmap(self.USER.avatar_path, (32, 32))

        profile_label.setPixmap(pixmap)
        top_layout.addWidget(profile_label)

        name_label = QtWidgets.QLabel(f"<font color='#3498db'><b>{user.name}</b></font>")
        time_label = QtWidgets.QLabel(f"<font color='lightgrey'>{self.time_ago(timestamp)}</font>")
        top_layout.addWidget(name_label)
        top_layout.addStretch()
        top_layout.addWidget(time_label)

        # Add delete button (initially hidden)
        self.delete_button = QtWidgets.QPushButton()
        if ICON_FOLDER:
            _trash_icon_path = os.path.join(ICON_FOLDER, "trash_icon_shotgrid.png")
            self.delete_button.setIcon(QtGui.QIcon(get_avatar_pixmap(_trash_icon_path)))
        self.delete_button.setFixedSize(24, 24)
        self.delete_button.setStyleSheet("border: none;")
        self.delete_button.clicked.connect(self.handle_delete)
        self.delete_button.setVisible(False)  # Hide by default
        top_layout.addWidget(self.delete_button)

        # Second line: comment text
        comment_label = QtWidgets.QLabel()
        if _is_html(comment):
            comment_label.setTextFormat(QtCore.Qt.RichText)
        else:
            comment_label.setTextFormat(QtCore.Qt.PlainText)
        comment_label.setText(comment)
        comment_label.setWordWrap(True)

        layout.addLayout(top_layout)
        layout.addWidget(comment_label)

    def handle_delete(self):
        emitted_data = {
            "comment": self.comment,
            "user": self.USER.name,
            "timestamp": self.timestamp,
            "take": self.take
        }
        self.commentDeleted.emit(emitted_data)
        print(f"Deleted comment: {emitted_data}")

    def enterEvent(self, event):
        """Show the delete button when the mouse enters the widget."""
        if self.USER.name == CurrentUser().name or CurrentUser().role == "Supervisor":
            self.delete_button.setVisible(True)
            super().enterEvent(event)

    def leaveEvent(self, event):
        """Hide the delete button when the mouse leaves the widget."""
        self.delete_button.setVisible(False)
        super().leaveEvent(event)

    def time_ago(self, timestamp):
        """Return a human-readable relative time string."""
        now = datetime.now()
        diff = now - timestamp
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            return f"{seconds // 60} minutes ago"
        elif seconds < 86400:
            return f"{seconds // 3600} hours ago"
        else:
            return f"{seconds // 86400} days ago"


class AddCommentWidget(QtWidgets.QWidget):
    """
    user input for comments
    your profile picture with a text edit and a save button
    todo allow mulitline, customise the look of the lineedit to connect with the user profile picture so we are under impression he is speaking (a small triangle shape should be enough)
    """

    commentSaved = QtCore.Signal(dict)

    def __init__(self, user:USER, take_name:str, parent:Optional[QtWidgets.QWidget] =None):
        super().__init__(parent)

        self.USER = user
        self.username = self.USER.name
        self.take_name = take_name

        # create a defualt picture if profile_path is None
        self._profile_path = self.USER.avatar_path or random_user_icon()

        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.text_layout = QtWidgets.QVBoxLayout()

        self.profile = QtWidgets.QLabel()
        pixmap = self.USER.avatar_pixmap((50,50))
        self.profile.setPixmap(pixmap)
        self.profile.setFixedSize(50, 50)

        self.text_edit = TextEditPlus()
        self.text_edit.setFixedHeight(30)
        self.text_edit.setPlaceholderText("Write a comment...")
        self.text_edit.setWordWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)

        # save note button, it is animated to appear while editing
        self.save_button = QtWidgets.QPushButton("Save Note")
        self.save_button.setStyleSheet("background-color: #3498db; color: white; font-size: 18px;")
        self.save_button.setFixedWidth(80)
        self.save_button.setFixedHeight(24)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()  # pushes button to the right
        button_layout.addWidget(self.save_button)

        self.save_button.setVisible(False)
        self.save_button.clicked.connect(self.emit_comment)

        self.text_layout.addWidget(self.text_edit)
        self.text_layout.addLayout(button_layout)

        self.main_layout.addWidget(self.profile, alignment=QtCore.Qt.AlignTop)
        self.main_layout.setAlignment(QtCore.Qt.AlignTop)
        self.main_layout.addLayout(self.text_layout)

        # Use an event filter to toggle the save button on focus changes.
        # Previously this was done via monkey-patching:
        #     self.text_edit.focusInEvent = self.expand_save_button
        #     self.text_edit.focusOutEvent = self.collapse_save_button
        # That replaced TextEditPlus's own focusInEvent with a method whose
        # super() resolved to AddCommentWidget → QWidget.focusInEvent instead
        # of TextEditPlus.focusInEvent, silently breaking any focus logic the
        # text edit had (e.g. autocomplete popup positioning).
        # An event filter watches for the events *without* replacing the
        # original methods, so TextEditPlus keeps full control of its own
        # focus handling.
        self.text_edit.installEventFilter(self)

        self.text_edit.textChanged.connect(self.adjust_text_edit_height)

    # -- event filter replaces the old monkey-patched focus methods -----------

    def eventFilter(self, obj, event):
        """
        Toggle save-button visibility when the text edit gains/loses focus.
        """
        if obj is self.text_edit:
            if event.type() == QtCore.QEvent.FocusIn:
                self.save_button.setVisible(True)
            elif event.type() == QtCore.QEvent.FocusOut:
                if not self.text_edit.toPlainText():
                    self.save_button.setVisible(False)
        return super().eventFilter(obj, event)

    def emit_comment(self):
        text = self.text_edit.toPlainText().strip()
        text_html = highlight_mentions(text, KeywordRegistry().get_roles(), KeywordRegistry().get_names())
        if text:
            comment_data = {
                "user_name": self.username,
                "user_image_pixmap": self.profile.pixmap(),
                "user_image": self._profile_path or random_user_icon(),
                "text": text,
                "text_html": text_html,
                "timestamp": datetime.now(),
                "take": self.take_name,
                "os_user_name":get_user(),
                "user_role":self.USER.role
            }
            self.commentSaved.emit(comment_data)
            self.text_edit.clear()
            self.save_button.setVisible(False)

    def adjust_text_edit_height(self):
        doc = self.text_edit.document()
        doc_height = doc.size().height()
        margin = 10
        new_height = doc_height + margin
        max_height = 150  # Limit to avoid huge box

        self.text_edit.setFixedHeight(min(new_height, max_height))
        self.save_button.setEnabled(bool(self.text_edit.toPlainText()))

class CollapsibleSection(QtWidgets.QWidget):
    """
    used to click on the section and display new widgets
    """
    def __init__(self, title="More Info", parent=None):
        super().__init__(parent)

        self.toggle_button = QtWidgets.QToolButton(text=title, checkable=True, checked=False)
        self.toggle_button.setStyleSheet("QToolButton { border: none; }")
        self.toggle_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(QtCore.Qt.RightArrow)
        self.toggle_button.clicked.connect(self.toggle)

        self.content_area = QtWidgets.QWidget()
        self.content_area.setVisible(False)

        self.content_layout = QtWidgets.QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 0, 0, 0)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addWidget(self.toggle_button)
        main_layout.addWidget(self.content_area)

    def toggle(self):
        checked = self.toggle_button.isChecked()
        self.content_area.setVisible(checked)
        self.toggle_button.setArrowType(QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow)

        # self.animation = QtCore.QPropertyAnimation(self.content_area, b"maximumHeight")
        # self.animation.setDuration(200)
        # self.animation.setStartValue(0)
        # self.animation.setEndValue(300)  # Adjust depending on content
        # self.animation.start()

    def add_widget(self, widget, insert_id:int=None):
        if isinstance(insert_id, int):
            self.content_layout.insertWidget(insert_id, widget)
        else:
            self.content_layout.addWidget(widget)

class CollapsibleTakeSection(CollapsibleSection):
    """
    In our data, each take is a collapsible item.
    The header will have a blue background, and the content will have a light gray background.
    """
    def __init__(self, title="Take 1", parent=None):
        super().__init__(title, parent)

        # Set the toggle button (header) to span the full width
        self.toggle_button.setStyleSheet("""
            QToolButton {
                border: none;
                background-color: #3498db;  /* Blue background for the header */
                color: white;
                padding: 10px;
                font-weight: bold;
                text-align: left;
            }
            QToolButton::checked {
                background-color: #2980b9;  /* Darker blue when expanded */
            }
        """)

        # Ensure that the button takes up the full width available in the layout
        self.toggle_button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        # Optional: If you want to make the layout even more responsive, you could use stretch factors
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

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
    win = None
    try:
        win = get_maya_main_window()
    except:
        pass
    return win

class TryWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=get_software_window()):
        super(TryWindow, self).__init__(parent)
        self.setWindowTitle("Comment System Demo")
        self.setMinimumSize(600, 400)

        widget = CommentSGStyleWidget()
        self.setCentralWidget(widget)


# ---------------------------------------------------------------------------
# Standalone mockup
# ---------------------------------------------------------------------------

def _create_mockup_render_tree():
    """Build a temporary project tree with versioned render folders and
    seed it with sample comments so the widget has something to display.

    Layout on disk::

        <tmp>/mockup_project/
            images/ep01/sq010/sh0010/render/
                v001/
                v002/
                v003/
                take_comment.json   <-- seeded data

    Returns:
        (render_folder, project)
    """
    import tempfile, json, os
    from datetime import datetime, timedelta

    try:
        from dw_utils.dw_project import Project
    except ImportError:
        # Minimal inline fallback so the file stays self-contained
        Project = None

    root = os.path.join(tempfile.mkdtemp(prefix="dw_mock_"), "mockup_project")

    # -- create the folder hierarchy ----------------------------------------
    render_dir = os.path.join(root, "images", "ep01", "sq010", "sh0010", "render")
    versions = ["v001", "v002", "v003"]
    for v in versions:
        os.makedirs(os.path.join(render_dir, v), exist_ok=True)

    # mirror in shots/ and assets/ so Project paths are consistent
    for category in ("shots", "assets"):
        os.makedirs(os.path.join(root, category, "ep01", "sq010", "sh0010"), exist_ok=True)

    # -- seed sample comments -----------------------------------------------
    now = datetime.now()
    sample_comments = {
        "Take_v003": {
            "comments": [
                {
                    "user_name": "Alice",
                    "user_image": "placeholder.png",
                    "os_user_name": "",
                    "text": "Latest render looks great, cloth sim is much better now.",
                    "text_html": "",
                    "timestamp": (now - timedelta(minutes=12)).isoformat(),
                    "user_role": "lead",
                },
                {
                    "user_name": "Bob",
                    "user_image": "placeholder.png",
                    "os_user_name": "",
                    "text": "Agreed. Small pop on frame 148 though — can we smooth that out?",
                    "text_html": "",
                    "timestamp": (now - timedelta(minutes=5)).isoformat(),
                    "user_role": "artist",
                },
            ]
        },
        "Take_v002": {
            "comments": [
                {
                    "user_name": "Charlie",
                    "user_image": "placeholder.png",
                    "os_user_name": "",
                    "text": "Lighting pass is missing on the left shoulder, @supervisor can you check?",
                    "text_html": 'Lighting pass is missing on the left shoulder, '
                                 '<span style="color:#FFD700; font-weight:bold">@supervisor</span> can you check?',
                    "timestamp": (now - timedelta(hours=3)).isoformat(),
                    "user_role": "artist",
                },
            ]
        },
        "Take_v001": {
            "comments": [
                {
                    "user_name": "Alice",
                    "user_image": "placeholder.png",
                    "os_user_name": "",
                    "text": "First blocking pass — placeholder textures, no lighting yet.",
                    "text_html": "",
                    "timestamp": (now - timedelta(days=2)).isoformat(),
                    "user_role": "lead",
                },
                {
                    "user_name": "Bob",
                    "user_image": "placeholder.png",
                    "os_user_name": "",
                    "text": "Proportions look off on the cape, needs another iteration.",
                    "text_html": "",
                    "timestamp": (now - timedelta(days=2, hours=-1)).isoformat(),
                    "user_role": "artist",
                },
                {
                    "user_name": "Charlie",
                    "user_image": "placeholder.png",
                    "os_user_name": "",
                    "text": "I'll take a look tomorrow morning.",
                    "text_html": "",
                    "timestamp": (now - timedelta(days=1, hours=20)).isoformat(),
                    "user_role": "td",
                },
            ]
        },
    }

    comment_json_path = os.path.join(render_dir, "take_comment.json")
    with open(comment_json_path, "w", encoding="utf-8") as fh:
        json.dump(sample_comments, fh, indent=2)

    # -- build a Project if dw_project is available -------------------------
    project = None
    if Project is not None:
        project = Project(
            name="mockup_project",
            root=root,
            episode="ep01",
            sequence="sq010",
            shot_name="sh0010",
        )

    print(f"[mockup] render folder : {render_dir}")
    print(f"[mockup] seeded {sum(len(t['comments']) for t in sample_comments.values())} comments across {len(versions)} versions")

    return render_dir, project


if __name__ == "__main__":
    import sys

    app = None
    if not QtWidgets.QApplication.instance():
        app = QtWidgets.QApplication(sys.argv)

    render_folder, project = _create_mockup_render_tree()

    parent = get_software_window()
    win = QtWidgets.QMainWindow(parent)
    win.setWindowTitle("Comment Widget — Mockup Project (ep01 / sq010 / sh0010 / render)")
    win.setMinimumSize(650, 550)

    comment_widget = CommentSGStyleWidget()
    if project is not None:
        comment_widget.set_task(task_string=project.task_key)
    else:
        comment_widget.task = "ep01_sq010_sh0010"

    # Point at the render folder which contains v001..v003 + take_comment.json
    comment_widget.set_folder_path(render_folder)

    win.setCentralWidget(comment_widget)
    win.show()

    if app:
        sys.exit(app.exec())
