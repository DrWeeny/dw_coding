"""
wgt_transfer.py - hand a solved generation back to the rig (Tools menu).

The two halves of the return trip, in one panel because they are one workflow
step and share their inputs:

    Skin        :func:`dem_cmds.copy_skin_cluster` - bind the target mesh to
                the SAME joints as a skinned source, with the same weights.
    Animation   :func:`dem_cmds.transfer_solve_animation` - push the solved
                joint animation onto the rig's controls, or onto the joints
                themselves for a skeleton with no control rig over it.

The dialog is non-modal so the artist can keep selecting in Maya while it is
open; every field is filled from the current selection via its Pick button.
Each half states up front what it is about to do - which copy will happen
(exact index-to-index when the vertex counts match, approximate
``copySkinWeights`` otherwise), and how many joints resolved to a target.

Classes
-------
    TransferDialog

Functions
---------
    launch(parent=None)

Author:
    DrWeeny
"""

from __future__ import annotations

from typing import List, Optional

from maya import cmds

from dw_maya.DemBones.compat import QtWidgets
from dw_maya.DemBones import dem_cmds
from dw_logger import get_logger

logger = get_logger()

_OK_COLOR = "color: #6cc06c;"
_WARN_COLOR = "color: #d89b3a;"
_BAD_COLOR = "color: #c06c6c;"


