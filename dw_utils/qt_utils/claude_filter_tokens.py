"""
Token-based Filter LineEdit Component for PySide6
Inspired by Google's email interface with hoverable token details
"""

from PySide6.QtWidgets import (
    QApplication, QWidget, QLineEdit, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QFrame, QScrollArea, QToolTip, QCompleter
)
from PySide6.QtCore import (
    Qt, Signal, QRect, QPoint, QSize, QTimer, QAbstractListModel,
    QSortFilterProxyModel, QModelIndex, QEvent, QStringListModel
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QFont, QFontMetrics, QMouseEvent,
    QPalette, QPixmap, QPainterPath
)
from typing import List, Dict, Any, Optional, Callable
import sys
import difflib


class TokenData:
    """Data model for a single token"""
    def __init__(
        self,
        display_text: str,
        token_type: str = "default",
        color: QColor = None,
        metadata: Dict[str, Any] = None,
        removable: bool = True
    ):
        self.display_text = display_text
        self.token_type = token_type
        self.color = color or QColor("#1a73e8")
        self.metadata = metadata or {}
        self.removable = removable

    def get_tooltip_html(self) -> str:
        """Generate HTML tooltip from metadata"""
        lines = [f"<b>{self.display_text}</b>"]

        for key, value in self.metadata.items():
            if key == "profile_image":
                continue
            lines.append(f"<b>{key}:</b> {value}")

        return "<br>".join(lines)


class Token(QWidget):
    """Visual representation of a token with cross button"""
    removeRequested = Signal(object)  # Emits self
    hoverChanged = Signal(object, bool)  # Emits self and hover state

    def __init__(self, token_data: TokenData, parent=None):
        super().__init__(parent)
        self.token_data = token_data
        self.hovered = False
        self.cross_hovered = False

        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

        # Calculate size
        font = QFont()
        font.setPointSize(9)
        fm = QFontMetrics(font)
        text_width = fm.horizontalAdvance(self.token_data.display_text)

        padding = 16
        cross_width = 16 if self.token_data.removable else 0
        spacing = 4 if self.token_data.removable else 0

        self.setFixedSize(text_width + padding + cross_width + spacing, 26)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(0, 2, 0, -2)

        # Background
        bg_color = self.token_data.color
        if self.hovered:
            bg_color = bg_color.darker(110)

        painter.setBrush(bg_color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 12, 12)

        # Text
        painter.setPen(QColor("white"))
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)

        text_rect = rect.adjusted(8, 0, -20 if self.token_data.removable else -8, 0)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft,
                        self.token_data.display_text)

        # Cross button
        if self.token_data.removable:
            cross_x = rect.right() - 16
            cross_y = rect.center().y()
            cross_size = 8

            painter.setPen(QPen(QColor("white"), 1.5))
            painter.drawLine(
                cross_x - cross_size // 2, cross_y - cross_size // 2,
                cross_x + cross_size // 2, cross_y + cross_size // 2
            )
            painter.drawLine(
                cross_x - cross_size // 2, cross_y + cross_size // 2,
                cross_x + cross_size // 2, cross_y - cross_size // 2
            )

    def mousePressEvent(self, event: QMouseEvent):
        if not self.token_data.removable:
            return

        # Check if click is on cross button
        cross_rect = QRect(self.width() - 20, 0, 20, self.height())
        if cross_rect.contains(event.pos()):
            self.removeRequested.emit(self)

    def enterEvent(self, event):
        self.hovered = True
        self.hoverChanged.emit(self, True)
        self.update()

        # Show tooltip with metadata
        if self.token_data.metadata:
            QToolTip.showText(
                self.mapToGlobal(QPoint(0, self.height())),
                self.token_data.get_tooltip_html(),
                self
            )

    def leaveEvent(self, event):
        self.hovered = False
        self.hoverChanged.emit(self, False)
        self.update()
        QToolTip.hideText()


