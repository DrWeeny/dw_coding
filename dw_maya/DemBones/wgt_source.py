"""
wgt_source.py - DemBones source panel.

Two meshes drive a solve:

    Source mesh (abc)   the deformed, Alembic-driven mesh - the motion to match.
                        Picking it derives the abc path + frame range from its
                        history.
    Target mesh (rest)  the static, non-animated mesh that will carry the
                        skinCluster. By default it is auto-created by duplicating
                        the source at the alembic's first frame ("create rest on
                        pick"); the user can also pick their own.

The panel keeps no shared state - main_ui reads its values through the public
getters at solve time, and connects ``use_rig_changed`` / ``anim_only_changed``
to the params panel.

"Animation only" is a solve mode, not a param: the target's existing skin
weights are frozen and only the joint transforms (the anim curves) are solved.
It needs the weights in the init FBX, so it depends on "Use existing rig" -
the checkbox stays disabled until that is on, and ticking it programmatically
turns use-rig on too.

Public API
----------
    source_mesh()  -> str
    target_mesh()  -> str
    abc_path()     -> str
    frame_range()  -> (int, int)
    use_rig()      -> bool
    anim_only()    -> bool
    topo_valid()   -> bool
    set_anim_only(bool)

Signals
-------
    use_rig_changed(bool)
    anim_only_changed(bool)
"""

from __future__ import annotations

from maya import cmds

from dw_maya.DemBones.compat import QtCore, QtWidgets, Signal
from dw_maya.DemBones import dem_cmds
from dw_logger import get_logger

logger = get_logger()

_OK_STYLE = "QLineEdit { background: #1e3b1e; }"      # green-ish
_BAD_STYLE = "QLineEdit { background: #3b1e1e; }"     # red-ish
_NEUTRAL_STYLE = ""


