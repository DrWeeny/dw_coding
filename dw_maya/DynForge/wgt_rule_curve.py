"""
wgt_rule_curve.py - edit a per-bone rule as a curve.

Summary:
    The same rule as the typed keys ("0:1, 1:.5:smooth, 2:.1"), drawn on the
    Slimfast RampCurveWidget (dw_pyqt_utils.wgt_ramp_curve): x runs from the
    chain's root to its tip, y from Low to High. A tick marks where each bone
    of the chain samples the curve, with the value it would get, so the shape
    is judged against the bones it drives rather than in the abstract.

    Low / High only scale the 0..1 grid (a collision radius of 5.5 does not
    fit in 0..1); changing them keeps the drawn shape. OK writes the curve back
    as keys - in bone units when the chain is known, so "1:..." still reads as
    the second bone.

Classes:
    BoneTickRamp - RampCurveWidget that also draws the bone samples.
    RuleCurveDialog - the dialog; keys_text() after exec.

Author:
    DrWeeny
"""

from __future__ import annotations

from dw_maya.DynForge.forge_cmds import param_rules
from dw_maya.DynForge.forge_cmds.compat import QtCore, QtGui, QtWidgets
from dw_maya.dw_pyqt_utils.wgt_ramp_curve import RampCurveWidget


class BoneTickRamp(RampCurveWidget):
    """RampCurveWidget plus one tick per bone at the value the curve gives it."""

    def __init__(self,
                 bones: int = 0,
                 parent=None,) -> None:
        super().__init__(parent)
        self.bones = bones
        self.setMinimumHeight(180)
        self.curveChanged.connect(self.update)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.bones < 2:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor(230, 160, 60, 170))
        pen.setStyle(QtCore.Qt.DotLine)
        for index in range(self.bones):
            x = index / (self.bones - 1)
            top = self._to_widget(x, 1.0)
            bottom = self._to_widget(x, 0.0)
            painter.setPen(pen)
            painter.drawLine(top, bottom)
            sample = self._to_widget(x, self.evaluate(x))
            painter.setPen(QtGui.QPen(QtGui.QColor(230, 160, 60)))
            painter.setBrush(QtGui.QColor(230, 160, 60))
            painter.drawEllipse(sample, 3, 3)
        painter.end()


class RuleCurveDialog(QtWidgets.QDialog):
    """Edit one rule's keys as a curve over the chain."""

    def __init__(self,
                 keys_text: str,
                 bones:     int = 0,
                 title:     str = "",
                 parent=None,) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Rule curve - {title}" if title else "Rule curve")
        self._bones = bones
        try:
            keys = param_rules.parse_keys(keys_text)
        except ValueError:
            keys = param_rules.parse_keys("0:1, 1:1")
        if len(keys) == 1:   # a curve needs both ends
            keys = [(0.0, keys[0][1], "linear"), (1.0, keys[0][1], "linear")]
        low, high = param_rules.value_range(keys)
        self._build_ui(low, high)
        self._ramp.control_points = param_rules.to_curve(keys, low, high)
        self._update_preview()

    def _build_ui(self,
                  low:  float,
                  high: float,) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        self._ramp = BoneTickRamp(self._bones)
        layout.addWidget(self._ramp, stretch=1)

        range_row = QtWidgets.QHBoxLayout()
        self._low = self._spin(low)
        self._high = self._spin(high)
        range_row.addWidget(QtWidgets.QLabel("Low"))
        range_row.addWidget(self._low)
        range_row.addWidget(QtWidgets.QLabel("High"))
        range_row.addWidget(self._high)
        range_row.addStretch()
        layout.addLayout(range_row)

        self._preview = QtWidgets.QLabel()
        self._preview.setWordWrap(True)
        self._preview.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self._preview)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._ramp.curveChanged.connect(self._update_preview)
        self._low.valueChanged.connect(self._update_preview)
        self._high.valueChanged.connect(self._update_preview)
        self.resize(460, 380)

    @staticmethod
    def _spin(value: float) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setDecimals(3)
        spin.setRange(-1e6, 1e6)
        spin.setSingleStep(0.05)
        spin.setValue(value)
        return spin

    def keys(self) -> list:
        return param_rules.from_curve(self._ramp.control_points, self._low.value(), self._high.value(), self._bones)

    def keys_text(self) -> str:
        """The curve as keys text, what the rules table stores."""
        return param_rules.format_keys(self.keys())

    def _update_preview(self, *_args) -> None:
        text = f"Keys: {self.keys_text()}"
        if self._bones:
            values = param_rules.evaluate(self.keys(), self._bones)
            text += f"\nOn this chain ({self._bones} bones): " + ", ".join(f"{v:.3g}" for v in values)
        self._preview.setText(text)