class FuzzyCompleter(QCompleter):
    """
    Custom QCompleter with support for fuzzy matching using difflib.
    Prevents blocking input while typing.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.fuzzy_enabled = True
        self.local_completion_prefix = ""
        self.source_model = None
        self.all_words = []
        self.cache = {}

        # Important: Set completion mode to allow typing
        self.setCompletionMode(QCompleter.PopupCompletion)
        self.setCaseSensitivity(Qt.CaseInsensitive)

    def setFuzzyEnabled(self, enabled: bool):
        """Enable or disable fuzzy matching."""
        self.fuzzy_enabled = enabled
        self.updateModel()

    def setModel(self, model):
        """Set the base model and store all words for matching."""
        self.source_model = model
        if hasattr(model, 'stringList'):
            self.all_words = model.stringList()
        super().setModel(model)

    def setWords(self, words: List[str]):
        """Set the list of words for autocompletion."""
        self.all_words = words
        model = QStringListModel(words)
        self.source_model = model
        super().setModel(model)

    def updateModel(self):
        """Rebuild the list of matches based on the current input prefix."""
        query = self.local_completion_prefix

        if query in self.cache:
            matches = self.cache[query]
        else:
            if not query:
                matches = self.all_words[:20]  # Limit initial results
            else:
                if self.fuzzy_enabled:
                    matches = difflib.get_close_matches(
                        query, self.all_words, n=10, cutoff=0.3
                    )
                    # Also include starts-with matches
                    starts_with = [
                        word for word in self.all_words
                        if word.lower().startswith(query.lower()) and word not in matches
                    ]
                    matches = starts_with + matches
                else:
                    matches = [
                        word for word in self.all_words
                        if query.lower() in word.lower()
                    ]

            # Cache the results
            self.cache[query] = matches[:10]  # Limit to 10 results
            matches = self.cache[query]

        model = QStringListModel(matches)
        super().setModel(model)

    def splitPath(self, path):
        """Intercept path splitting to provide fuzzy matches."""
        self.local_completion_prefix = path
        self.updateModel()
        return []  # Return empty list to prevent default filtering


class AutoCompleteItem:
    """Data model for autocomplete suggestions"""
    def __init__(
        self,
        display_text: str,
        prefix: str = "text",  # user, department, email, include, exclude, text
        full_value: str = None,
        token_color: QColor = None,
        metadata: Dict[str, Any] = None
    ):
        self.display_text = display_text
        self.prefix = prefix
        self.full_value = full_value or display_text
        self.token_color = token_color or self._default_color_for_prefix(prefix)
        self.metadata = metadata or {}

    def _default_color_for_prefix(self, prefix: str) -> QColor:
        """Return default color based on prefix type"""
        color_map = {
            "user": QColor("#1a73e8"),
            "department": QColor("#34a853"),
            "email": QColor("#ea4335"),
            "include": QColor("#fbbc04"),
            "exclude": QColor("#ff6d00"),
            "type": QColor("#9334e6"),
            "text": QColor("#5f6368")
        }
        return color_map.get(prefix, QColor("#5f6368"))

    def get_display_string(self) -> str:
        """Get formatted display string for autocomplete list"""
        if self.prefix == "text":
            return self.display_text
        return f"{self.prefix}::{self.display_text}"

    def to_token_data(self) -> TokenData:
        """Convert to TokenData for token creation"""
        return TokenData(
            display_text=self.display_text,
            token_type=self.prefix,
            color=self.token_color,
            metadata=self.metadata
        )


class AutoCompletePopup(QFrame):
    """Popup widget for autocomplete suggestions"""
    itemSelected = Signal(AutoCompleteItem)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.items: List[AutoCompleteItem] = []
        self.current_index = -1

        self.setStyleSheet("""
            AutoCompletePopup {
                background: white;
                border: 1px solid #dadce0;
                border-radius: 4px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)

        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidget(self.list_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMaximumHeight(200)

        layout.addWidget(scroll)

        self.item_labels: List[QLabel] = []

    def set_items(self, items: List[AutoCompleteItem]):
        """Set autocomplete items"""
        # Clear existing items
        for label in self.item_labels:
            label.deleteLater()
        self.item_labels.clear()

        self.items = items
        self.current_index = 0 if items else -1

        # Create labels for each item
        for i, item in enumerate(items):
            label = QLabel(item.get_display_string())
            label.setStyleSheet("""
                QLabel {
                    padding: 8px 12px;
                    color: #202124;
                }
                QLabel:hover {
                    background: #f1f3f4;
                }
            """)
            label.setCursor(Qt.PointingHandCursor)
            label.mousePressEvent = lambda e, idx=i: self._on_item_clicked(idx)

            self.list_layout.addWidget(label)
            self.item_labels.append(label)

        self._update_selection()

        if items:
            self.adjustSize()

    def _on_item_clicked(self, index: int):
        """Handle item click"""
        if 0 <= index < len(self.items):
            self.itemSelected.emit(self.items[index])
            self.hide()

    def move_selection(self, direction: int):
        """Move selection up (-1) or down (1)"""
        if not self.items:
            return

        self.current_index += direction
        if self.current_index < 0:
            self.current_index = len(self.items) - 1
        elif self.current_index >= len(self.items):
            self.current_index = 0

        self._update_selection()

    def _update_selection(self):
        """Update visual selection"""
        for i, label in enumerate(self.item_labels):
            if i == self.current_index:
                label.setStyleSheet("""
                    QLabel {
                        padding: 8px 12px;
                        background: #e8f0fe;
                        color: #1967d2;
                        font-weight: bold;
                    }
                """)
            else:
                label.setStyleSheet("""
                    QLabel {
                        padding: 8px 12px;
                        color: #202124;
                    }
                    QLabel:hover {
                        background: #f1f3f4;
                    }
                """)

    def get_selected_item(self) -> Optional[AutoCompleteItem]:
        """Get currently selected item"""
        if 0 <= self.current_index < len(self.items):
            return self.items[self.current_index]
        return None


class FilterParser:
    """Parses filter text and extracts special commands like include:, exclude:, etc."""

    def __init__(self):
        self.commands = ["include:", "exclude:", "type:", "user:", "department:", "email:"]

    def parse(self, text: str) -> Dict[str, Any]:
        """
        Parse filter text and return structured filter data
        Returns: {
            'raw_text': str,
            'commands': [{'type': str, 'value': str}],
            'plain_text': str
        }
        """
        result = {
            'raw_text': text,
            'commands': [],
            'plain_text': ''
        }

        words = text.split()
        plain_words = []

        for word in words:
            command_found = False
            for cmd in self.commands:
                if word.lower().startswith(cmd):
                    value = word[len(cmd):]
                    result['commands'].append({
                        'type': cmd[:-1],  # Remove colon
                        'value': value
                    })
                    command_found = True
                    break

            if not command_found:
                plain_words.append(word)

        result['plain_text'] = ' '.join(plain_words)
        return result


class TokenFilterLineEdit(QWidget):
    """
    Main token-based filter line edit widget
    Supports tokens, filtering, and custom filter parsing
    """
    filterChanged = Signal(dict)  # Emits parsed filter data
    tokensChanged = Signal(list)  # Emits list of TokenData

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tokens: List[TokenData] = []
        self.token_widgets: List[Token] = []
        self.filter_parser = FilterParser()
        self.custom_filter_callback: Optional[Callable] = None

        # Autocomplete with fuzzy matching
        self.autocomplete_items: List[AutoCompleteItem] = []
        self.fuzzy_completer = None
        self.autocomplete_enabled = True
        self.min_chars_for_autocomplete = 1
        self.completer_selected = False

        self._setup_ui()

    def _setup_ui(self):
        """Setup the UI layout"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Container for tokens
        self.token_container = QWidget()
        self.token_layout = QHBoxLayout(self.token_container)
        self.token_layout.setContentsMargins(0, 0, 0, 0)
        self.token_layout.setSpacing(4)
        self.token_layout.addStretch()

        # Line edit for text input
        self.line_edit = QLineEdit()
        self.line_edit.setPlaceholderText("Filter...")
        self.line_edit.setFrame(False)
        self.line_edit.textChanged.connect(self._on_text_changed)
        self.line_edit.returnPressed.connect(self._on_return_pressed)
        self.line_edit.installEventFilter(self)

        main_layout.addWidget(self.token_container)
        main_layout.addWidget(self.line_edit, 1)

        # Styling with prominent border
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("white"))
        self.setPalette(palette)

        self.setStyleSheet("""
            TokenFilterLineEdit {
                border: 2px solid #1a73e8;
                border-radius: 8px;
                background: white;
                padding: 2px;
            }
            TokenFilterLineEdit:focus-within {
                border: 2px solid #1557b0;
                background: #f8f9fa;
            }
            QLineEdit {
                border: none;
                background: transparent;
                padding: 4px;
            }
        """)

        # Setup fuzzy completer
        self.fuzzy_completer = FuzzyCompleter(self)
        self.fuzzy_completer.activated.connect(self._on_completer_activated)
        self.line_edit.setCompleter(self.fuzzy_completer)

    def eventFilter(self, obj, event):
        """Handle key events for backspace on empty input"""
        if obj == self.line_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key_Backspace and not self.line_edit.text():
                # Remove last token on backspace when input is empty
                if self.token_widgets:
                    self._remove_token(self.token_widgets[-1])
                return True

        return super().eventFilter(obj, event)

    def add_token(self, token_data: TokenData):
        """Add a new token"""
        # Check if token already exists to prevent duplicates
        for existing_token in self.tokens:
            if (existing_token.display_text == token_data.display_text and
                existing_token.token_type == token_data.token_type):
                return  # Token already exists, don't add duplicate

        self.tokens.append(token_data)

        token_widget = Token(token_data, self)
        token_widget.removeRequested.connect(self._remove_token)

        # Insert before stretch
        self.token_layout.insertWidget(
            self.token_layout.count() - 1,
            token_widget
        )
        self.token_widgets.append(token_widget)

        self.tokensChanged.emit(self.tokens)
        self._emit_filter_changed()

    def _remove_token(self, token_widget: Token):
        """Remove a token"""
        if token_widget in self.token_widgets:
            idx = self.token_widgets.index(token_widget)
            self.tokens.pop(idx)
            self.token_widgets.pop(idx)
            token_widget.deleteLater()

            self.tokensChanged.emit(self.tokens)
            self._emit_filter_changed()

    def clear_tokens(self):
        """Remove all tokens"""
        for widget in self.token_widgets:
            widget.deleteLater()

        self.tokens.clear()
        self.token_widgets.clear()
        self.tokensChanged.emit(self.tokens)
        self._emit_filter_changed()

    def get_filter_text(self) -> str:
        """Get the current filter text from line edit"""
        return self.line_edit.text()

    def get_tokens(self) -> List[TokenData]:
        """Get all current tokens"""
        return self.tokens.copy()

    def set_custom_filter_callback(self, callback: Callable):
        """
        Set a custom callback for filter processing
        Callback signature: callback(tokens: List[TokenData], filter_text: str, parsed_data: dict) -> Any
        """
        self.custom_filter_callback = callback

    def set_autocomplete_items(self, items: List[AutoCompleteItem]):
        """Set the list of autocomplete suggestions"""
        self.autocomplete_items = items

        # Build list of display strings for fuzzy completer
        display_strings = [item.get_display_string() for item in items]
        self.fuzzy_completer.setWords(display_strings)

    def set_autocomplete_enabled(self, enabled: bool):
        """Enable or disable autocomplete"""
        self.autocomplete_enabled = enabled
        if not enabled:
            self.line_edit.setCompleter(None)
        else:
            self.line_edit.setCompleter(self.fuzzy_completer)

    def _on_completer_activated(self, text: str):
        """Handle completer selection"""
        self.completer_selected = True

        # Find the matching AutoCompleteItem
        for item in self.autocomplete_items:
            if item.get_display_string() == text:
                QTimer.singleShot(10, lambda i=item: self._create_token_from_item(i))
                return

        # If no match found, create a text token
        QTimer.singleShot(10, lambda t=text: self._create_token_from_text(t))

    def _create_token_from_item(self, item: AutoCompleteItem):
        """Create token from AutoCompleteItem"""
        token_data = item.to_token_data()
        self.add_token(token_data)
        self.line_edit.clear()
        self.completer_selected = False

    def _create_token_from_text(self, text: str):
        """Create token from plain text"""
        # Parse text for prefix (e.g., "user::Alice" or just "Alice")
        if "::" in text:
            parts = text.split("::", 1)
            prefix = parts[0]
            value = parts[1]

            item = AutoCompleteItem(
                display_text=value,
                prefix=prefix,
                metadata={"source": "manual_input"}
            )
        else:
            item = AutoCompleteItem(
                display_text=text,
                prefix="text",
                metadata={"source": "manual_input"}
            )

        token_data = item.to_token_data()
        self.add_token(token_data)
        self.line_edit.clear()
        self.completer_selected = False

    def _on_text_changed(self, text: str):
        """Handle text change in line edit"""
        self._emit_filter_changed()

    def _on_return_pressed(self):
        """Handle return key press - create token from text or completer"""
        # If completer was just activated, skip to avoid duplicates
        if self.completer_selected:
            return

        text = self.line_edit.text().strip()
        if text:
            QTimer.singleShot(10, lambda: self._create_token_from_text(text))

    def _emit_filter_changed(self):
        """Parse and emit filter changed signal"""
        text = self.line_edit.text()
        parsed = self.filter_parser.parse(text)

        filter_data = {
            'tokens': self.tokens,
            'text': text,
            'parsed': parsed
        }

        # Call custom filter callback if set
        if self.custom_filter_callback:
            filter_data['custom_result'] = self.custom_filter_callback(
                self.tokens, text, parsed
            )

        self.filterChanged.emit(filter_data)


# Example usage and demo
class DemoWindow(QWidget):
    """Demo window showing usage of TokenFilterLineEdit"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Token Filter LineEdit Demo")
        self.setGeometry(100, 100, 800, 600)

        layout = QVBoxLayout(self)

        # Title
        title = QLabel("Token Filter LineEdit Demo with Autocomplete")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin: 10px;")
        layout.addWidget(title)

        # Filter line edit
        self.filter_edit = TokenFilterLineEdit()
        self.filter_edit.setMinimumHeight(40)
        layout.addWidget(self.filter_edit)

        # Instructions
        instructions = QLabel(
            "• Start typing to see autocomplete suggestions\n"
            "• Use ↑↓ arrow keys to navigate suggestions\n"
            "• Press Enter to create a token from selection\n"
            "• Type 'prefix::value' (e.g., 'user::Alice') or just text\n"
            "• Hover over tokens to see details\n"
            "• Click X to remove tokens"
        )
        instructions.setStyleSheet("margin: 10px; color: #666;")
        layout.addWidget(instructions)

        # Add sample tokens button
        btn_layout = QHBoxLayout()

        add_user_btn = QPushButton("Add User Token")
        add_user_btn.clicked.connect(self.add_user_token)
        btn_layout.addWidget(add_user_btn)

        add_type_btn = QPushButton("Add Type Token")
        add_type_btn.clicked.connect(self.add_type_token)
        btn_layout.addWidget(add_type_btn)

        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self.filter_edit.clear_tokens)
        btn_layout.addWidget(clear_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Output display
        self.output_label = QLabel("Filter output will appear here...")
        self.output_label.setWordWrap(True)
        self.output_label.setStyleSheet(
            "background: #f5f5f5; padding: 10px; border-radius: 4px; margin: 10px;"
        )
        layout.addWidget(self.output_label)

        layout.addStretch()

        # Connect signals
        self.filter_edit.filterChanged.connect(self.on_filter_changed)

        # Set custom filter callback
        self.filter_edit.set_custom_filter_callback(self.custom_filter_logic)

        # Setup autocomplete items
        self.setup_autocomplete()

    def setup_autocomplete(self):
        """Setup autocomplete suggestions"""
        autocomplete_items = [
            # Users
            AutoCompleteItem(
                display_text="Alice Pazat",
                prefix="user",
                metadata={
                    "email": "Alice.Pazat@wanadoo.fr",
                    "mattermost": "@alice.pazat",
                    "role": "Lead Developer",
                    "department": "Engineering"
                }
            ),
            AutoCompleteItem(
                display_text="Alexis Martin",
                prefix="user",
                metadata={
                    "email": "alexis.martin@company.com",
                    "mattermost": "@alexis",
                    "role": "Senior Artist",
                    "department": "Animation"
                }
            ),
            AutoCompleteItem(
                display_text="Bob Smith",
                prefix="user",
                metadata={
                    "email": "bob.smith@company.com",
                    "mattermost": "@bob",
                    "role": "TD",
                    "department": "Technical"
                }
            ),
            # Departments
            AutoCompleteItem(
                display_text="Animation",
                prefix="department",
                metadata={
                    "description": "Animation Department",
                    "team_size": "25 members"
                }
            ),
            AutoCompleteItem(
                display_text="Engineering",
                prefix="department",
                metadata={
                    "description": "Engineering Department",
                    "team_size": "15 members"
                }
            ),
            AutoCompleteItem(
                display_text="Compositing",
                prefix="department",
                metadata={
                    "description": "Compositing Department",
                    "team_size": "12 members"
                }
            ),
            # Project types
            AutoCompleteItem(
                display_text="CFX",
                prefix="type",
                token_color=QColor("#9334e6"),
                metadata={
                    "type": "Project Type",
                    "description": "Character Effects",
                    "count": "142 items"
                }
            ),
            AutoCompleteItem(
                display_text="Animation",
                prefix="type",
                token_color=QColor("#9334e6"),
                metadata={
                    "type": "Project Type",
                    "description": "Animation Tasks",
                    "count": "89 items"
                }
            ),
            # Include/Exclude examples
            AutoCompleteItem(
                display_text="completed",
                prefix="include",
                metadata={"description": "Include completed items"}
            ),
            AutoCompleteItem(
                display_text="archived",
                prefix="exclude",
                metadata={"description": "Exclude archived items"}
            ),
        ]

        self.filter_edit.set_autocomplete_items(autocomplete_items)

    def add_user_token(self):
        """Add a sample user token"""
        token = TokenData(
            display_text="Alice Pazat",
            token_type="user",
            color=QColor("#1a73e8"),
            metadata={
                "email": "Alice.Pazat@wanadoo.fr",
                "mattermost": "@alice.pazat",
                "role": "Lead Developer",
                "department": "Engineering"
            }
        )
        self.filter_edit.add_token(token)

    def add_type_token(self):
        """Add a sample type token"""
        token = TokenData(
            display_text="CFX",
            token_type="type",
            color=QColor("#34a853"),
            metadata={
                "type": "Project Type",
                "description": "Visual Effects Project",
                "count": "142 items"
            }
        )
        self.filter_edit.add_token(token)

    def custom_filter_logic(self, tokens: List[TokenData], filter_text: str, parsed_data: dict):
        """Custom filter logic example"""
        results = []

        # Process tokens
        for token in tokens:
            results.append(f"Token: {token.display_text} ({token.token_type})")

        # Process commands
        for cmd in parsed_data['commands']:
            results.append(f"Command: {cmd['type']} = {cmd['value']}")

        # Process plain text
        if parsed_data['plain_text']:
            results.append(f"Plain text filter: {parsed_data['plain_text']}")

        return results

    def on_filter_changed(self, filter_data: dict):
        """Handle filter changes"""
        output_lines = [
            f"<b>Active Tokens:</b> {len(filter_data['tokens'])}",
            f"<b>Filter Text:</b> {filter_data['text'] or '(empty)'}",
            f"<b>Plain Text:</b> {filter_data['parsed']['plain_text'] or '(none)'}",
            f"<b>Commands:</b> {len(filter_data['parsed']['commands'])}"
        ]

        if 'custom_result' in filter_data and filter_data['custom_result']:
            output_lines.append("<b>Custom Filter Results:</b>")
            for result in filter_data['custom_result']:
                output_lines.append(f"  • {result}")

        self.output_label.setText("<br>".join(output_lines))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DemoWindow()
    window.show()
    sys.exit(app.exec())