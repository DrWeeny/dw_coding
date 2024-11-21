from PySide6 import QtWidgets, QtCore, QtGui
from enum import Enum
import math
from typing import Optional


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
        self.hover_color = QtGui.QColor(0, 0, 0, 30)

        # Animation setup
        self._setup_animation()

        # Track pending items
        self.pending_items = set()

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
        if not index.isValid():
            return

        # Get current state
        state = self._get_state(index)

        # Manage animation timer
        if state == ToggleState.PENDING:
            self.pending_items.add(index)
            if not self._animation_timer.isActive():
                self._animation_timer.start()
        else:
            self.pending_items.discard(index)
            if not self.pending_items and self._animation_timer.isActive():
                self._animation_timer.stop()

        # Calculate button rect
        button_rect = self._get_button_rect(option.rect)

        # Draw components
        self._draw_hover_effect(painter, option, button_rect)
        self._draw_base_button(painter, button_rect, state)

        if state == ToggleState.PENDING:
            self._draw_loading_animation(painter, button_rect)
        elif state == ToggleState.DISABLED:
            self._draw_disabled_indicator(painter, button_rect)

    def _get_button_rect(self, rect):
        """Calculate button geometry."""
        button_size = min(rect.height() - 4, 20)
        return QtCore.QRect(
            rect.right() - button_size - 4,
            rect.center().y() - button_size // 2,
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
        """Get current toggle state including pending."""
        state = index.data(QtCore.Qt.UserRole + 3)
        pending = index.data(QtCore.Qt.UserRole + 5)
        return ToggleState.PENDING if pending else (ToggleState.ENABLED if state else ToggleState.DISABLED)
