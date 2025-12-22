"""
Toggle slide widget with smooth animation (iOS/mobile style).

Provides a customizable sliding toggle switch widget with smooth animations and
configurable colors, similar to modern mobile app toggles.

Features
--------
- Smooth sliding animation with easing
- Customizable colors for on/off states
- Configurable size and animation speed
- Signal emission on state change
- Mouse hover effects
- Click and drag support

Usage
-----
Basic usage in a Qt application:

    from cfx_maya.wgt_toggle_slide import ToggleSlideWidget

    toggle = ToggleSlideWidget()
    toggle.setChecked(True)  # Start in ON state
    toggle.toggled.connect(lambda state: print(f"Toggle: {state}"))

    # Customize colors
    toggle.setColors(
        on_color="#4CAF50",
        off_color="#555555",
        handle_color="#FFFFFF"
    )

Classes
-------
- ToggleSlideWidget: Main sliding toggle switch widget

Integration
-----------
Compatible with PySide2/PySide6 and PyQt5/PyQt6. Automatically detects available
Qt binding.

Dependencies
------------
- PySide2/PySide6 or PyQt5/PyQt6

Version
-------
1.0.0

Authors
-------
Weeny
"""

try:
    from PySide2 import QtWidgets, QtCore, QtGui
    from PySide2.QtCore import Signal
except ImportError:
    try:
        from PySide6 import QtWidgets, QtCore, QtGui
        from PySide6.QtCore import Signal
    except ImportError:
        try:
            from PyQt5 import QtWidgets, QtCore, QtGui
            from PyQt5.QtCore import pyqtSignal as Signal
        except ImportError:
            from PyQt6 import QtWidgets, QtCore, QtGui
            from PyQt6.QtCore import pyqtSignal as Signal


