"""
wgt_params.py - DemBones solve parameter panel.

One "Params" group box: the common params are always visible, the rest live
under a collapsible "Advanced" header. Each row is [spinbox][label] with a
fixed-width field so every control lines up; the description and any tips live
in the widget tooltip rather than the label text.

``get_params`` returns a flat dict keyed by the names ``dem_cmds.build_args``
expects; ``set_params`` restores them (used by the generations "Restore params"
action). main_ui wires the source panel's ``use_rig_changed`` signal to
``set_use_rig``, which greys out nBones (the bone count comes from the rig), and
``anim_only_changed`` to ``set_anim_only``, which forces and locks the three
params that make the solve transforms-only (the previous values come back when
the mode is switched off).
"""

from __future__ import annotations

from typing import Dict

from dw_maya.DemBones.compat import QtCore, QtWidgets


class ParamsPanel(QtWidgets.QWidget):
    """DemBones solve parameters: common rows + a collapsible Advanced block."""

    _FIELD_W = 100   # fixed field width so every spinbox/combo aligns

    # Params forced (and locked) by the anim-only mode -> transforms-only solve.
    _ANIM_ONLY_PARAMS = {
        "nWeightsIters": 0,   # freeze the weights we were given
        "nInitIters":    0,   # no re-clustering, the bones already exist
        "bindUpdate":    0,   # keep the bind pose / joint placement
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._anim_only = False
        self._saved_params = {}   # values stashed while anim-only is on
        self._build_ui()

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        box = QtWidgets.QGroupBox("Params")
        v = QtWidgets.QVBoxLayout(box)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(4)

        # One-line warning shown only with "Use existing rig"; the full
        # custom-joints explanation lives in its tooltip (hover to read).
        self.rig_note = QtWidgets.QLabel(
            "Warning: Use existing rig changes the params - hover for details.")
        self.rig_note.setToolTip(
            "Use existing rig: solving against your supplied joints.\n"
            "- nBones is ignored - the bone count comes from your skeleton.\n"
            "- Weights are solved by default (nWeightsIters > 0); your skin is "
            "the seed, not the final weights. Tick 'Animation only' in the "
            "source panel to keep them instead.\n"
            "- bindUpdate = 0 keeps your joint placement.\n"
            "Tip: a high nIters is rarely needed here - your placement already "
            "does the heavy lifting.")
        self.rig_note.setWordWrap(False)
        self.rig_note.setStyleSheet("QLabel { color: #d89b3a; }")
        self.rig_note.setVisible(False)
        v.addWidget(self.rig_note)

        # Shown with "Animation only": the locked params and what still matters.
        self.anim_note = QtWidgets.QLabel(
            "Animation only: weights frozen, transforms solved - hover.")
        self.anim_note.setToolTip(
            "Animation only: the target's existing skin weights are kept and "
            "only the joint transforms are solved.\n"
            "- nWeightsIters = 0, nInitIters = 0, bindUpdate = 0 (locked).\n"
            "- nTransIters is the only solve left - give it room (5-10).\n"
            "- nIters can stay low: with the weights frozen there is no "
            "alternation left to converge.\n"
            "- nBones / nnz / the weights-smoothing params are unused.")
        self.anim_note.setWordWrap(False)
        self.anim_note.setStyleSheet("QLabel { color: #6cc0c0; }")
        self.anim_note.setVisible(False)
        v.addWidget(self.anim_note)

        # -- Common params (always visible) -------------------------------
        common = QtWidgets.QGridLayout()
        common.setHorizontalSpacing(8)
        common.setVerticalSpacing(3)
        common.setColumnStretch(1, 1)
        r = 0

        self.n_bones = QtWidgets.QSpinBox()
        self.n_bones.setRange(1, 4096)
        self.n_bones.setValue(30)
        self._add_row(common, r, self.n_bones, "nBones (-b)",
                      "Number of bones (rigid segments) to solve for.\n"
                      "Higher = closer fit but a heavier skinCluster.\n"
                      "Disabled when 'Use existing rig' is on (the count then "
                      "comes from the supplied skeleton).")
        r += 1

        self.nnz = QtWidgets.QSpinBox()
        self.nnz.setRange(1, 32)
        self.nnz.setValue(8)
        self._add_row(common, r, self.nnz, "max influences (--nnz)",
                      "Max non-zero influences per vertex (joints skinning each "
                      "vertex).\nMaya and most engines cap this at 8.")
        r += 1

        self.n_iters = QtWidgets.QSpinBox()
        self.n_iters.setRange(1, 10000)
        self.n_iters.setValue(30)
        self._add_row(common, r, self.n_iters, "nIters (-n)",
                      "Global solver iterations (alternating bone-transform and "
                      "weight solves).\nMore = better convergence but slower.")
        r += 1

        self.n_trans_iters = QtWidgets.QSpinBox()
        self.n_trans_iters.setRange(0, 1000)
        self.n_trans_iters.setValue(5)
        self._add_row(common, r, self.n_trans_iters, "nTransIters",
                      "Bone-transform sub-iterations per global iteration.\n"
                      "0 = solve weights only (keep the current transforms).")
        r += 1

        self.n_weights_iters = QtWidgets.QSpinBox()
        self.n_weights_iters.setRange(0, 1000)
        self.n_weights_iters.setValue(3)
        self._add_row(common, r, self.n_weights_iters, "nWeightsIters",
                      "Weight sub-iterations per global iteration.\n"
                      "0 = solve transforms only (keep the current weights).")
        r += 1

        v.addLayout(common)

        # -- Advanced (collapsible) ---------------------------------------
        self.adv_toggle = QtWidgets.QToolButton()
        self.adv_toggle.setText("Advanced")
        self.adv_toggle.setCheckable(True)
        self.adv_toggle.setChecked(False)
        self.adv_toggle.setAutoRaise(True)
        self.adv_toggle.setArrowType(QtCore.Qt.RightArrow)
        self.adv_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.adv_toggle.setToolTip("Show every DemBones flag.")
        self.adv_toggle.toggled.connect(self._toggle_advanced)
        v.addWidget(self.adv_toggle)

        self._adv = QtWidgets.QWidget()
        adv = QtWidgets.QGridLayout(self._adv)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setHorizontalSpacing(8)
        adv.setVerticalSpacing(3)
        adv.setColumnStretch(1, 1)
        r = 0

        self.n_init_iters = QtWidgets.QSpinBox()
        self.n_init_iters.setRange(0, 1000)
        self.n_init_iters.setValue(10)
        self._add_row(adv, r, self.n_init_iters, "nInitIters",
                      "Initialization iterations for the bone clustering, before "
                      "the main solve begins.")
        r += 1

        self.weights_smooth = QtWidgets.QDoubleSpinBox()
        self.weights_smooth.setDecimals(8)
        self.weights_smooth.setRange(0.0, 1.0)
        self.weights_smooth.setSingleStep(1e-4)
        self.weights_smooth.setValue(1e-4)
        self._add_row(adv, r, self.weights_smooth, "weightsSmooth",
                      "Laplacian smoothing strength on the skin weights.\n"
                      "Higher = smoother but less detailed weights.")
        r += 1

        self.weights_smooth_step = QtWidgets.QDoubleSpinBox()
        self.weights_smooth_step.setDecimals(4)
        self.weights_smooth_step.setRange(0.0, 100.0)
        self.weights_smooth_step.setSingleStep(0.1)
        self.weights_smooth_step.setValue(1.0)
        self._add_row(adv, r, self.weights_smooth_step, "weightsSmoothStep",
                      "Step size for the weights-smoothing solve.\n"
                      "Lower = more stable but slower.")
        r += 1

        self.trans_affine = QtWidgets.QDoubleSpinBox()
        self.trans_affine.setDecimals(4)
        self.trans_affine.setRange(0.0, 1000.0)
        self.trans_affine.setSingleStep(1.0)
        self.trans_affine.setValue(10.0)
        self._add_row(adv, r, self.trans_affine, "transAffine",
                      "Allowed affine (non-rigid) bone transformation.\n"
                      "0 = pure rigid bones.")
        r += 1

        self.trans_affine_norm = QtWidgets.QDoubleSpinBox()
        self.trans_affine_norm.setDecimals(4)
        self.trans_affine_norm.setRange(0.0, 100.0)
        self.trans_affine_norm.setSingleStep(1.0)
        self.trans_affine_norm.setValue(4.0)
        self._add_row(adv, r, self.trans_affine_norm, "transAffineNorm",
                      "Normalization p-norm applied to the affine constraint.")
        r += 1

        self.bind_update = QtWidgets.QComboBox()
        self.bind_update.addItems(
            ["0 (keep bind)", "1 (update bind)", "2 (regroup root)"])
        self._add_row(adv, r, self.bind_update, "bindUpdate",
                      "How the bind pose is updated during the solve.")
        r += 1

        self.tolerance = QtWidgets.QDoubleSpinBox()
        self.tolerance.setDecimals(6)
        self.tolerance.setRange(0.0, 1.0)
        self.tolerance.setSingleStep(1e-3)
        self.tolerance.setValue(0.001)
        self._add_row(adv, r, self.tolerance, "tolerance",
                      "Convergence tolerance on the RMSE change; the solve stops "
                      "early once the improvement drops below this.")
        r += 1

        self.patience = QtWidgets.QSpinBox()
        self.patience.setRange(0, 100)
        self.patience.setValue(3)
        self._add_row(adv, r, self.patience, "patience",
                      "Number of stalled iterations to tolerate before the solve "
                      "stops early.")
        r += 1

        v.addWidget(self._adv)
        self._adv.setVisible(False)

        outer.addWidget(box)
        outer.addStretch(1)

    def _add_row(self, grid, row, widget, label_text, tip) -> None:
        """Add a [field][label] row: fixed-width field, tooltip on both."""
        widget.setFixedWidth(self._FIELD_W)
        widget.setToolTip(tip)
        label = QtWidgets.QLabel(label_text)
        label.setToolTip(tip)
        grid.addWidget(widget, row, 0)
        grid.addWidget(label, row, 1)

    def _toggle_advanced(self, on: bool) -> None:
        self.adv_toggle.setArrowType(
            QtCore.Qt.DownArrow if on else QtCore.Qt.RightArrow)
        self._adv.setVisible(on)

    # -- Slots ------------------------------------------------------------

    def set_use_rig(self, on: bool) -> None:
        # In rig mode the bone count is dictated by the supplied skeleton.
        self.n_bones.setEnabled(not bool(on))
        self.rig_note.setVisible(bool(on))

    def set_anim_only(self, on: bool) -> None:
        """Force (and lock) the transforms-only params, or give them back.

        Args:
            on: True to freeze the supplied weights and solve transforms only.
        """
        on = bool(on)
        if on == self._anim_only:
            return
        self._anim_only = on

        if on:
            self._saved_params = {key: self._get_value(key)
                                  for key in self._ANIM_ONLY_PARAMS}
            for key, value in self._ANIM_ONLY_PARAMS.items():
                self._set_value(key, value)
        else:
            for key, value in self._saved_params.items():
                self._set_value(key, value)
            self._saved_params = {}

        for key in self._ANIM_ONLY_PARAMS:
            self._widget(key).setEnabled(not on)
        self.anim_note.setVisible(on)

    # -- Locked-param helpers ---------------------------------------------

    def _widget(self, key: str):
        """Return the widget backing an anim-only param key."""
        return {
            "nWeightsIters": self.n_weights_iters,
            "nInitIters":    self.n_init_iters,
            "bindUpdate":    self.bind_update,
        }[key]

    def _get_value(self, key: str) -> int:
        widget = self._widget(key)
        if isinstance(widget, QtWidgets.QComboBox):
            return widget.currentIndex()
        return widget.value()

    def _set_value(self, key: str, value: int) -> None:
        widget = self._widget(key)
        if isinstance(widget, QtWidgets.QComboBox):
            widget.setCurrentIndex(int(value))
        else:
            widget.setValue(int(value))

    # -- Public API -------------------------------------------------------

    def get_params(self) -> Dict:
        """Return the flat param dict for ``dem_cmds.build_args``."""
        return {
            "nBones":            self.n_bones.value(),
            "nnz":               self.nnz.value(),
            "nIters":            self.n_iters.value(),
            "nTransIters":       self.n_trans_iters.value(),
            "nWeightsIters":     self.n_weights_iters.value(),
            "nInitIters":        self.n_init_iters.value(),
            "weightsSmooth":     self.weights_smooth.value(),
            "weightsSmoothStep": self.weights_smooth_step.value(),
            "transAffine":       self.trans_affine.value(),
            "transAffineNorm":   self.trans_affine_norm.value(),
            "bindUpdate":        self.bind_update.currentIndex(),
            "tolerance":         self.tolerance.value(),
            "patience":          self.patience.value(),
        }

    def set_params(self, params: Dict) -> None:
        """Restore widget values from a param dict (missing keys left as-is).

        While anim-only is on the three locked params are not written to the
        widgets - they go to the stash instead, so they come back correctly
        when the mode is switched off rather than being overwritten by the
        forced zeros.
        """
        if self._anim_only:
            params = dict(params)
            for key in self._ANIM_ONLY_PARAMS:
                if key in params:
                    self._saved_params[key] = int(params.pop(key))

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
        if "nInitIters" in params:
            self.n_init_iters.setValue(int(params["nInitIters"]))
        if "weightsSmooth" in params:
            self.weights_smooth.setValue(float(params["weightsSmooth"]))
        if "weightsSmoothStep" in params:
            self.weights_smooth_step.setValue(float(params["weightsSmoothStep"]))
        if "transAffine" in params:
            self.trans_affine.setValue(float(params["transAffine"]))
        if "transAffineNorm" in params:
            self.trans_affine_norm.setValue(float(params["transAffineNorm"]))
        if "bindUpdate" in params:
            self.bind_update.setCurrentIndex(int(params["bindUpdate"]))
        if "tolerance" in params:
            self.tolerance.setValue(float(params["tolerance"]))
        if "patience" in params:
            self.patience.setValue(int(params["patience"]))