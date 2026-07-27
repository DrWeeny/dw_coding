"""Curve-based contrast / remap popup for Slimfast.

A non-modal editor that reshapes the active source's weights through a
draggable 0-1 curve -- an S-curve to add contrast, an inverse ramp to flip,
etc. It follows a deliberately simple, Maya-friendly model:

Model (one-shot transform on a frozen snapshot):
    - The weight map on the node is the single source of truth.
    - On open, the current weights are snapshotted as the frozen input.
    - The curve maps input -> output; the output is written back for a live
      preview via the controller's SILENT (non-undoable) path, so dragging
      the curve updates the viewport without spamming the undo queue.
    - Apply commits the change as ONE undoable step (original -> final);
      Cancel / close restores the snapshot.

    Full transform, with input domain and output range both exposed::

        w' = out_lo + (out_hi - out_lo) * curve((w - in_lo) / (in_hi - in_lo))

    - in_lo / in_hi (input domain): frozen at open. "Fit to data range" maps
      the curve across the actual painted min/max (default); unchecked maps
      it across an absolute 0-1.
    - out_lo / out_hi (output range): defaults to the input range (pure,
      range-preserving contrast); override to contrast AND retarget the
      range in one apply (subsumes remap-fit).

There is deliberately no persistent "curve layer": Maya has no weight-layer
stack, so once the artist paints again the contrasted values ARE the map.
Re-opening the editor simply snapshots afresh.

While the editor is open, the caller (main_ui) disables the weight-mutating
buttons (paint / flood / smooth / remap) so a paint stroke can't race the
live preview -- a soft lock, not a hard modal, so the viewport stays
navigable for judging the contrast.

Classes:
    CurveRemapDialog -- the non-modal curve editor.

Example::

    dlg = CurveRemapDialog(controller, parent=main_window)
    dlg.finished.connect(reenable_buttons)
    dlg.show()

Author: DrWeeny
"""

from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

try:
    from PySide6 import QtCore, QtWidgets
    from PySide6.QtCore import Slot
except ImportError:
    from PySide2 import QtCore, QtWidgets
    from PySide2.QtCore import Slot

from dw_maya.dw_pyqt_utils.wgt_ramp_curve import RampCurveWidget
from dw_logger import get_logger

if TYPE_CHECKING:
    from dw_maya.Slimfast.cmds import SlimfastController

logger = get_logger()


