"""
Slider with a Spinbox synched
"""

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

from typing import Optional, Union

def get_qt_width_from_str(text: str,
                          font: QtGui.QFont = None,
                          size: int = 9) -> int:
    # conforming to qlabel
    if isinstance(text, QtWidgets.QLabel):
        lbl = text
        if font:
            lbl.setFont(font)
    else:
        lbl = QtWidgets.QLabel(text)
        if not font:
            font = lbl.font()
            font.setPointSize(size)
        lbl.setFont(font)

    lbl.ensurePolished()
    w_width = lbl.sizeHint().width()

    return w_width

class WidgetSizeGroup(QtCore.QObject):
    """
    Synchronise automatiquement la largeur d'un groupe de widgets.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._widgets = []

    def add_widget(self, widget: QtWidgets.QWidget):
        self._widgets.append(widget)
        # On peut imaginer recalculer à l'ajout,
        # mais le mieux est de le faire après l'initialisation.

    def update_widths(self):
        """
        Calcule la largeur maximale requise (sizeHint) et l'applique à tous.
        Utiliser sizeHint() est plus sûr que QFontMetrics car cela inclut
        les marges et le padding appliqués par Maya/Houdini !
        """
        max_width = 0
        for w in self._widgets:
            # ensurePolished applique le style de l'hôte avant de demander la taille
            w.ensurePolished()
            # sizeHint() inclut la police ET les marges du style actuel
            w_width = w.sizeHint().width()
            if w_width > max_width:
                max_width = w_width

        for w in self._widgets:
            w.setMinimumWidth(max_width)

class SliderWithButton(QtWidgets.QWidget):
    """Horizontal slider bidirectionally synced with a spinbox, plus a button.

    Replaces Maya's ``floatSliderButtonGrp`` which has no PySide6 equivalent.

    QtCore.Signals:
        value_changed(float): Emitted whenever the slider or spinbox changes.
        button_clicked():     Emitted when the action button is pressed.

    Args:
        label:       Label shown to the left.
        btn_label:   Text on the action button.
        min_val:     Slider minimum.
        max_val:     Slider maximum.
        default:     Initial value.
        decimals:    Number of decimal places in the spinbox.
        step:        Single step size for the spinbox.
        parent:      Optional parent widget.

    Example:
        slider = SliderWithButton('weight', 'Set', 0.0, 1.0, 0.5)
        slider.value_changed.connect(on_weight_changed)
        slider.button_clicked.connect(on_set_clicked)
    """

    value_changed = QtCore.Signal(float)
    button_clicked = QtCore.Signal()
    sliderReleased = QtCore.Signal()

    def __init__(self,
                 label: str = '',
                 btn_label: str = 'Set',
                 min_val: float = None,
                 max_val: float = None,
                 default: float = 0.5,
                 decimals: int = 2,
                 step: float = 0.01,
                 label_width = 0,
                 has_button: bool = True,
                 parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        self._scale = 10 ** decimals  # int slider resolution

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if label:
            lbl = QtWidgets.QLabel(label)
            if not label_width and label:
                label_width = get_qt_width_from_str(label)
            lbl.setFixedWidth(label_width)
            layout.addWidget(lbl)

        self._spinbox = QtWidgets.QDoubleSpinBox()
        self._spinbox.setLocale(QtCore.QLocale(QtCore.QLocale.English, QtCore.QLocale.UnitedStates))
        if isinstance(min_val, (int, float)):
            self._spinbox.setMinimum(min_val)
        if isinstance(max_val, (int, float)):
            self._spinbox.setMaximum(max_val)
        self._spinbox.setDecimals(decimals)
        self._spinbox.setSingleStep(step)
        self._spinbox.setValue(default)
        self._spinbox.setFixedWidth(58)
        layout.addWidget(self._spinbox)

        s_min = min_val if isinstance(min_val, (int, float)) else 0.0
        s_max = max_val if isinstance(max_val, (int, float)) else 1.0

        self._slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._slider.setRange(int(s_min * self._scale),
                              int(s_max * self._scale))
        self._slider.setValue(int(default * self._scale))
        layout.addWidget(self._slider, stretch=1)

        self._button = None
        if has_button:
            self._button = QtWidgets.QPushButton(btn_label)
            self._button.setFixedWidth(44)
            layout.addWidget(self._button)

        # Bidirectional sync
        self._slider.valueChanged.connect(self._on_slider_changed)
        self._slider.sliderReleased.connect(self.sliderReleased.emit)
        self._spinbox.valueChanged.connect(self._on_spinbox_changed)
        if self._button:
            self._button.clicked.connect(self.button_clicked)

        self._syncing = False  # prevent feedback loops

    # ------------------------------------------------------------------

    def _on_slider_changed(self, int_val: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        float_val = int_val / self._scale
        self._spinbox.setValue(float_val)
        self._syncing = False
        self.value_changed.emit(float_val)

    def _on_spinbox_changed(self, float_val: float) -> None:
        if self._syncing:
            return
        self._syncing = True
        self._slider.setValue(int(float_val * self._scale))
        self._syncing = False
        self.value_changed.emit(float_val)

    @property
    def value(self) -> float:
        return self._spinbox.value()

    @value.setter
    def value(self, v: float) -> None:
        self._spinbox.setValue(v)
        
class RangeSlider(QtWidgets.QSlider):
    """Custom double-handled range slider."""

    rangeChanged = QtCore.Signal(float, float)

    def __init__(self, orientation=QtCore.Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.first_position = 0
        self.second_position = 99
        self.setMinimum(0)
        self.setMaximum(99)

        self.offset = 10
        self.movement = 0
        self.isSliderDown = False

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            pos_x = event.pos().x()
            val = self.minimum() + ((self.maximum() - self.minimum()) * pos_x) / self.width()

            if abs(self.first_position - val) < abs(self.second_position - val):
                self.first_position = val
                self.movement = 1
            else:
                self.second_position = val
                self.movement = 2

            self.isSliderDown = True
            self.update()
            self._emit_range()

    def mouseMoveEvent(self, event):
        if self.isSliderDown:
            pos_x = event.pos().x()
            val = self.minimum() + ((self.maximum() - self.minimum()) * pos_x) / self.width()

            if self.movement == 1:
                self.first_position = max(0, min(val, self.second_position - 1))
            else:
                self.second_position = min(99, max(val, self.first_position + 1))

            self.update()
            self._emit_range()

    def mouseReleaseEvent(self, event):
        self.isSliderDown = False
        self.movement = 0

    def _emit_range(self):
        """Emit the current range as normalized values."""
        min_val = self.first_position / 99.0
        max_val = self.second_position / 99.0
        self.rangeChanged.emit(min_val, max_val)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        # Track
        track_rect = QtCore.QRect(
            self.offset, self.height() // 2 - 2,
                         self.width() - 2 * self.offset, 4
        )
        painter.fillRect(track_rect, QtGui.QColor(80, 80, 80))

        # Selected range
        x1 = int(self.offset + (self.first_position / 99.0) * (self.width() - 2 * self.offset))
        x2 = int(self.offset + (self.second_position / 99.0) * (self.width() - 2 * self.offset))

        range_rect = QtCore.QRect(x1, self.height() // 2 - 2, x2 - x1, 4)
        painter.fillRect(range_rect, QtGui.QColor(100, 180, 100))

        # Handles
        for pos in [self.first_position, self.second_position]:
            x = int(self.offset + (pos / 99.0) * (self.width() - 2 * self.offset))
            handle_rect = QtCore.QRect(x - 5, self.height() // 2 - 8, 10, 16)
            painter.setBrush(QtGui.QColor(200, 200, 200))
            painter.setPen(QtGui.QColor(100, 100, 100))
            painter.drawRoundedRect(handle_rect, 3, 3)

    def setRange(self, min_val: float, max_val: float):
        """Set range from normalized values (0-1)."""
        self.first_position = int(min_val * 99)
        self.second_position = int(max_val * 99)
        self.update()

class RangeSliderWithSpinbox(QtWidgets.QWidget):
    """Double-handle range slider flanked by two spinboxes.

    Layout::

        [spin_min] [══[▌]═══════[▐]══] [spin_max]

    Intentionally button-free so it composes freely in any parent layout.
    Typing a value outside the current limits **auto-extends** those limits.

    Signals:
        range_changed(float, float): Emitted on every handle / spinbox move.

    Args:
        limit_min: Lower bound (default ``0.0``).
        limit_max: Upper bound (default ``1.0``).
        decimals:  Decimal precision (default ``2``).
        parent:    Optional parent widget.

    Example::

        w = RangeSliderWithSpinbox(limit_min=0.0, limit_max=2.5)
        w.range_changed.connect(lambda lo, hi: print(lo, hi))
        w.set_limits(min_w, max_w)   # recalibrate from actual weights
    """

    range_changed = QtCore.Signal(float, float)

    def __init__(self,
                 limit_min: float = 0.0,
                 limit_max: float = 1.0,
                 decimals: int = 2,
                 parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        self._limit_min = limit_min
        self._limit_max = limit_max
        self._decimals = decimals
        self._syncing = False

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self._spin_min = QtWidgets.QDoubleSpinBox()
        self._spin_min.setLocale(QtCore.QLocale(QtCore.QLocale.English, QtCore.QLocale.UnitedStates))
        self._spin_min.setDecimals(decimals)
        self._spin_min.setSingleStep(10 ** -decimals)
        self._spin_min.setFixedWidth(60)
        self._spin_min.setRange(-9999.0, 9999.0)   # wide open — limits are logical only
        self._spin_min.setToolTip('Lower bound — type to extend the range')
        layout.addWidget(self._spin_min)

        self._slider = RangeSlider(QtCore.Qt.Horizontal)
        self._slider.setMinimumHeight(22)
        layout.addWidget(self._slider, stretch=1)

        self._spin_max = QtWidgets.QDoubleSpinBox()
        self._spin_max.setLocale(QtCore.QLocale(QtCore.QLocale.English, QtCore.QLocale.UnitedStates))
        self._spin_max.setDecimals(decimals)
        self._spin_max.setSingleStep(10 ** -decimals)
        self._spin_max.setFixedWidth(60)
        self._spin_max.setRange(-9999.0, 9999.0)   # wide open — limits are logical only
        self._spin_max.setToolTip('Upper bound — type to extend the range')
        layout.addWidget(self._spin_max)

        # Pre-seed spinbox values so set_limits clamps to the full range.
        # Block signals to avoid triggering _on_spin_*_changed before the
        # slider connections are wired — QDoubleSpinBox defaults to 0 which
        # would otherwise collapse both handles to the left.
        for sp, val in ((self._spin_min, limit_min), (self._spin_max, limit_max)):
            sp.blockSignals(True)
            sp.setValue(val)
            sp.blockSignals(False)
        self.set_limits(limit_min, limit_max)

        self._slider.rangeChanged.connect(self._on_slider_changed)
        self._spin_min.valueChanged.connect(self._on_spin_min_changed)
        self._spin_max.valueChanged.connect(self._on_spin_max_changed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_limits(self, limit_min: float, limit_max: float) -> None:
        """Recalibrate the logical slider bounds (does NOT restrict spinbox input).

        The spinboxes always accept any value in [-9999, 9999]; typing outside
        the current limits simply auto-extends them via the slot logic.
        """
        if limit_max <= limit_min:
            return
        self._limit_min = limit_min
        self._limit_max = limit_max
        self._push_to_slider()

    def set_range(self, lo: float, hi: float) -> None:
        """Set both handles programmatically, auto-extending limits if needed."""
        new_lim_min = min(lo, self._limit_min)
        new_lim_max = max(hi, self._limit_max)
        if new_lim_min < self._limit_min or new_lim_max > self._limit_max:
            self.set_limits(new_lim_min, new_lim_max)
        self._syncing = True
        self._spin_min.setValue(lo)
        self._spin_max.setValue(hi)
        self._syncing = False
        self._push_to_slider()
        self.range_changed.emit(self._spin_min.value(), self._spin_max.value())

    def snap_to_min(self) -> None:
        """Snap both handles to the current lower limit."""
        self.set_range(self._limit_min, self._limit_min)

    def snap_to_max(self) -> None:
        """Snap both handles to the current upper limit."""
        self.set_range(self._limit_max, self._limit_max)

    @property
    def low(self) -> float:
        return self._spin_min.value()

    @property
    def high(self) -> float:
        return self._spin_max.value()

    @property
    def limit_min(self) -> float:
        return self._limit_min

    @property
    def limit_max(self) -> float:
        return self._limit_max

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _to_norm(self, val: float) -> float:
        span = self._limit_max - self._limit_min
        return 0.0 if span == 0 else (val - self._limit_min) / span

    def _to_real(self, norm: float) -> float:
        return self._limit_min + norm * (self._limit_max - self._limit_min)

    def _push_to_slider(self) -> None:
        self._slider.first_position = int(self._to_norm(self._spin_min.value()) * 99)
        self._slider.second_position = int(self._to_norm(self._spin_max.value()) * 99)
        self._slider.update()

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_slider_changed(self, lo_norm: float, hi_norm: float) -> None:
        if self._syncing:
            return
        self._syncing = True
        self._spin_min.setValue(self._to_real(lo_norm))
        self._spin_max.setValue(self._to_real(hi_norm))
        self._syncing = False
        self.range_changed.emit(self._spin_min.value(), self._spin_max.value())

    def _on_spin_min_changed(self, val: float) -> None:
        if self._syncing:
            return
        # Auto-extend lower logical limit
        if val < self._limit_min:
            self._limit_min = val
        # Prevent min > max
        if val > self._spin_max.value():
            self._syncing = True
            self._spin_min.setValue(self._spin_max.value())
            self._syncing = False
        self._push_to_slider()
        self.range_changed.emit(self._spin_min.value(), self._spin_max.value())

    def _on_spin_max_changed(self, val: float) -> None:
        if self._syncing:
            return
        # Auto-extend upper logical limit
        if val > self._limit_max:
            self._limit_max = val
        # Prevent max < min
        if val < self._spin_min.value():
            self._syncing = True
            self._spin_max.setValue(self._spin_min.value())
            self._syncing = False
        self._push_to_slider()
        self.range_changed.emit(self._spin_min.value(), self._spin_max.value())