class ToggleSlideWidget(QtWidgets.QWidget):
    """
    iOS-style sliding toggle switch widget with smooth animation.

    Provides a customizable toggle switch that animates between ON/OFF states
    with a sliding handle, similar to mobile app toggles.

    Attributes:
        toggled: Signal emitted when toggle state changes (bool)
        _checked: Current toggle state
        _handle_position: Current animated position of the handle (0.0 to 1.0)
        _animation: QPropertyAnimation for smooth transitions
        _on_color: Background color when toggle is ON
        _off_color: Background color when toggle is OFF
        _handle_color: Color of the sliding handle
        _hover: Whether mouse is hovering over widget

    Example:
        toggle = ToggleSlideWidget()
        toggle.setFixedSize(60, 30)
        toggle.toggled.connect(my_callback)
        toggle.setChecked(True)
    """

    toggled = Signal(bool)

    def __init__(self, parent=None, checked=False, width=60, height=30):
        """
        Initialize toggle slide widget.

        Args:
            parent: Parent widget (default: None)
            checked: Initial state (default: False)
            width: Widget width in pixels (default: 60)
            height: Widget height in pixels (default: 30)
        """
        super(ToggleSlideWidget, self).__init__(parent)

        self._checked = checked
        self._handle_position = 1.0 if checked else 0.0
        self._hover = False

        # Colors (can be customized)
        self._on_color = QtGui.QColor("#4CAF50")  # Green
        self._off_color = QtGui.QColor("#555555")  # Dark gray
        self._handle_color = QtGui.QColor("#FFFFFF")  # White
        self._handle_hover_color = QtGui.QColor("#F0F0F0")  # Light gray

        # Size
        self.setFixedSize(width, height)
        self.setCursor(QtCore.Qt.PointingHandCursor)

        # Animation for smooth sliding
        self._animation = QtCore.QPropertyAnimation(self, b"handlePosition", self)
        self._animation.setEasingCurve(QtCore.QEasingCurve.InOutQuad)
        self._animation.setDuration(200)  # 200ms animation

        # Enable mouse tracking for hover effect
        self.setMouseTracking(True)

    def setColors(self, on_color=None, off_color=None, handle_color=None, handle_hover_color=None):
        """
        Customize toggle colors.

        Args:
            on_color: Background color when ON (hex string or QColor)
            off_color: Background color when OFF (hex string or QColor)
            handle_color: Handle color (hex string or QColor)
            handle_hover_color: Handle color on hover (hex string or QColor)
        """
        if on_color:
            self._on_color = QtGui.QColor(on_color) if isinstance(on_color, str) else on_color
        if off_color:
            self._off_color = QtGui.QColor(off_color) if isinstance(off_color, str) else off_color
        if handle_color:
            self._handle_color = QtGui.QColor(handle_color) if isinstance(handle_color, str) else handle_color
        if handle_hover_color:
            self._handle_hover_color = QtGui.QColor(handle_hover_color) if isinstance(handle_hover_color, str) else handle_hover_color

        self.update()

    def isChecked(self):
        """
        Get current toggle state.

        Returns:
            bool: True if toggle is ON, False otherwise
        """
        return self._checked

    def setChecked(self, checked):
        """
        Set toggle state with animation.

        Args:
            checked: New state (True = ON, False = OFF)
        """
        if self._checked == checked:
            return

        self._checked = checked
        self._animate_toggle()
        self.toggled.emit(self._checked)

    def toggle(self):
        """Toggle between ON and OFF states."""
        self.setChecked(not self._checked)

    def _animate_toggle(self):
        """Animate handle sliding to new position."""
        self._animation.stop()
        self._animation.setStartValue(self._handle_position)
        self._animation.setEndValue(1.0 if self._checked else 0.0)
        self._animation.start()

    @QtCore.Property(float)
    def handlePosition(self):
        """
        Get current animated handle position.

        Returns:
            float: Position from 0.0 (OFF/left) to 1.0 (ON/right)
        """
        return self._handle_position

    @handlePosition.setter
    def handlePosition(self, pos):
        """
        Set handle position and trigger repaint.

        Args:
            pos: Position from 0.0 to 1.0
        """
        self._handle_position = pos
        self.update()

    def sizeHint(self):
        """Provide size hint for layout managers."""
        return QtCore.QSize(60, 30)

    def enterEvent(self, event):
        """Handle mouse enter event."""
        self._hover = True
        self.update()
        super(ToggleSlideWidget, self).enterEvent(event)

    def leaveEvent(self, event):
        """Handle mouse leave event."""
        self._hover = False
        self.update()
        super(ToggleSlideWidget, self).leaveEvent(event)

    def mousePressEvent(self, event):
        """Handle mouse click to toggle state."""
        if event.button() == QtCore.Qt.LeftButton:
            self.toggle()
        super(ToggleSlideWidget, self).mousePressEvent(event)

    def paintEvent(self, event):
        """
        Paint the toggle widget with current state.

        Draws the background track and animated handle with smooth colors.
        """
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        # Calculate dimensions
        width = self.width()
        height = self.height()
        radius = height / 2
        handle_radius = radius - 3  # Slightly smaller than track

        # Interpolate background color based on position
        bg_color = self._interpolate_color(
            self._off_color,
            self._on_color,
            self._handle_position
        )

        # Draw background track (rounded rectangle)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(0, 0, width, height, radius, radius)

        # Calculate handle position
        handle_x = handle_radius + 3 + (width - 2 * handle_radius - 6) * self._handle_position
        handle_y = height / 2

        # Draw handle shadow for depth
        shadow_color = QtGui.QColor(0, 0, 0, 40)
        painter.setBrush(shadow_color)
        painter.drawEllipse(
            QtCore.QPointF(handle_x + 1, handle_y + 1),
            handle_radius,
            handle_radius
        )

        # Draw handle
        handle_color = self._handle_hover_color if self._hover else self._handle_color
        painter.setBrush(handle_color)
        painter.drawEllipse(
            QtCore.QPointF(handle_x, handle_y),
            handle_radius,
            handle_radius
        )

        painter.end()

    def _interpolate_color(self, color1, color2, t):
        """
        Linearly interpolate between two colors.

        Args:
            color1: Start color (QColor)
            color2: End color (QColor)
            t: Interpolation factor from 0.0 to 1.0

        Returns:
            QColor: Interpolated color
        """
        r = int(color1.red() + (color2.red() - color1.red()) * t)
        g = int(color1.green() + (color2.green() - color1.green()) * t)
        b = int(color1.blue() + (color2.blue() - color1.blue()) * t)
        return QtGui.QColor(r, g, b)


