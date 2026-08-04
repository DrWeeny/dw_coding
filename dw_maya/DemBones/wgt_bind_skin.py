"""
wgt_bind_skin.py - bind the rest mesh so every joint takes part in the solve.

Front end for :func:`dem_cmds.bind_mesh_to_joints` and
:func:`dem_cmds.add_zero_weight_influences`, the two halves of preparing a rest
mesh for a use-rig solve:

    Bind (weighted)     the joints that should be SOLVED. Weights are the only
                        coupling between a joint and DemBones - a joint with no
                        weight anywhere is invisible to the solver and comes
                        back with no animation.
    Add at weight 0     the joints that must be in the file but must not
                        deform: the pipeline root, any intermediate joint
                        between it and the real influences.

The weighted bind forces ``removeUnusedInfluence`` off, which is why it keeps
joints Maya's default bind silently drops.

Classes
-------
    BindSkinDialog

Functions
---------
    launch(parent=None)

Author:
    DrWeeny
"""

from __future__ import annotations

from typing import List

from maya import cmds

from dw_maya.DemBones.compat import QtWidgets
from dw_maya.DemBones import dem_cmds
from dw_logger import get_logger

logger = get_logger()

_OK_COLOR = "color: #6cc06c;"
_WARN_COLOR = "color: #d89b3a;"
_BAD_COLOR = "color: #c06c6c;"


