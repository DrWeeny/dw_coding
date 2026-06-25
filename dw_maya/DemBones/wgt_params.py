"""
wgt_params.py - DemBones solve parameter panel.

Basic params (always visible) + an Advanced collapsible group. ``get_params``
returns a flat dict keyed by the names ``dem_cmds.build_args`` expects;
``set_params`` restores them (used by the generations "Restore params" action).

main_ui wires the source panel's ``use_rig_changed`` signal to ``set_use_rig``,
which greys out nBones (bone count comes from the rig in that mode).
"""

from __future__ import annotations

from typing import Dict

from dw_maya.DemBones.compat import QtWidgets


class ParamsPanel(QtWidgets.QWidget):
    """Basic + advanced DemBones solve parameters."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Basic
        basic = QtWidgets.QGroupBox("Params")
        bform = QtWidgets.QFormLayout(basic)

        self.n_bones = QtWidgets.QSpinBox()
        self.n_bones.setRange(1, 4096)
        self.n_bones.setValue(100)
        bform.addRow("nBones (-b)", self.n_bones)

        self.nnz = QtWidgets.QSpinBox()
        self.nnz.setRange(1, 32)
        self.nnz.setValue(8)
        bform.addRow("max influences (--nnz)", self.nnz)

        self.n_iters = QtWidgets.QSpinBox()
        self.n_iters.setRange(1, 10000)
        self.n_iters.setValue(100)
        bform.addRow("nIters (-n)", self.n_iters)

        outer.addWidget(basic)

        # Advanced (collapsible via checkable group box)
        adv = QtWidgets.QGroupBox("Advanced")
        adv.setCheckable(True)
        adv.setChecked(False)
        self._adv_box = adv
        aform = QtWidgets.QFormLayout(adv)

        self.n_trans_iters = QtWidgets.QSpinBox()
        self.n_trans_iters.setRange(0, 1000)
        self.n_trans_iters.setValue(10)
        aform.addRow("nTransIters (0=weights only)", self.n_trans_iters)

        self.n_weights_iters = QtWidgets.QSpinBox()
        self.n_weights_iters.setRange(0, 1000)
        self.n_weights_iters.setValue(3)
        aform.addRow("nWeightsIters (0=transforms only)", self.n_weights_iters)

        self.weights_smooth = QtWidgets.QDoubleSpinBox()
        self.weights_smooth.setDecimals(8)
        self.weights_smooth.setRange(0.0, 1.0)
        self.weights_smooth.setSingleStep(1e-4)
        self.weights_smooth.setValue(1e-4)
        aform.addRow("weightsSmooth", self.weights_smooth)

        self.bind_update = QtWidgets.QComboBox()
        self.bind_update.addItems(["0 (keep bind)", "1 (update bind)", "2 (regroup root)"])
        aform.addRow("bindUpdate", self.bind_update)

        self.tolerance = QtWidgets.QDoubleSpinBox()
        self.tolerance.setDecimals(6)
        self.tolerance.setRange(0.0, 1.0)
        self.tolerance.setSingleStep(1e-3)
        self.tolerance.setValue(0.001)
        aform.addRow("tolerance", self.tolerance)

        self.patience = QtWidgets.QSpinBox()
        self.patience.setRange(0, 100)
        self.patience.setValue(3)
        aform.addRow("patience", self.patience)

        # Collapse children when unchecked.
        adv.toggled.connect(self._toggle_advanced)
        self._toggle_advanced(False)

        outer.addWidget(adv)
        outer.addStretch(1)

    def _toggle_advanced(self, on: bool) -> None:
        for i in range(self._adv_box.layout().count()):
            item = self._adv_box.layout().itemAt(i).widget()
            if item is not None:
                item.setVisible(on)

    # -- Slots ------------------------------------------------------------

    def set_use_rig(self, on: bool) -> None:
        # In rig mode the bone count is dictated by the supplied skeleton.
        self.n_bones.setEnabled(not bool(on))

    # -- Public API -------------------------------------------------------

    def get_params(self) -> Dict:
        """Return the flat param dict for ``dem_cmds.build_args``."""
        return {
            "nBones":        self.n_bones.value(),
            "nnz":           self.nnz.value(),
            "nIters":        self.n_iters.value(),
            "nTransIters":   self.n_trans_iters.value(),
            "nWeightsIters": self.n_weights_iters.value(),
            "weightsSmooth": self.weights_smooth.value(),
            "bindUpdate":    self.bind_update.currentIndex(),
            "tolerance":     self.tolerance.value(),
            "patience":      self.patience.value(),
        }

    def set_params(self, params: Dict) -> None:
        """Restore widget values from a param dict (missing keys left as-is)."""
        if "nBones" in params:
            self.n_bones.setValue(int(params["nBones"]))
        if "nnz" in params:
            self.nnz.setValue(int(params["nnz"]))
        if "nIters" in params:
            self.n_iters.setValue(int(params["nIters"]))
        if "nTransIters" in params:
            self.n_trans_iters.setValue(int(params["nTransIters"]))
        if "nWeightsIters" in params:
            self.n_weights_iters.setValue(int(params["nWeightsIters"]))
        if "weightsSmooth" in params:
            self.weights_smooth.setValue(float(params["weightsSmooth"]))
        if "bindUpdate" in params:
            self.bind_update.setCurrentIndex(int(params["bindUpdate"]))
        if "tolerance" in params:
            self.tolerance.setValue(float(params["tolerance"]))
        if "patience" in params:
            self.patience.setValue(int(params["patience"]))