"""
Comment Editor Widget with DataHub Integration

Displays and edits comments for caches and presets.
Subscribes to cache selection to show relevant comments.
"""

from pathlib import Path
from PySide6 import QtWidgets, QtCore, QtGui

from dw_logger import get_logger

# Local imports
from ..hub_keys import HubKeys
from .wgt_base import DynEvalWidget

logger = get_logger()


class CommentTitle(QtWidgets.QFrame):
    """Title bar for comment section."""

    def __init__(self, title: str = None, size: tuple = (400, 40), parent=None):
        super().__init__(parent)

        # Icon (optional)
        icon_label = QtWidgets.QLabel()
        icon_label.setFixedSize(16, 16)

        # Try to load icon
        try:
            icon_path = Path(__file__).parent.parent / 'icons' / 'comment.png'
            if icon_path.exists():
                icon_label.setPixmap(
                    QtGui.QPixmap(str(icon_path)).scaled(
                        16, 16, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
                    )
                )
        except Exception:
            pass

        # Title Label
        self.title_label = QtWidgets.QLabel(title or "Comment")
        self.title_label.setFont(QtGui.QFont("Segoe UI", 10))
        self.title_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        # Layout
        layout = QtWidgets.QHBoxLayout(self)
        layout.addWidget(icon_label)
        layout.addWidget(self.title_label)
        layout.addStretch()
        layout.setContentsMargins(5, 5, 5, 5)

        self.setFixedHeight(size[1])

        # Styling
        self.setStyleSheet("""
            QFrame {
                background-color: rgba(60, 60, 60, 100);
                border-radius: 4px;
            }
            QLabel {
                color: #ffffff;
            }
        """)

    def setTitle(self, text: str = None):
        """Set the title text."""
        self.title_label.setText(text if text else "Comment")