class LabeledToggleWidget(QtWidgets.QWidget):
    """
    Toggle switch with integrated label (convenience wrapper).

    Combines a ToggleSlideWidget with a QLabel for easy form layouts.

    Attributes:
        toggled: Signal emitted when toggle state changes (bool)

    Example:
        toggle = LabeledToggleWidget("Edit Mode")
        toggle.setChecked(True)
        toggle.toggled.connect(my_callback)
    """

    toggled = Signal(bool)

    def __init__(self, label_text="", parent=None, checked=False, label_on_left=True):
        """
        Initialize labeled toggle widget.

        Args:
            label_text: Text to display next to toggle
            parent: Parent widget
            checked: Initial toggle state
            label_on_left: If True, label is on left side; if False, on right
        """
        super(LabeledToggleWidget, self).__init__(parent)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.label = QtWidgets.QLabel(label_text)
        self.toggle = ToggleSlideWidget(checked=checked)

        if label_on_left:
            layout.addWidget(self.label)
            layout.addWidget(self.toggle)
        else:
            layout.addWidget(self.toggle)
            layout.addWidget(self.label)

        layout.addStretch()

        # Forward toggle signal
        self.toggle.toggled.connect(self.toggled.emit)

    def setChecked(self, checked):
        """Set toggle state."""
        self.toggle.setChecked(checked)

    def isChecked(self):
        """Get toggle state."""
        return self.toggle.isChecked()

    def setText(self, text):
        """Update label text."""
        self.label.setText(text)

    def setColors(self, **kwargs):
        """Set toggle colors (forwards to ToggleSlideWidget)."""
        self.toggle.setColors(**kwargs)


if __name__ == "__main__":
    """Standalone test/demo of the toggle widget."""
    import sys

    app = QtWidgets.QApplication(sys.argv)

    # Create demo window
    window = QtWidgets.QWidget()
    window.setWindowTitle("Toggle Slide Widget Demo")
    window.resize(400, 300)

    layout = QtWidgets.QVBoxLayout(window)
    layout.setSpacing(20)

    # Title
    title = QtWidgets.QLabel("<h2>Toggle Slide Widget Demo</h2>")
    layout.addWidget(title)

    # Basic toggle
    layout.addWidget(QtWidgets.QLabel("<b>Basic Toggle:</b>"))
    basic_toggle = ToggleSlideWidget(checked=False)
    basic_toggle.toggled.connect(lambda state: print(f"Basic toggle: {state}"))
    layout.addWidget(basic_toggle)

    # Labeled toggle
    layout.addWidget(QtWidgets.QLabel("<b>Labeled Toggle (Edit Mode):</b>"))
    edit_toggle = LabeledToggleWidget("Edit Mode", checked=False)
    edit_toggle.toggled.connect(lambda state: print(f"Edit Mode: {state}"))
    layout.addWidget(edit_toggle)

    # Custom colors
    layout.addWidget(QtWidgets.QLabel("<b>Custom Colors (Blue/Red):</b>"))
    custom_toggle = ToggleSlideWidget(checked=True, width=70, height=35)
    custom_toggle.setColors(
        on_color="#2196F3",  # Blue
        off_color="#F44336",  # Red
        handle_color="#FFFFFF"
    )
    custom_toggle.toggled.connect(lambda state: print(f"Custom toggle: {state}"))
    layout.addWidget(custom_toggle)

    # Different sizes
    layout.addWidget(QtWidgets.QLabel("<b>Different Sizes:</b>"))
    size_layout = QtWidgets.QHBoxLayout()

    small_toggle = ToggleSlideWidget(width=40, height=20)
    small_toggle.toggled.connect(lambda state: print(f"Small: {state}"))
    size_layout.addWidget(QtWidgets.QLabel("Small:"))
    size_layout.addWidget(small_toggle)

    medium_toggle = ToggleSlideWidget(width=60, height=30)
    medium_toggle.toggled.connect(lambda state: print(f"Medium: {state}"))
    size_layout.addWidget(QtWidgets.QLabel("Medium:"))
    size_layout.addWidget(medium_toggle)

    large_toggle = ToggleSlideWidget(width=80, height=40)
    large_toggle.toggled.connect(lambda state: print(f"Large: {state}"))
    size_layout.addWidget(QtWidgets.QLabel("Large:"))
    size_layout.addWidget(large_toggle)

    size_layout.addStretch()
    layout.addLayout(size_layout)

    layout.addStretch()

    # Status label
    status_label = QtWidgets.QLabel("Click any toggle to see state changes in console")
    status_label.setStyleSheet("color: #888; font-style: italic;")
    layout.addWidget(status_label)

    window.show()
    sys.exit(app.exec_())