class CurveRemapDialog(QtWidgets.QDialog):
    """Non-modal curve-based contrast / remap editor for the active source."""

    _LUT_SIZE = 256
    # Above this vertex count, debounce the live preview so a drag doesn't
    # write the whole map on every mouse-move event.
    _HEAVY_VTX = 60000

    def __init__(self,
                 controller: 'SlimfastController',
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._ctrl = controller
        self._applied = False
        self._closed = False

        self.setWindowTitle('Curve Remap / Contrast')
        self.setModal(False)
        self.setMinimumWidth(280)

        # -- Snapshot the frozen input (single source of truth stays the map).
        # Capture the source object itself so a mid-session selection change
        # can't retarget writes to a different mesh.
        self._source = controller.active_source
        source = self._source
        self._snapshot: List[float] = list(source.get_weights()) if source else []
        self._n = len(self._snapshot)

        # Frozen vertex mask: restrict the contrast to the selected verts
        # (captured once at open, like the snapshot). None = whole mesh.
        mask_ids = controller.selection_vtx_ids() if source else None
        self._mask = set(mask_ids) if mask_ids else None

        # The data range is computed over the AFFECTED verts only, so the
        # curve spans what will actually change, not the untouched remainder.
        affected = ([self._snapshot[i] for i in self._mask if i < self._n]
                    if self._mask else self._snapshot)
        self._data_lo = min(affected) if affected else 0.0
        self._data_hi = max(affected) if affected else 1.0

        self._build_ui()

        heavy = self._n > self._HEAVY_VTX
        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(40 if heavy else 0)
        self._preview_timer.timeout.connect(self._preview)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lay = QtWidgets.QVBoxLayout(self)

        scope = (f'{len(self._mask)} selected verts' if self._mask
                 else f'{self._n} verts (whole mesh)')
        info = QtWidgets.QLabel(
            f'{scope}  ·  range [{self._data_lo:.3f}, {self._data_hi:.3f}]'
        )
        info.setStyleSheet('color: #999;')
        lay.addWidget(info)

        self._curve = RampCurveWidget()
        self._curve.setMinimumSize(240, 200)
        self._curve.curveChanged.connect(self._schedule_preview)
        lay.addWidget(self._curve)

        # Input domain
        self._fit_check = QtWidgets.QCheckBox('Fit curve to data range')
        self._fit_check.setChecked(True)
        self._fit_check.setToolTip(
            'On: the curve spans the actual painted min/max.\n'
            'Off: the curve spans an absolute 0-1.'
        )
        self._fit_check.toggled.connect(self._schedule_preview)
        lay.addWidget(self._fit_check)

        # Output range
        out_row = QtWidgets.QHBoxLayout()
        out_row.addWidget(QtWidgets.QLabel('Out'))
        self._out_min = QtWidgets.QDoubleSpinBox()
        self._out_max = QtWidgets.QDoubleSpinBox()
        for sp, val in ((self._out_min, self._data_lo), (self._out_max, self._data_hi)):
            sp.setRange(-99.0, 99.0)
            sp.setDecimals(3)
            sp.setSingleStep(0.05)
            sp.setValue(val)
            sp.setFixedWidth(72)
            sp.valueChanged.connect(self._schedule_preview)
        out_row.addWidget(QtWidgets.QLabel('min'))
        out_row.addWidget(self._out_min)
        out_row.addWidget(QtWidgets.QLabel('max'))
        out_row.addWidget(self._out_max)
        out_row.addStretch()
        lay.addLayout(out_row)

        # Buttons
        btn_row = QtWidgets.QHBoxLayout()
        reset_btn = QtWidgets.QPushButton('Reset Curve')
        reset_btn.clicked.connect(self._curve.reset)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()

        cancel_btn = QtWidgets.QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        apply_btn = QtWidgets.QPushButton('Apply')
        apply_btn.setStyleSheet(
            'QPushButton { background-color: #504040; color: white; }'
            'QPushButton:hover { background-color: #705050; }'
        )
        apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(apply_btn)
        lay.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Transform
    # ------------------------------------------------------------------

    def _compute_final(self) -> List[float]:
        """Apply the 4-param curve transform to the frozen snapshot."""
        fit = self._fit_check.isChecked()
        in_lo = self._data_lo if fit else 0.0
        in_hi = self._data_hi if fit else 1.0
        out_lo = self._out_min.value()
        out_hi = self._out_max.value()
        span = in_hi - in_lo

        # Sample the curve once into a LUT, then map each weight through it
        # (pure python -- no numpy dependency, fast enough for the meshes
        # this tool paints).
        last = self._LUT_SIZE - 1
        lut = [self._curve.evaluate(i / last) for i in range(self._LUT_SIZE)]
        out_range = out_hi - out_lo

        degenerate = abs(span) < 1e-9
        mask = self._mask

        result = []
        for i, w in enumerate(self._snapshot):
            # Outside the frozen mask -> leave the weight untouched.
            if mask is not None and i not in mask:
                result.append(w)
                continue
            if degenerate:
                # Flat domain (all affected verts equal): map through curve(0).
                result.append(out_lo + out_range * lut[0])
                continue
            t = (w - in_lo) / span
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            # Linear-interpolate between LUT samples so a smooth gradient
            # doesn't band on the 256-step quantisation.
            f = t * last
            i0 = int(f)
            if i0 >= last:
                y = lut[last]
            else:
                frac = f - i0
                y = lut[i0] * (1.0 - frac) + lut[i0 + 1] * frac
            result.append(out_lo + out_range * y)
        return result

    # ------------------------------------------------------------------
    # Preview / commit / restore
    # ------------------------------------------------------------------

    @Slot()
    def _schedule_preview(self, *args) -> None:
        """Coalesce rapid curve/spinbox changes into one preview write."""
        self._preview_timer.start()

    def _preview(self) -> None:
        if self._closed or not self._snapshot:
            return
        try:
            self._ctrl.preview_weights(self._compute_final(), source=self._source)
        except Exception as e:
            logger.warning(f"Curve preview failed: {e}")

    def _restore(self) -> None:
        """Silently put the snapshot back (cancel / close without apply)."""
        if not self._snapshot:
            return
        try:
            self._ctrl.preview_weights(self._snapshot, source=self._source)
        except Exception as e:
            logger.warning(f"Curve restore failed: {e}")

    @Slot()
    def _on_apply(self) -> None:
        self._preview_timer.stop()
        if self._snapshot:
            try:
                self._ctrl.commit_weights(self._snapshot, self._compute_final(),
                                          source=self._source)
            except Exception as e:
                logger.error(f"Curve apply failed: {e}")
        self._applied = True
        self._closed = True
        self.accept()

    # ------------------------------------------------------------------
    # Lifecycle -- restore snapshot on any close that isn't an Apply
    # ------------------------------------------------------------------

    def reject(self) -> None:
        # QDialog.closeEvent (window X) also routes here, so this is the one
        # place that handles every non-Apply close.
        self._preview_timer.stop()
        if not self._applied:
            self._restore()
        self._closed = True
        super().reject()