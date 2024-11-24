from PySide6 import QtWidgets, QtCore, QtGui
from enum import Enum
import math
from typing import Optional
from .nucleus_leaf.base_standarditem import BaseSimulationItem
from dw_logger import get_logger

logger = get_logger()

class ToggleState(Enum):
    DISABLED = 0
    ENABLED = 1
    PENDING = 2


class ToggleButtonDelegate(QtWidgets.QStyledItemDelegate):
    """Enhanced delegate with loading animation and state management."""

    toggled = QtCore.Signal(QtCore.QModelIndex, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Colors for different states
        self.colors = {
            ToggleState.ENABLED: QtGui.QColor("#10B981"),  # Green
            ToggleState.DISABLED: QtGui.QColor("#EF4444"),  # Red
            ToggleState.PENDING: QtGui.QColor("#FCD34D"),  # Yellow
        }
        self.hover_color = QtGui.QColor(0, 0, 0, 15)  # Lighter background
        self.hover_highlight = QtGui.QColor(59, 130, 246, 180)  # Semi-transparent blue

        # Animation setup
        self._setup_animation()

        # Track pending items
        self.pending_items = set()

        # Initialize hover tracking
        self.hover_active = False
        self.current_hover_rect = None

    def editorEvent(self, event, model, option, index) -> bool:
        """Handle mouse events for the toggle button."""
        if not index.isValid() or index.column() != 1:
            return False

        button_rect = self._get_button_rect(option.rect)

        # Handle mouse move and hover
        if event.type() == QtCore.QEvent.MouseMove:
            self.hover_active = button_rect.contains(event.pos())
            self.current_hover_rect = button_rect if self.hover_active else None
            self.parent().viewport().update()
            return True

        # Handle click
        elif event.type() == QtCore.QEvent.MouseButtonRelease:
            if button_rect.contains(event.pos()):
                current_state = index.data(QtCore.Qt.UserRole + 3)
                new_state = not bool(current_state)
                self.toggled.emit(index, new_state)
                return True

        return super().editorEvent(event, model, option, index)


    def sizeHint(self, option, index) -> QtCore.QSize:
        """Return the size hint for the delegate."""
        return QtCore.QSize(24, 24)  # Fixed size for toggle button

    def _setup_animation(self):
        """Initialize animation timer and properties."""
        self._animation_timer = QtCore.QTimer(self)
        self._animation_timer.timeout.connect(self._update_animation)
        self._animation_timer.setInterval(16)  # ~60 FPS

        self._rotation_angle = 0.0
        self._dot_positions = []
        self._calculate_dot_positions()

    def _calculate_dot_positions(self):
        """Precalculate dot positions for animation."""
        self._dot_positions = []
        for i in range(8):
            angle = i * (360 / 8)  # 8 dots evenly spaced
            self._dot_positions.append(angle)

    def paint(self, painter, option, index):
        """Paint the toggle button with hover highlight."""
        if not index.isValid():
            return

        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        # Get current state
        state = self._get_state(index)

        # Calculate button rect
        button_rect = self._get_button_rect(option.rect)

        # Draw hover effect
        if self.hover_active and self.current_hover_rect == button_rect:
            # Draw hover highlight
            highlight_rect = button_rect.adjusted(-4, -4, 4, 4)
            painter.setPen(QtGui.QPen(self.hover_highlight, 2))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(highlight_rect, 6, 6)

        # Draw base button
        color = self.colors[state]
        painter.setPen(QtGui.QPen(color, 2))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(button_rect)

        # Draw loading animation if pending
        if state == ToggleState.PENDING:
            self._draw_loading_animation(painter, button_rect)

        painter.restore()

    def _get_button_rect(self, rect):
        """Calculate button geometry."""
        button_size = min(rect.height() - 8, 16)  # Slightly smaller button
        center_x = rect.center().x()
        center_y = rect.center().y()

        return QtCore.QRect(
            center_x - button_size // 2,
            center_y - button_size // 2,
            button_size,
            button_size
        )
    def _draw_hover_effect(self, painter, option, rect):
        """Draw hover state background."""
        if option.state & QtWidgets.QStyle.State_MouseOver:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(self.hover_color)
            painter.drawRoundedRect(rect, 4, 4)

    def _draw_base_button(self, painter, rect, state):
        """Draw the main button circle."""
        color = self.colors[state]
        painter.setPen(QtGui.QPen(color, 2))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(rect.adjusted(2, 2, -2, -2))

    def _draw_loading_animation(self, painter, rect):
        """Draw animated loading indicator."""
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        center = rect.center()
        radius = rect.width() / 3

        for i, base_angle in enumerate(self._dot_positions):
            # Calculate dot position with current rotation
            angle = base_angle + self._rotation_angle
            rad_angle = math.radians(angle)

            # Calculate dot position
            x = center.x() + radius * math.cos(rad_angle)
            y = center.y() + radius * math.sin(rad_angle)

            # Fade dots based on position
            fade = 0.3 + (0.7 * ((i + 1) / 8))
            painter.setOpacity(fade)

            # Draw dot
            dot_size = 2
            painter.setBrush(self.colors[ToggleState.PENDING])
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawEllipse(QtCore.QPointF(x, y), dot_size, dot_size)

        painter.restore()

    def _draw_disabled_indicator(self, painter, rect):
        """Draw disabled state indicator."""
        adjusted_rect = rect.adjusted(2, 2, -2, -2)
        painter.drawLine(
            adjusted_rect.topLeft() + QtCore.QPoint(3, 3),
            adjusted_rect.bottomRight() + QtCore.QPoint(-3, -3)
        )

    def _update_animation(self):
        """Update animation rotation angle."""
        self._rotation_angle = (self._rotation_angle + 5) % 360

        # Only update regions with pending items
        if self.parent():
            for index in self.pending_items:
                self.parent().viewport().update(
                    self.parent().visualRect(index)
                )

    def _get_state(self, index) -> ToggleState:
        """Get current toggle state."""
        state = index.data(QtCore.Qt.UserRole + 3)
        if isinstance(state, bool):
            return ToggleState.ENABLED if state else ToggleState.DISABLED
        return ToggleState.DISABLED