class BindSkinDialog(QtWidgets.QDialog):
    """Bind a rest mesh to its joints, and add non-deforming joints at 0."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bind Skin - prepare a rest mesh")
        self.setObjectName("DemBonesBindSkinDialog")
        self.setMinimumWidth(470)
        self._build_ui()
        self._connect()
        self._refresh_status()

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        mesh_row = QtWidgets.QHBoxLayout()
        mesh_row.addWidget(QtWidgets.QLabel("Mesh"))
        self.mesh_field = QtWidgets.QLineEdit()
        self.mesh_field.setReadOnly(True)
        self.mesh_field.setToolTip("The rest mesh the solve will bind.")
        self.mesh_pick_btn = QtWidgets.QPushButton("Pick")
        mesh_row.addWidget(self.mesh_field, 1)
        mesh_row.addWidget(self.mesh_pick_btn)
        layout.addLayout(mesh_row)

        # -- Weighted bind -------------------------------------------------
        bind_box = QtWidgets.QGroupBox("Bind selected joints (weighted)")
        bind_box.setToolTip(
            "Smooth-bind the mesh to the selected joints. These are the joints "
            "the solve will animate.")
        bind_layout = QtWidgets.QVBoxLayout(bind_box)

        note = QtWidgets.QLabel(
            "The joints to SOLVE. Weights are the only thing connecting a "
            "joint to DemBones - unweighted joints come back static.")
        note.setWordWrap(True)
        bind_layout.addWidget(note)

        opts = QtWidgets.QHBoxLayout()
        opts.addWidget(QtWidgets.QLabel("max influences"))
        self.max_inf_spin = QtWidgets.QSpinBox()
        self.max_inf_spin.setRange(1, 32)
        self.max_inf_spin.setValue(8)
        self.max_inf_spin.setToolTip(
            "Influences per vertex. Match it to the solve's nnz (8 by "
            "default), or the seed is narrower than the budget the solve "
            "will use.")
        opts.addWidget(self.max_inf_spin)
        opts.addSpacing(12)
        opts.addWidget(QtWidgets.QLabel("dropoff"))
        self.dropoff_spin = QtWidgets.QDoubleSpinBox()
        self.dropoff_spin.setRange(0.1, 100.0)
        self.dropoff_spin.setValue(4.0)
        self.dropoff_spin.setToolTip("Weight falloff by distance.")
        opts.addWidget(self.dropoff_spin)
        opts.addStretch(1)
        bind_layout.addLayout(opts)

        self.replace_chk = QtWidgets.QCheckBox(
            "Replace an existing skinCluster")
        self.replace_chk.setToolTip(
            "On: delete the current skinCluster and bind fresh, so every joint "
            "gets a distance-based seed.\n"
            "Off: keep it and add the selected joints to it - they arrive with "
            "no weight, so flood or paint them afterwards.")
        bind_layout.addWidget(self.replace_chk)

        self.bind_btn = QtWidgets.QPushButton("Bind selected joints")
        bind_layout.addWidget(self.bind_btn)
        layout.addWidget(bind_box)

        # -- Zero-weight influences ---------------------------------------
        zero_box = QtWidgets.QGroupBox("Add selected joints at weight 0")
        zero_box.setToolTip(
            "Add the selected joints as influences carrying no weight.")
        zero_layout = QtWidgets.QVBoxLayout(zero_box)

        zero_note = QtWidgets.QLabel(
            "The joints that must be in the FBX but must not deform - a "
            "pipeline root, the joints between it and the real influences. "
            "Makes the file's joint count match the influence count, which is "
            "what DemBones insists on.")
        zero_note.setWordWrap(True)
        zero_layout.addWidget(zero_note)

        zero_btn_row = QtWidgets.QHBoxLayout()
        self.zero_btn = QtWidgets.QPushButton("Add selected joints at 0")
        self.ancestors_btn = QtWidgets.QPushButton("Add missing ancestors")
        self.ancestors_btn.setToolTip(
            "Work out which joints the FBX export will drag in as ancestors of "
            "the current influences, and add those. Usually just the root.")
        zero_btn_row.addWidget(self.zero_btn)
        zero_btn_row.addWidget(self.ancestors_btn)
        zero_layout.addLayout(zero_btn_row)
        layout.addWidget(zero_box)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        close_row = QtWidgets.QHBoxLayout()
        close_row.addStretch(1)
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.close_btn = QtWidgets.QPushButton("Close")
        close_row.addWidget(self.refresh_btn)
        close_row.addWidget(self.close_btn)
        layout.addLayout(close_row)

    def _connect(self) -> None:
        self.mesh_pick_btn.clicked.connect(self._on_pick_mesh)
        self.bind_btn.clicked.connect(self._on_bind)
        self.zero_btn.clicked.connect(self._on_add_zero)
        self.ancestors_btn.clicked.connect(self._on_add_ancestors)
        self.refresh_btn.clicked.connect(self._refresh_status)
        self.close_btn.clicked.connect(self.close)

    # -- Slots ------------------------------------------------------------

    def _on_pick_mesh(self) -> None:
        sel = cmds.ls(selection=True, long=True) or []
        if not sel:
            QtWidgets.QMessageBox.information(
                self, "Bind Skin", "Select the rest mesh first.")
            return
        self.mesh_field.setText(sel[0])
        self._refresh_status()

    def _on_bind(self) -> None:
        mesh = self._mesh()
        joints = self._selected_joints()
        if not mesh or not joints:
            return
        skin = dem_cmds.bind_mesh_to_joints(
            mesh,
            joints,
            max_influences=self.max_inf_spin.value(),
            dropoff=self.dropoff_spin.value(),
            replace=self.replace_chk.isChecked())
        if not skin:
            QtWidgets.QMessageBox.warning(
                self, "Bind Skin",
                "The bind failed - see the script editor for the reason.")
        self._refresh_status()

    def _on_add_zero(self) -> None:
        mesh = self._mesh()
        joints = self._selected_joints()
        if not mesh or not joints:
            return
        dem_cmds.add_zero_weight_influences(mesh, joints)
        self._refresh_status()

    def _on_add_ancestors(self) -> None:
        mesh = self._mesh()
        if not mesh:
            return
        skin = dem_cmds.find_skin_cluster(mesh)
        if not skin:
            QtWidgets.QMessageBox.information(
                self, "Bind Skin", "Bind the mesh first.")
            return
        ancestors = dem_cmds.non_influence_ancestors(
            dem_cmds.skin_influences(skin))
        if not ancestors:
            self.status_label.setText(
                "No ancestor joints are missing - the export already matches.")
            self.status_label.setStyleSheet(_OK_COLOR)
            return
        dem_cmds.add_zero_weight_influences(mesh, ancestors)
        self._refresh_status()

    # -- Helpers ----------------------------------------------------------

    def _mesh(self) -> str:
        mesh = self.mesh_field.text()
        if not mesh:
            QtWidgets.QMessageBox.information(
                self, "Bind Skin", "Pick the rest mesh first.")
        return mesh

    def _selected_joints(self) -> List[str]:
        joints = cmds.ls(selection=True, type="joint", long=True) or []
        if not joints:
            QtWidgets.QMessageBox.information(
                self, "Bind Skin", "Select the joints in the viewport first.")
        return joints

    def _refresh_status(self) -> None:
        mesh = self.mesh_field.text()
        if not mesh:
            self.status_label.setText("Pick a rest mesh.")
            self.status_label.setStyleSheet("")
            return

        skin = dem_cmds.find_skin_cluster(mesh)
        if not skin:
            self.status_label.setText(
                f"'{mesh.split('|')[-1]}' has no skinCluster yet. Select the "
                f"joints to solve and bind them.")
            self.status_label.setStyleSheet(_WARN_COLOR)
            return

        influences = dem_cmds.skin_influences(skin)
        ancestors = dem_cmds.non_influence_ancestors(influences)
        text = f"'{skin}': {len(influences)} influences. "
        if ancestors:
            names = ", ".join(dem_cmds._leaf_name(j) for j in ancestors[:4])
            self.status_label.setText(
                text + f"{len(ancestors)} joint(s) will be dragged into the "
                       f"FBX as ancestors without being influences ({names}) - "
                       f"the solve will refuse the mismatch. Add them at "
                       f"weight 0.")
            self.status_label.setStyleSheet(_BAD_COLOR)
            return
        self.status_label.setText(
            text + "Every joint the export writes is an influence - the counts "
                   "match.")
        self.status_label.setStyleSheet(_OK_COLOR)


def launch(parent=None) -> BindSkinDialog:
    """Show the bind-skin dialog (non-modal) and return it."""
    dialog = BindSkinDialog(parent=parent)
    dialog.show()
    return dialog