class TransferDialog(QtWidgets.QDialog):
    """Copy a skinCluster mesh to mesh, and hand the solved animation back."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Transfer to Rig - skin and animation")
        self.setObjectName("DemBonesTransferDialog")
        self.setMinimumWidth(480)
        self._build_ui()
        self._connect()
        self._refresh_status()

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        skin_box = QtWidgets.QGroupBox("Skin")
        skin_layout = QtWidgets.QVBoxLayout(skin_box)

        form = QtWidgets.QFormLayout()
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(4)

        self.source_field = QtWidgets.QLineEdit()
        self.source_field.setReadOnly(True)
        self.source_field.setToolTip(
            "The skinned mesh to read from - typically an imported DemBones "
            "generation.")
        self.source_pick_btn = QtWidgets.QPushButton("Pick")
        form.addRow("Source (skinned)",
                    self._row(self.source_field, self.source_pick_btn))

        self.target_field = QtWidgets.QLineEdit()
        self.target_field.setReadOnly(True)
        self.target_field.setToolTip(
            "The mesh to bind. It ends up driven by the source's own joints, "
            "not by copies of them.")
        self.target_pick_btn = QtWidgets.QPushButton("Pick")
        form.addRow("Target",
                    self._row(self.target_field, self.target_pick_btn))

        # The bind-space offset is derived from the target itself, so this is
        # an override rather than a step - hidden until asked for.
        _OVERRIDE_TIP = (
            "The bind-space offset is normally worked out from the target "
            "itself: its undeformed (Orig) shape against the shape the rig "
            "draws, which share topology, so the fit is exact. Measured "
            "0.0003 units from a hand-placed mesh on a production asset.\n\n"
            "Tick this only when that cannot work:\n"
            "- the rest pose is NOT a rigid placement (the rig genuinely "
            "deforms the mesh at rest), which the solver detects and refuses "
            "rather than approximating;\n"
            "- the target has no undeformed shape to measure - never bound, "
            "or its history was deleted;\n"
            "- you want the offset taken from a specific mesh you placed "
            "yourself, rather than from the asset's current state.\n\n"
            "The override is a copy of the SOURCE mesh moved onto the "
            "target's bind pose, and must share topology with the source.")

        self.bind_override_chk = QtWidgets.QCheckBox(
            "Static bind pose mesh override")
        self.bind_override_chk.setToolTip(_OVERRIDE_TIP)
        form.addRow("", self.bind_override_chk)

        self.bind_field = QtWidgets.QLineEdit()
        self.bind_field.setReadOnly(True)
        self.bind_field.setPlaceholderText("(override)")
        self.bind_field.setToolTip(_OVERRIDE_TIP)
        self.bind_pick_btn = QtWidgets.QPushButton("Pick")
        self.bind_clear_btn = QtWidgets.QPushButton("X")
        self.bind_clear_btn.setMaximumWidth(24)
        self.bind_row = self._row(self.bind_field, self.bind_pick_btn)
        self.bind_row.layout().addWidget(self.bind_clear_btn)
        self.bind_label = QtWidgets.QLabel("Bind pose mesh")
        self.bind_label.setToolTip(_OVERRIDE_TIP)
        form.addRow(self.bind_label, self.bind_row)
        self.bind_label.setVisible(False)
        self.bind_row.setVisible(False)

        bind_to_row = QtWidgets.QHBoxLayout()
        self.bind_source_radio = QtWidgets.QRadioButton("the source's joints")
        self.bind_source_radio.setToolTip(
            "Bind the target to the SOURCE's own joint nodes - both meshes end "
            "up on one skeleton.\n"
            "This is the INBOUND direction: seeding a rest mesh from an "
            "earlier generation so an 'Animation only' solve has weights to "
            "keep.\n"
            "Wrong for sending a solve back to a published asset: the asset "
            "would depend on a demNNN: namespace that gets deleted.")
        self.bind_own_radio = QtWidgets.QRadioButton("the target's own joints")
        self.bind_own_radio.setChecked(True)
        self.bind_own_radio.setToolTip(
            "Pair each source influence to the scene joint of the same leaf "
            "name and bind the target to THOSE, copying only the weights.\n"
            "This is the OUTBOUND direction: handing a solve back to the "
            "published asset, which has to stay driven by its own rig.")
        bind_to_row.addWidget(self.bind_source_radio)
        bind_to_row.addWidget(self.bind_own_radio)
        bind_to_row.addStretch(1)
        form.addRow("Bind target to", self._wrap(bind_to_row))

        self.assoc_combo = QtWidgets.QComboBox()
        self.assoc_combo.addItems(dem_cmds.SURFACE_ASSOCIATIONS)
        self.assoc_combo.setToolTip(
            "How vertices are paired when the topologies differ:\n"
            "- closestPoint: nearest point on the source surface. The default, "
            "and the right one after points were deleted or added.\n"
            "- closestComponent: stays within the matching shell - better on "
            "meshes with separate pieces that overlap.\n"
            "- rayCast: projects along the normal - for surfaces offset from "
            "each other.\n"
            "Unused when both meshes have the same vertex count: that copy is "
            "index to index and needs no pairing.")
        form.addRow("Association", self.assoc_combo)

        skin_layout.addLayout(form)

        self.replace_chk = QtWidgets.QCheckBox(
            "Replace an existing skinCluster on the target")
        self.replace_chk.setChecked(True)
        self.replace_chk.setToolTip(
            "On: delete the target's current skinCluster and bind a fresh one. "
            "Keep it on for the return leg.\n"
            "Off: the target keeps its original influences AND gains the "
            "solved ones, while only the solved columns are written - so the "
            "old weights survive underneath and no longer sum to 1.")
        skin_layout.addWidget(self.replace_chk)

        self.bind_pose_chk = QtWidgets.QCheckBox("Copy the source bind pose")
        self.bind_pose_chk.setChecked(True)
        self.bind_pose_chk.setToolTip(
            "Copy the source's bindPreMatrix values instead of binding at the "
            "joints' current position.\n"
            "Keep this on when the joints are animated (a solved generation "
            "always is) - otherwise the current frame becomes the bind pose "
            "and the mesh jumps.")
        skin_layout.addWidget(self.bind_pose_chk)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        skin_layout.addWidget(self.status_label)

        skin_btn_row = QtWidgets.QHBoxLayout()
        self.copy_btn = QtWidgets.QPushButton("Copy Skin")
        skin_btn_row.addStretch(1)
        skin_btn_row.addWidget(self.copy_btn)
        skin_layout.addLayout(skin_btn_row)
        layout.addWidget(skin_box)

        layout.addWidget(self._build_animation_box())

        btn_row = QtWidgets.QHBoxLayout()
        self.close_btn = QtWidgets.QPushButton("Close")
        btn_row.addStretch(1)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

    def _build_animation_box(self) -> QtWidgets.QGroupBox:
        """The animation half: solved joints -> rig controls, or -> joints."""
        box = QtWidgets.QGroupBox("Animation")
        box.setToolTip(
            "Hand the solved joint animation back to the rig it came from. "
            "The joints are read from the source mesh's skinCluster.")
        layout = QtWidgets.QVBoxLayout(box)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel("Transfer to"))
        self.to_controls_radio = QtWidgets.QRadioButton("rig controls")
        self.to_controls_radio.setChecked(True)
        self.to_controls_radio.setToolTip(
            "Whatever constrains each joint - found through the constraint's "
            "target list, not by name.\n"
            "Constrain-bake-release with maintainOffset at the rest frame: a "
            "control sits somewhere else, oriented differently, under a "
            "different parent, so its curves are not the joint's curves.\n"
            "Locked channels are skipped and reported.")
        self.to_joints_radio = QtWidgets.QRadioButton("joints")
        self.to_joints_radio.setToolTip(
            "The scene joints themselves, matched by leaf name.\n"
            "A direct anim-curve copy - the generation is an import of the "
            "same skeleton, so local values transfer exactly, with no baking "
            "and no sampling error.\n"
            "Use it for a plain skeleton with no control rig. If the joints "
            "are constrained, keys set on them will not win - target the "
            "controls instead.")
        mode_row.addWidget(self.to_controls_radio)
        mode_row.addWidget(self.to_joints_radio)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        remap_row = QtWidgets.QHBoxLayout()
        remap_row.addWidget(QtWidgets.QLabel("Control name"))
        self.remap_find = QtWidgets.QLineEdit()
        self.remap_find.setPlaceholderText("find (optional)")
        self.remap_replace = QtWidgets.QLineEdit()
        self.remap_replace.setPlaceholderText("replace")
        remap_tip = (
            "Optional. Derive each control's name from its joint by one "
            "find/replace over the whole name, namespace included:\n"
            "    _SKL_ACC_X_:BB_   ->   _RIG_ACC_X_:MANIPFK_\n\n"
            "Leave empty to find controls through their CONSTRAINTS, which is "
            "the default and the more reliable route - on a validated rig the "
            "drivers were MANIPFK_* where the naming convention said RESETFK_*, "
            "and the root's was MANIP_M_0_Root. Fill these in for a rig that "
            "drives its joints by direct connection, with no constraint to "
            "follow.\n"
            "When given, the remap is tried first and the constraint lookup "
            "still catches whatever it misses.")
        for widget in (self.remap_find, self.remap_replace):
            widget.setToolTip(remap_tip)
        remap_row.addWidget(self.remap_find, 1)
        remap_row.addWidget(QtWidgets.QLabel("->"))
        remap_row.addWidget(self.remap_replace, 1)
        layout.addLayout(remap_row)

        range_row = QtWidgets.QHBoxLayout()
        range_row.addWidget(QtWidgets.QLabel("start"))
        self.start_spin = QtWidgets.QSpinBox()
        self.start_spin.setRange(-100000, 100000)
        range_row.addWidget(self.start_spin)
        range_row.addWidget(QtWidgets.QLabel("end"))
        self.end_spin = QtWidgets.QSpinBox()
        self.end_spin.setRange(-100000, 100000)
        range_row.addWidget(self.end_spin)
        self.range_btn = QtWidgets.QPushButton("from timeline")
        self.range_btn.setToolTip(
            "Fill from the playback range. Careful: that is often longer than "
            "the range you solved, and the extra frames would be baked with "
            "the rig sitting at its last solved pose.")
        range_row.addWidget(self.range_btn)
        range_row.addStretch(1)
        layout.addLayout(range_row)

        self.anim_status = QtWidgets.QLabel("")
        self.anim_status.setWordWrap(True)
        layout.addWidget(self.anim_status)

        anim_btn_row = QtWidgets.QHBoxLayout()
        self.resolve_btn = QtWidgets.QPushButton("Resolve (dry run)")
        self.resolve_btn.setToolTip(
            "Report how many solved joints found a target, and which did not, "
            "without touching anything.")
        self.transfer_anim_btn = QtWidgets.QPushButton("Transfer Animation")
        anim_btn_row.addStretch(1)
        anim_btn_row.addWidget(self.resolve_btn)
        anim_btn_row.addWidget(self.transfer_anim_btn)
        layout.addLayout(anim_btn_row)

        start, end = dem_cmds.timeline_range()
        self.start_spin.setValue(start)
        self.end_spin.setValue(end)
        return box

    @staticmethod
    def _wrap(layout) -> QtWidgets.QWidget:
        """Put a bare layout into a widget so a QFormLayout can take it."""
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        widget = QtWidgets.QWidget()
        widget.setLayout(layout)
        return widget

    @staticmethod
    def _row(field, button) -> QtWidgets.QWidget:
        """Wrap a [field][button] pair into one form-row widget."""
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(field, 1)
        row.addWidget(button)
        widget = QtWidgets.QWidget()
        widget.setLayout(row)
        return widget

    def _connect(self) -> None:
        self.source_pick_btn.clicked.connect(self._on_pick_source)
        self.target_pick_btn.clicked.connect(self._on_pick_target)
        self.bind_pick_btn.clicked.connect(self._on_pick_bind)
        self.bind_clear_btn.clicked.connect(self._on_clear_bind)
        self.bind_override_chk.toggled.connect(self._on_bind_override)
        self.copy_btn.clicked.connect(self._on_copy)
        self.close_btn.clicked.connect(self.close)
        self.bind_own_radio.toggled.connect(self._on_bind_mode)
        self._on_bind_mode(self.bind_own_radio.isChecked())
        self.range_btn.clicked.connect(self._on_range_from_timeline)
        self.resolve_btn.clicked.connect(self._on_resolve_anim)
        self.transfer_anim_btn.clicked.connect(self._on_transfer_anim)

    # -- Slots ------------------------------------------------------------

    def _on_pick_source(self) -> None:
        node = self._selected_mesh()
        if node:
            self.source_field.setText(node)
            self._refresh_status()

    def _on_pick_target(self) -> None:
        node = self._selected_mesh()
        if node:
            self.target_field.setText(node)
            self._refresh_status()

    def _on_pick_bind(self) -> None:
        node = self._selected_mesh()
        if node:
            self.bind_field.setText(node)
            self._refresh_status()

    def _on_clear_bind(self) -> None:
        self.bind_field.clear()
        self._refresh_status()

    def _on_bind_override(self, on: bool) -> None:
        """Reveal the override picker, and forget it again when switched off.

        Clearing on the way out matters: a stale path left in a hidden field
        would keep overriding the derived offset with no visible cause.
        """
        self.bind_label.setVisible(on)
        self.bind_row.setVisible(on)
        if not on:
            self.bind_field.clear()
        self._refresh_status()

    def _on_copy(self) -> None:
        source = self.source_field.text()
        target = self.target_field.text()
        if not source or not target:
            QtWidgets.QMessageBox.information(
                self, "Copy Skin", "Pick a source and a target mesh first.")
            return
        if source == target:
            QtWidgets.QMessageBox.information(
                self, "Copy Skin", "Source and target are the same mesh.")
            return

        if self.bind_own_radio.isChecked():
            skin = dem_cmds.copy_skin_to_own_joints(
                source,
                target,
                bind_pose_mesh=self.bind_field.text() or None,
                replace=self.replace_chk.isChecked(),
                surface_association=self.assoc_combo.currentText())
        else:
            skin = dem_cmds.copy_skin_cluster(
                source,
                target,
                replace=self.replace_chk.isChecked(),
                copy_bind_pose=self.bind_pose_chk.isChecked(),
                surface_association=self.assoc_combo.currentText(),
                bind_pose_mesh=self.bind_field.text() or None)

        if not skin:
            QtWidgets.QMessageBox.warning(
                self, "Copy Skin",
                "The copy failed - see the script editor for the reason.")
            return

        self._refresh_status()
        self.status_label.setText(f"Copied into '{skin}'.")
        self.status_label.setStyleSheet(_OK_COLOR)

    def _on_bind_mode(self, to_own_joints: bool) -> None:
        """Grey out what the chosen direction does not read.

        The outbound path takes its bind from the solve and pairs vertices by
        name, so neither the bind-pose checkbox nor the association combo is
        consulted. Leaving them live implies a control the artist does not
        have - and a setting that silently does nothing is what turns a wrong
        result into an unexplainable one.
        """
        self.bind_pose_chk.setEnabled(not to_own_joints)
        self.assoc_combo.setEnabled(not to_own_joints)
        if to_own_joints:
            self.bind_pose_chk.setToolTip(
                "Not used when binding to the target's own joints: the bind "
                "always comes from the solve, which is the only source that "
                "covers every influence.")
            self.assoc_combo.setToolTip(
                "Not used when binding to the target's own joints: vertices "
                "are matched one to one and influences by name, so there is "
                "no association to choose. Only the fallback path uses it.")
            self.replace_chk.setChecked(True)
        else:
            self.bind_pose_chk.setToolTip(
                "Copy the source's bindPreMatrix values instead of binding at "
                "the joints' current position.")
            self.assoc_combo.setToolTip(
                "How vertices are paired when the topologies differ.")

    # -- Animation slots --------------------------------------------------

    def _on_range_from_timeline(self) -> None:
        start, end = dem_cmds.timeline_range()
        self.start_spin.setValue(start)
        self.end_spin.setValue(end)

    def _solved_joints(self) -> List[str]:
        """The solved joints, read from the source mesh's skinCluster."""
        source = self.source_field.text()
        if not source:
            QtWidgets.QMessageBox.information(
                self, "Transfer", "Pick the source (solved) mesh first.")
            return []
        skin = dem_cmds.find_skin_cluster(source)
        if not skin:
            QtWidgets.QMessageBox.information(
                self, "Transfer",
                "The source mesh has no skinCluster, so there are no solved "
                "joints to read.")
            return []
        return dem_cmds.skin_influences(skin)

    def _run_anim_transfer(self, dry_run: bool) -> None:
        joints = self._solved_joints()
        if not joints:
            return
        to_controls = self.to_controls_radio.isChecked()
        find = self.remap_find.text().strip()
        mapping = dem_cmds.transfer_solve_animation(
            joints,
            start=self.start_spin.value(),
            end=self.end_spin.value(),
            to_controls=to_controls,
            name_remap=(find, self.remap_replace.text().strip())
            if find else None,
            dry_run=dry_run)

        target = "control(s)" if to_controls else "joint(s)"
        missed = len(joints) - len(mapping)
        verb = "would receive" if dry_run else "received"
        text = f"{len(mapping)} of {len(joints)} solved joints: {target} {verb} the animation."
        if missed:
            text += (f" {missed} unresolved - see the script editor for which.")
            self.anim_status.setStyleSheet(_WARN_COLOR)
        else:
            self.anim_status.setStyleSheet(_OK_COLOR if mapping else _BAD_COLOR)
        self.anim_status.setText(text)

    def _on_resolve_anim(self) -> None:
        self._run_anim_transfer(dry_run=True)

    def _on_transfer_anim(self) -> None:
        self._run_anim_transfer(dry_run=False)

    # -- Helpers ----------------------------------------------------------

    @staticmethod
    def _selected_mesh() -> Optional[str]:
        """First selected node, or None (with a message) when nothing is."""
        sel = cmds.ls(selection=True, long=True) or []
        if not sel:
            QtWidgets.QMessageBox.information(
                None, "Copy Skin", "Select a mesh first.")
            return None
        return sel[0]

    def _refresh_status(self) -> None:
        """Describe what the copy will do with the two meshes as picked."""
        source = self.source_field.text()
        target = self.target_field.text()
        if not source or not target:
            self.status_label.setText("Pick a source and a target mesh.")
            self.status_label.setStyleSheet("")
            return

        src_skin = dem_cmds.find_skin_cluster(source)
        if not src_skin:
            self.status_label.setText(
                "The source mesh has no skinCluster - nothing to copy.")
            self.status_label.setStyleSheet(_BAD_COLOR)
            return

        n_inf = len(dem_cmds.skin_influences(src_skin))
        src_n = dem_cmds.mesh_vertex_count(source) or 0
        tgt_n = dem_cmds.mesh_vertex_count(target) or 0
        head = f"'{src_skin}', {n_inf} influences. "

        bind_mesh = self.bind_field.text()
        if bind_mesh:
            bind_n = dem_cmds.mesh_vertex_count(bind_mesh) or 0
            if bind_n != src_n:
                self.status_label.setText(
                    head + f"The bind pose mesh has {bind_n} vertices against "
                           f"the source's {src_n}. It has to be a moved copy "
                           f"of the source to solve the transform between "
                           f"them.")
                self.status_label.setStyleSheet(_BAD_COLOR)
                return
            self.status_label.setText(
                head + f"Binding through '{bind_mesh.split('|')[-1]}': the "
                       f"rigid offset to the target's bind pose is folded into "
                       f"the bind matrices. Vertex counts {src_n} vs {tgt_n}.")
            self.status_label.setStyleSheet(_OK_COLOR)
            return

        # World space first: it is the failure that looks like a tool bug.
        same_space, distance = dem_cmds.meshes_share_space(source, target)
        if not same_space:
            self.status_label.setText(
                head + f"The geometry a bind would consume is {distance:.2f} "
                       f"units apart between the two (measured on the "
                       f"undeformed shapes, which is what a skinCluster reads "
                       f"- not what the viewport shows). The target would be "
                       f"bound to the source's joints, which stay put, so it "
                       f"will snap over to them. Bring the two together before "
                       f"copying.")
            self.status_label.setStyleSheet(_BAD_COLOR)
            return

        if src_n and src_n == tgt_n:
            self.status_label.setText(
                head + f"Both meshes have {src_n} vertices - exact copy, index "
                       f"to index.")
            self.status_label.setStyleSheet(_OK_COLOR)
        else:
            self.status_label.setText(
                head + f"Vertex counts differ ({src_n} vs {tgt_n}) - "
                       f"{self.assoc_combo.currentText()} copy, so the weights "
                       f"are approximate and worth a look before solving.")
            self.status_label.setStyleSheet(_WARN_COLOR)


def launch(parent=None) -> TransferDialog:
    """Show the transfer dialog (non-modal) and return it."""
    dialog = TransferDialog(parent=parent)
    dialog.show()
    return dialog