class CommentEditor(DynEvalWidget):
    """
    Widget for viewing and editing comments on caches/presets.

    Subscribes to:
        - HubKeys.CACHE_SELECTED: Updates display when cache is selected
        - HubKeys.SELECTED_ITEM: Updates title when node is selected

    Publishes:
        - HubKeys.COMMENT_CURRENT: Current comment text
    """

    # Qt Signals
    save_requested = QtCore.Signal(str)  # Emits comment text when save requested
    comment_changed = QtCore.Signal(str)  # Emits when comment is modified

    def __init__(self, title: str = None, size: tuple = (400, 40), parent=None):
        super().__init__(parent)

        # Current context
        self._current_cache = None
        self._current_item = None

        # Setup UI
        self._setup_ui(title, size)
        self._connect_signals()
        self._setup_hub_subscriptions()

    def _setup_ui(self, title: str, size: tuple):
        """Initialize UI components."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Title
        self.comment_title = CommentTitle(title, size)
        layout.addWidget(self.comment_title)

        # Display Area (read-only, shows existing comment)
        display_label = QtWidgets.QLabel("Saved Comment:")
        display_label.setStyleSheet("color: #888888; font-size: 10px;")
        layout.addWidget(display_label)

        self.display_area = QtWidgets.QTextEdit()
        self.display_area.setReadOnly(True)
        self.display_area.setPlaceholderText("No comment saved")
        self.display_area.setMaximumHeight(100)
        self.display_area.setStyleSheet("""
            QTextEdit {
                background-color: rgba(40, 40, 40, 150);
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 4px;
                color: #cccccc;
            }
        """)
        layout.addWidget(self.display_area)

        # Separator
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Sunken)
        separator.setStyleSheet("background-color: #555555;")
        layout.addWidget(separator)

        # Write Area
        write_label = QtWidgets.QLabel("New Comment:")
        write_label.setStyleSheet("color: #888888; font-size: 10px;")
        layout.addWidget(write_label)

        self.write_area = QtWidgets.QTextEdit()
        self.write_area.setPlaceholderText("Write a comment...")
        self.write_area.setMaximumHeight(100)
        self.write_area.setStyleSheet("""
            QTextEdit {
                background-color: rgba(50, 50, 50, 150);
                border: 1px solid #666666;
                border-radius: 4px;
                padding: 4px;
                color: #ffffff;
            }
            QTextEdit:focus {
                border: 1px solid #888888;
            }
        """)
        layout.addWidget(self.write_area)

        # Buttons
        button_layout = QtWidgets.QHBoxLayout()

        self.save_btn = QtWidgets.QPushButton("Save Comment")
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a4a4a;
                border: 1px solid #666666;
                border-radius: 4px;
                padding: 6px 12px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
            }
            QPushButton:disabled {
                background-color: #3a3a3a;
                color: #666666;
            }
        """)

        self.clear_btn = QtWidgets.QPushButton("Clear")
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a4a4a;
                border: 1px solid #666666;
                border-radius: 4px;
                padding: 6px 12px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
            }
        """)

        button_layout.addStretch()
        button_layout.addWidget(self.clear_btn)
        button_layout.addWidget(self.save_btn)

        layout.addLayout(button_layout)
        layout.addStretch()

        # Context menu for write area
        self.write_area.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.write_area.customContextMenuRequested.connect(self._show_context_menu)

    def _connect_signals(self):
        """Connect widget signals."""
        self.write_area.textChanged.connect(self._on_text_changed)
        self.save_btn.clicked.connect(self._emit_save)
        self.clear_btn.clicked.connect(self._clear_write_area)

    def _setup_hub_subscriptions(self):
        """Setup DataHub subscriptions."""
        self.hub_subscribe(HubKeys.CACHE_SELECTED, self._on_cache_selected)
        self.hub_subscribe(HubKeys.SELECTED_ITEM, self._on_item_selected)

    # ========================================================================
    # HUB CALLBACKS
    # ========================================================================

    def _on_cache_selected(self, old_value, new_value):
        """Hub callback: cache selection changed."""
        self._current_cache = new_value

        if new_value:
            # Update title to show cache version
            version_text = f"v{new_value.version:03d}" if hasattr(new_value, 'version') else ""
            cache_name = getattr(new_value, 'name', 'Cache')
            self.comment_title.setTitle(f"Comment: {cache_name}")

            # Try to load existing comment
            self._load_comment_for_cache(new_value)
        else:
            self.comment_title.setTitle("Comment")
            self.display_area.clear()

    def _on_item_selected(self, old_value, new_value):
        """Hub callback: node selection changed."""
        self._current_item = new_value

        if new_value:
            # Update title with node name
            node_name = getattr(new_value, 'short_name', None) or getattr(new_value, 'node', 'Node')
            if isinstance(node_name, str):
                node_name = node_name.split('|')[-1].split(':')[-1]
            self.comment_title.setTitle(f"Comment: {node_name}")

    # ========================================================================
    # PUBLIC METHODS
    # ========================================================================

    def setComment(self, text: str = None):
        """Set the displayed comment (read-only area)."""
        self.display_area.setText(text if text else "")

    def getComment(self) -> str:
        """Get the text from the write area."""
        return self.write_area.toPlainText()

    def setTitle(self, title: str = None):
        """Set the title."""
        self.comment_title.setTitle(title)

    def clear(self):
        """Clear both areas."""
        self.display_area.clear()
        self.write_area.clear()

    # ========================================================================
    # PRIVATE METHODS
    # ========================================================================

    def _load_comment_for_cache(self, cache_info):
        """Load comment for selected cache from metadata."""
        try:
            if not self._current_item:
                return

            # Get metadata path
            if not hasattr(self._current_item, 'metadata'):
                return

            metadata_path = Path(self._current_item.metadata())
            if not metadata_path.exists():
                self.display_area.clear()
                return

            # Load metadata
            from dw_maya.dw_presets_io import dw_json
            data = dw_json.load_json(str(metadata_path))

            # Get solver name
            solver = getattr(self._current_item, 'solver_name', None)
            if not solver:
                solver = self._current_item.data(self._current_item.CUSTOM_ROLES.get('SOLVER', 0))

            # Get comment
            version = cache_info.version if hasattr(cache_info, 'version') else 0
            comment = data.get('comment', {}).get(solver, {}).get(str(version), "")

            self.display_area.setText(comment)

        except Exception as e:
            logger.warning(f"Failed to load comment: {e}")
            self.display_area.clear()

    def _on_text_changed(self):
        """Handle text changes in write area."""
        has_text = bool(self.write_area.toPlainText().strip())
        has_cache = self._current_cache is not None

        self.save_btn.setEnabled(has_text and has_cache)

        # Publish current comment
        self.hub_publish(HubKeys.COMMENT_CURRENT, self.write_area.toPlainText())

        # Emit signal
        self.comment_changed.emit(self.write_area.toPlainText())

    def _emit_save(self):
        """Emit save request."""
        comment = self.getComment()
        if comment.strip():
            self.save_requested.emit(comment)

            # Optionally copy to display after save
            self.display_area.setText(comment)
            self.write_area.clear()

    def _clear_write_area(self):
        """Clear the write area."""
        self.write_area.clear()

    def _show_context_menu(self, position: QtCore.QPoint):
        """Show context menu for write area."""
        menu = self.write_area.createStandardContextMenu()

        # Add custom actions
        menu.addSeparator()

        save_action = QtWidgets.QAction("Save To Selected Cache", self)
        save_action.triggered.connect(self._emit_save)
        save_action.setEnabled(
            bool(self.write_area.toPlainText().strip()) and
            self._current_cache is not None
        )
        menu.insertAction(menu.actions()[0], save_action)
        menu.insertSeparator(menu.actions()[1])

        # Copy from display action
        copy_action = QtWidgets.QAction("Copy Saved Comment", self)
        copy_action.triggered.connect(self._copy_from_display)
        copy_action.setEnabled(bool(self.display_area.toPlainText()))
        menu.addAction(copy_action)

        menu.exec_(self.write_area.viewport().mapToGlobal(position))

    def _copy_from_display(self):
        """Copy text from display area to write area."""
        self.write_area.setText(self.display_area.toPlainText())

    # CLEANUP - handled by DynEvalWidget base class