class SourcePanel(QtWidgets.QWidget):
    """Source (abc) + target (rest) meshes, abc path, range, use-rig inputs."""

    use_rig_changed = Signal(bool)
    anim_only_changed = Signal(bool)
    target_mesh_changed = Signal(str)

    _ANIM_ONLY_TIP = (
        "Animation only: keep the target's existing skin weights and solve the "
        "joint transforms (anim curves) only.\n"
        "Use it to re-solve a new cache against weights a previous generation "
        "already produced.\n"
        "Sets nWeightsIters = 0, nInitIters = 0, bindUpdate = 0.")
    _ANIM_ONLY_TIP_OFF = (
        "'Use existing rig' is necessary - the weights to keep must be exported "
        "with the rest mesh.\n\n" + _ANIM_ONLY_TIP)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._abc_node = None
        self._topo_valid = True
        self._build_ui()
        self._connect()

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        box = QtWidgets.QGroupBox("Source")
        form = QtWidgets.QFormLayout(box)
        form.setContentsMargins(8, 6, 8, 6)
        form.setVerticalSpacing(3)
        form.setHorizontalSpacing(6)
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        # Source mesh (abc-driven) + pick + auto-create toggle
        src_row = QtWidgets.QHBoxLayout()
        self.source_field = QtWidgets.QLineEdit()
        self.source_field.setReadOnly(True)
        self.source_pick_btn = QtWidgets.QPushButton("Pick")
        self.create_chk = QtWidgets.QCheckBox("create rest on pick")
        self.create_chk.setChecked(True)
        self.create_chk.setToolTip(
            "On pick, duplicate the source at the alembic's first frame to make "
            "the rest (target) mesh.")
        src_row.addWidget(self.source_field, 1)
        src_row.addWidget(self.source_pick_btn)
        src_row.addWidget(self.create_chk)
        form.addRow("Src mesh (abc)", self._wrap(src_row))

        # Target mesh (rest) + pick
        tgt_row = QtWidgets.QHBoxLayout()
        self.target_field = QtWidgets.QLineEdit()
        self.target_field.setReadOnly(True)
        self.target_pick_btn = QtWidgets.QPushButton("Pick")
        tgt_row.addWidget(self.target_field, 1)
        tgt_row.addWidget(self.target_pick_btn)
        form.addRow("Target mesh", self._wrap(tgt_row))

        self.vtx_label = QtWidgets.QLabel("-")
        form.addRow("Is Valid", self.vtx_label)

        # ABC path + browse
        abc_row = QtWidgets.QHBoxLayout()
        self.abc_field = QtWidgets.QLineEdit()
        self.browse_btn = QtWidgets.QPushButton("...")
        self.browse_btn.setMaximumWidth(30)
        abc_row.addWidget(self.abc_field, 1)
        abc_row.addWidget(self.browse_btn)
        form.addRow("Alembic", self._wrap(abc_row))

        # Frame range + auto
        range_row = QtWidgets.QHBoxLayout()
        self.start_spin = QtWidgets.QSpinBox()
        self.start_spin.setRange(-100000, 100000)
        self.end_spin = QtWidgets.QSpinBox()
        self.end_spin.setRange(-100000, 100000)
        self.auto_combo = QtWidgets.QComboBox()
        self.auto_combo.addItems(["timeline", "alembic"])
        self.auto_btn = QtWidgets.QPushButton("auto")
        range_row.addWidget(QtWidgets.QLabel("start"))
        range_row.addWidget(self.start_spin)
        range_row.addWidget(QtWidgets.QLabel("end"))
        range_row.addWidget(self.end_spin)
        range_row.addWidget(self.auto_combo)
        range_row.addWidget(self.auto_btn)
        form.addRow("Range", self._wrap(range_row))

        # Use rig + anim-only mode + status
        rig_row = QtWidgets.QHBoxLayout()
        self.use_rig_chk = QtWidgets.QCheckBox("Use existing rig")
        self.use_rig_chk.setToolTip(
            "Solve against the target's own skeleton instead of clustering new "
            "bones (the init FBX is exported with its skin + joints).")
        self.anim_only_chk = QtWidgets.QCheckBox("Animation only")
        self.anim_only_chk.setEnabled(False)
        self.anim_only_chk.setToolTip(self._ANIM_ONLY_TIP_OFF)
        self.rig_status = QtWidgets.QLabel("")
        rig_row.addWidget(self.use_rig_chk)
        rig_row.addWidget(self.anim_only_chk)
        rig_row.addWidget(self.rig_status, 1)
        form.addRow("Rig", self._wrap(rig_row))

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)

    @staticmethod
    def _wrap(layout) -> QtWidgets.QWidget:
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        w = QtWidgets.QWidget()
        w.setLayout(layout)
        return w

    def _connect(self) -> None:
        self.source_pick_btn.clicked.connect(self._on_pick_source)
        self.target_pick_btn.clicked.connect(self._on_pick_target)
        self.browse_btn.clicked.connect(self._on_browse)
        self.auto_btn.clicked.connect(self._on_auto_range)
        self.use_rig_chk.toggled.connect(self._on_use_rig)
        self.anim_only_chk.toggled.connect(self._on_anim_only)
        self.target_field.editingFinished.connect(self._emit_target_changed)


        # -- Public getters ---------------------------------------------------

    def source_mesh(self) -> str:
        return self.source_field.text()

    def target_mesh(self) -> str:
        return self.target_field.text()

    def abc_path(self) -> str:
        return self.abc_field.text()

    def frame_range(self):
        return self.start_spin.value(), self.end_spin.value()

    def use_rig(self) -> bool:
        return self.use_rig_chk.isChecked()

    def anim_only(self) -> bool:
        return self.anim_only_chk.isChecked()

    def topo_valid(self) -> bool:
        return self._topo_valid

    # -- Public setters ---------------------------------------------------

    def set_anim_only(self, on: bool) -> None:
        """Set the anim-only mode, turning use-rig on first when needed.

        Used to restore the mode from a generation sidecar; a plain
        ``setChecked`` would be refused while the box is still disabled.
        """
        if on and not self.use_rig_chk.isChecked():
            self.use_rig_chk.setChecked(True)
        self.anim_only_chk.setChecked(bool(on))

    # -- Slots ------------------------------------------------------------

    def _emit_target_changed(self) -> None:
        self.target_mesh_changed.emit(self.target_field.text())

    def _on_pick_source(self) -> None:
        sel = cmds.ls(selection=True, long=True) or []
        if not sel:
            QtWidgets.QMessageBox.information(self, "DemBones", "Select the abc mesh first.")
            return
        source = sel[0]
        self.source_field.setText(source)

        # Derive abc + range from the mesh history.
        self._abc_node = dem_cmds.find_alembic_node(source)
        if self._abc_node:
            abc_path = dem_cmds.alembic_file_path(self._abc_node)
            if abc_path:
                self.abc_field.setText(abc_path)
            rng = dem_cmds.alembic_frame_range(self._abc_node)
            if rng:
                self._set_range(*rng)

        # Auto-create the rest (target) mesh from the first frame.
        if self.create_chk.isChecked():
            self._create_rest(source)

        self._validate()
        self._refresh_rig_status()

    def _on_pick_target(self) -> None:
        sel = cmds.ls(selection=True, long=True) or []
        if not sel:
            QtWidgets.QMessageBox.information(self, "DemBones", "Select the rest mesh first.")
            return
        self.target_field.setText(sel[0])
        self._validate()
        self._refresh_rig_status()

    def _on_browse(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Alembic cache", "", "Alembic (*.abc)")
        if path:
            self.abc_field.setText(path)

    def _on_auto_range(self) -> None:
        mode = self.auto_combo.currentText()
        if mode == "timeline":
            self._set_range(*dem_cmds.timeline_range())
        elif mode == "alembic" and self._abc_node:
            rng = dem_cmds.alembic_frame_range(self._abc_node)
            if rng:
                self._set_range(*rng)
            else:
                QtWidgets.QMessageBox.information(
                    self, "DemBones", "No frame range found on the Alembic node.")
        else:
            QtWidgets.QMessageBox.information(
                self, "DemBones", "Pick an abc-driven mesh first for alembic range.")

    def _on_use_rig(self, checked: bool) -> None:
        # Anim-only needs the weights inside the init FBX, which only the
        # use-rig export writes - so it follows use-rig on and off.
        self.anim_only_chk.setEnabled(bool(checked))
        self.anim_only_chk.setToolTip(
            self._ANIM_ONLY_TIP if checked else self._ANIM_ONLY_TIP_OFF)
        if not checked and self.anim_only_chk.isChecked():
            self.anim_only_chk.setChecked(False)   # emits anim_only_changed
        self.use_rig_changed.emit(checked)
        self._refresh_rig_status()

    def _on_anim_only(self, checked: bool) -> None:
        if checked and not self.use_rig_chk.isChecked():
            self.use_rig_chk.setChecked(True)      # emits use_rig_changed
        self.anim_only_changed.emit(checked)
        self._refresh_rig_status()

    # -- Helpers ----------------------------------------------------------

    def _create_rest(self, source: str) -> None:
        """Duplicate the source at the start frame into the target field."""
        try:
            start = self.start_spin.value()
            target = dem_cmds.create_rest_duplicate(source, start)
            self.target_field.setText(target)
        except Exception as e:
            logger.error(f"Could not create rest mesh: {e}")
            QtWidgets.QMessageBox.warning(
                self, "DemBones", f"Could not create rest mesh:\n{e}")

    def _set_range(self, start: int, end: int) -> None:
        self.start_spin.setValue(int(start))
        self.end_spin.setValue(int(end))

    def _validate(self) -> None:
        target = self.target_field.text()
        source = self.source_field.text()
        if not target:
            return
        target_n, source_n, valid = dem_cmds.validate_topology(target, source)
        self._topo_valid = valid
        if source_n is None:
            self.vtx_label.setText(f"{target_n}")
            self.target_field.setStyleSheet(_NEUTRAL_STYLE)
            tip = (f"Target mesh: {target_n} vertices.\n"
                   f"Pick a source (abc) mesh to check the two match.")
        elif valid:
            self.vtx_label.setText(f"{target_n}  (matches source)")
            self.target_field.setStyleSheet(_OK_STYLE)
            tip = (f"Target and source both have {target_n} vertices - the "
                   f"solve can run.")
        else:
            self.vtx_label.setText(f"{target_n}  != source {source_n}")
            self.target_field.setStyleSheet(_BAD_STYLE)
            tip = (f"Vertex count mismatch: the target (rest) mesh has "
                   f"{target_n} vertices, the source (abc) mesh has "
                   f"{source_n}.\n"
                   f"DemBones matches the cache to the rest mesh vertex by "
                   f"vertex, so the two must be the same topology - the solve "
                   f"is blocked until they are.\n"
                   f"Usual causes: the rest mesh comes from a different "
                   f"asset/version than the cache, or it is a DemBones result "
                   f"mesh whose geometry was rebuilt.\n"
                   f"Fix: let 'create rest on pick' build the rest mesh from "
                   f"the source, or pick a rest mesh with the cache's "
                   f"topology.")
        self.target_field.setToolTip(tip)
        self.vtx_label.setToolTip(tip)

    def _refresh_rig_status(self) -> None:
        mesh = self.target_field.text()
        if not self.use_rig_chk.isChecked() or not mesh:
            self.rig_status.setText("")
            return
        skin = dem_cmds.find_skin_cluster(mesh)
        if skin:
            n = len(dem_cmds.skin_influences(skin))
            self.rig_status.setText(f"skinCluster '{skin}' ({n} joints)")
            self.rig_status.setStyleSheet("color: #6cc06c;")
        else:
            joints = cmds.ls(selection=True, type="joint") or []
            if joints and not self.anim_only_chk.isChecked():
                self.rig_status.setText(f"{len(joints)} selected joints (no skin)")
                self.rig_status.setStyleSheet("color: #c0b06c;")
            elif joints:
                # Anim-only freezes weights, so bare joints are not enough.
                self.rig_status.setText(
                    f"{len(joints)} selected joints but no skin - anim only "
                    f"needs weights")
                self.rig_status.setStyleSheet("color: #c06c6c;")
            else:
                self.rig_status.setText("no skinCluster found")
                self.rig_status.setStyleSheet("color: #c06c6c;")