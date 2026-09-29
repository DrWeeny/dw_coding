"""
wgt_skin_panel.py - DynForge "Skinning" tab.

Per the selected guide:
- register its skinCluster (from the selected mesh)
- reach: radius = distance from the _PIN to the nearest skin joint, times a
  per-guide scale slider; it sizes the attachment search and the chain's tube
- Analyze: rank the skin joints around the _PIN (what the chain hangs from);
  selected rows = donor bones, double-click = inspect its paint. When nothing
  is picked yet the top one is taken as donor + parent bone.
- sharing: which other guides of the same skinCluster take from the same donor
- split preview: vertex-colour copy of the meshes, one colour per chain, mixed
  hues where chains compete, grey for what the donors keep
- optional clip gizmo, parent bone, cascade power, backup / restore

Weights are only written by "Install guides" (main window), per skinCluster.
"""

from __future__ import annotations

from dw_maya.DynForge.forge_cmds.compat import QtWidgets, Qt
from dw_maya.DynForge.forge_cmds import skin_ops
from dw_maya.DynForge.wgt_base import DynForgeWidgetBase
from dw_logger import get_logger

logger = get_logger()


_SHAPES = ("Box", "Sphere", "Capsule")
_INFL_ROLE = Qt.UserRole + 1
_SCALE_STEPS = 100   # slider ticks per 1.0 of radius scale


def _short(name: str) -> str:
    return name.split("|")[-1]


class SkinPanel(DynForgeWidgetBase):
    """Skinning setup for the selected guide (registration, reach, donors, preview)."""

    def __init__(self,
                 hub,
                 parent=None,) -> None:
        super().__init__(hub, parent)
        self._guide = None
        self._peers_provider = None
        self._build_ui()

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QtWidgets.QStackedWidget()
        outer.addWidget(self._stack)

        placeholder = QtWidgets.QLabel("Select a guide to set up its skinning.")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: #888;")
        self._stack.addWidget(placeholder)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        # Wrap long (namespaced) names instead of scrolling sideways.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self._build_content())
        self._stack.addWidget(scroll)

    def _build_content(self) -> QtWidgets.QWidget:
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)

        # Register the skinCluster
        reg_box = QtWidgets.QGroupBox("Target skinCluster")
        reg_layout = QtWidgets.QVBoxLayout(reg_box)
        self._register_btn = QtWidgets.QPushButton("Register selected mesh")
        reg_layout.addWidget(self._register_btn)
        self._skin_label = QtWidgets.QLabel("skinCluster: -")
        self._skin_label.setWordWrap(True)
        reg_layout.addWidget(self._skin_label)
        layout.addWidget(reg_box)

        # Reach
        reach_box = QtWidgets.QGroupBox("Reach")
        reach_layout = QtWidgets.QVBoxLayout(reach_box)
        self._reach_label = QtWidgets.QLabel("-")
        self._reach_label.setWordWrap(True)
        reach_layout.addWidget(self._reach_label)
        scale_row = QtWidgets.QHBoxLayout()
        scale_row.addWidget(QtWidgets.QLabel("Scale"))
        self._scale_slider = QtWidgets.QSlider(Qt.Horizontal)
        self._scale_slider.setRange(int(0.1 * _SCALE_STEPS), int(4.0 * _SCALE_STEPS))
        self._scale_slider.setValue(_SCALE_STEPS)
        scale_row.addWidget(self._scale_slider, stretch=1)
        self._scale_spin = QtWidgets.QDoubleSpinBox()
        self._scale_spin.setRange(0.1, 4.0)
        self._scale_spin.setSingleStep(0.05)
        self._scale_spin.setValue(1.0)
        scale_row.addWidget(self._scale_spin)
        reach_layout.addLayout(scale_row)
        layout.addWidget(reach_box)

        # Attachment / donors
        part_box = QtWidgets.QGroupBox("Attachment (skin joints around the _PIN)")
        part_layout = QtWidgets.QVBoxLayout(part_box)
        self._analyze_btn = QtWidgets.QPushButton("Analyze")
        part_layout.addWidget(self._analyze_btn)
        self._tree = QtWidgets.QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Influence", "%"])
        self._tree.setRootIsDecorated(False)
        self._tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._tree.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        header = self._tree.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        part_layout.addWidget(self._tree, stretch=1)
        hint = QtWidgets.QLabel("Selected rows = donor bones; double-click to inspect the paint.")
        hint.setStyleSheet("color: #888;")
        part_layout.addWidget(hint)
        self._donors_label = QtWidgets.QLabel("Donors: -")
        self._donors_label.setWordWrap(True)
        part_layout.addWidget(self._donors_label)
        self._sharing_label = QtWidgets.QLabel("")
        self._sharing_label.setWordWrap(True)
        part_layout.addWidget(self._sharing_label)
        layout.addWidget(part_box, stretch=1)

        # Split preview
        prev_box = QtWidgets.QGroupBox("Split preview (all chains of this skinCluster)")
        prev_layout = QtWidgets.QVBoxLayout(prev_box)
        prev_row = QtWidgets.QHBoxLayout()
        self._preview_btn = QtWidgets.QPushButton("Preview split")
        self._preview_btn.setToolTip(
            "Colour a copy of the meshes: one colour per chain, mixed hues where chains "
            "share a donor, grey for what the donors keep. The originals are hidden.")
        self._clear_btn = QtWidgets.QPushButton("Clear preview")
        prev_row.addWidget(self._preview_btn)
        prev_row.addWidget(self._clear_btn)
        prev_row.addStretch(1)
        prev_layout.addLayout(prev_row)
        self._preview_label = QtWidgets.QLabel("")
        self._preview_label.setWordWrap(True)
        self._preview_label.setTextFormat(Qt.RichText)
        prev_layout.addWidget(self._preview_label)
        layout.addWidget(prev_box)

        # Transfer: parent bone + power + optional clip gizmo
        bottom_box = QtWidgets.QGroupBox("Transfer")
        form = QtWidgets.QFormLayout(bottom_box)
        parent_row = QtWidgets.QHBoxLayout()
        self._parent_btn = QtWidgets.QPushButton("Pick parent bone (selected)")
        parent_row.addWidget(self._parent_btn)
        self._parent_label = QtWidgets.QLabel("-")
        parent_row.addWidget(self._parent_label, stretch=1)
        form.addRow("Parent", parent_row)
        self._power = QtWidgets.QDoubleSpinBox()
        self._power.setRange(0.1, 10.0)
        self._power.setSingleStep(0.1)
        self._power.setValue(1.0)
        self._power.setToolTip("Cascade width down the chain joints (1 ~ one joint spacing).")
        form.addRow("Power", self._power)
        giz_row = QtWidgets.QHBoxLayout()
        self._shape_combo = QtWidgets.QComboBox()
        self._shape_combo.addItems(_SHAPES)
        giz_row.addWidget(self._shape_combo)
        self._gizmo_btn = QtWidgets.QPushButton("Create / reset")
        self._gizmo_btn.setToolTip(
            "Create the clip volume fitted around the whole chain (root -> tip, reach radius): it starts "
            "clipping nothing - shrink / move it to cut something out (a belt, the body...). Outside it "
            "the chain claims nothing, so it must keep containing the chain's curve.")
        self._gizmo_del_btn = QtWidgets.QPushButton("Remove")
        giz_row.addWidget(self._gizmo_btn)
        giz_row.addWidget(self._gizmo_del_btn)
        giz_row.addStretch(1)
        form.addRow("Clip gizmo", giz_row)
        self._gizmo_label = QtWidgets.QLabel("")
        self._gizmo_label.setStyleSheet("color: #888;")
        form.addRow("", self._gizmo_label)
        layout.addWidget(bottom_box)

        # Backup / restore
        backup_box = QtWidgets.QGroupBox("Backup (the skin before any install)")
        backup_layout = QtWidgets.QVBoxLayout(backup_box)
        self._backup_label = QtWidgets.QLabel("No backup")
        backup_layout.addWidget(self._backup_label)
        backup_row = QtWidgets.QHBoxLayout()
        self._backup_btn  = QtWidgets.QPushButton("Backup original skin")
        self._restore_btn = QtWidgets.QPushButton("Restore original skin")
        backup_row.addWidget(self._backup_btn)
        backup_row.addWidget(self._restore_btn)
        backup_layout.addLayout(backup_row)
        layout.addWidget(backup_box)

        # Connections
        self._register_btn.clicked.connect(self._on_register)
        self._scale_slider.valueChanged.connect(self._on_slider_changed)
        self._scale_spin.valueChanged.connect(self._on_scale_spin_changed)
        self._analyze_btn.clicked.connect(self._on_analyze)
        self._tree.itemDoubleClicked.connect(self._on_row_double_clicked)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._preview_btn.clicked.connect(self._on_preview)
        self._clear_btn.clicked.connect(self._on_clear_preview)
        self._parent_btn.clicked.connect(self._on_pick_parent)
        self._power.valueChanged.connect(self._on_power_changed)
        self._shape_combo.currentIndexChanged.connect(self._on_shape_changed)
        self._gizmo_btn.clicked.connect(self._on_create_gizmo)
        self._gizmo_del_btn.clicked.connect(self._on_remove_gizmo)
        self._backup_btn.clicked.connect(self._on_backup)
        self._restore_btn.clicked.connect(self._on_restore)

        return content

    # -- Public -----------------------------------------------------------

    def set_peers_provider(self,
                           provider,) -> None:
        """`provider(skin) -> [guides]`: every listed guide registered on `skin`."""
        self._peers_provider = provider

    def load_guide(self,
                   guide,) -> None:
        """Show the panel for `guide`, or the placeholder when None."""
        self._guide = None   # mute handlers while populating
        self._tree.clear()
        self._preview_label.setText("")
        if guide is None:
            self._stack.setCurrentIndex(0)
            return

        idx = self._shape_combo.findText(getattr(guide, "gizmo_shape", "box").capitalize())
        if idx >= 0:
            self._shape_combo.setCurrentIndex(idx)
        self._power.setValue(getattr(guide, "power", 1.0))
        scale = getattr(guide, "radius_scale", 1.0)
        self._scale_spin.setValue(scale)
        self._scale_slider.setValue(int(round(scale * _SCALE_STEPS)))

        self._guide = guide
        self._refresh_labels()
        self._stack.setCurrentIndex(1)

    def reload_if_current(self,
                          guide,) -> None:
        if guide is self._guide:
            self.load_guide(guide)

    def refresh_if_current(self,
                           guide,) -> None:
        """Update the labels only (keeps the Analyze table / preview legend)."""
        if guide is self._guide:
            self._refresh_labels()

    # -- Labels -----------------------------------------------------------

    def _refresh_labels(self) -> None:
        guide = self._guide
        if guide is None:
            return
        skin = guide.skin_cluster
        meshes = guide.skin_meshes or []
        self._skin_label.setText(f"skinCluster: {skin}  ({len(meshes)} mesh)" if skin else "skinCluster: -")
        parent = guide.parent_bone
        self._parent_label.setText(_short(parent) if parent else "-")
        donors = guide.source_influences or []
        self._donors_label.setText("Donors: " + (", ".join(_short(d) for d in donors) if donors else "-"))
        self._refresh_gizmo_label()
        self._refresh_reach()
        self._refresh_sharing()
        self._refresh_backup_label()

    def _refresh_gizmo_label(self) -> None:
        """Clip state, warning in red when the gizmo cuts the chain's own curve."""
        guide = self._guide
        if not guide.gizmo:
            self._gizmo_label.setStyleSheet("color: #888;")
            self._gizmo_label.setText("no clip - plain tube around the chain")
            return
        coverage = None
        try:
            coverage = guide.gizmo_coverage()
        except Exception as e:
            logger.warning(f"DynForge: gizmo coverage failed: {e}")
        if coverage is not None and coverage < 0.99:
            self._gizmo_label.setStyleSheet("color: #e06c5a;")
            self._gizmo_label.setText(
                f"{_short(guide.gizmo)} excludes {100 * (1 - coverage):.0f}% of the chain's curve - "
                "those verts go to the neighbour chains / donor. Recreate it (fitted) or enlarge it.")
        else:
            self._gizmo_label.setStyleSheet("color: #888;")
            self._gizmo_label.setText(f"clipping with {_short(guide.gizmo)} (contains the whole chain)")

    def _refresh_reach(self) -> None:
        try:
            bone, base, radius = self._guide.reach()
        except Exception as e:
            self._reach_label.setText(f"Reach unavailable: {e}")
            return
        if bone is None:
            self._reach_label.setText("Build the chain and register a skin to size the reach.")
            return
        self._reach_label.setText(
            f"_PIN -> nearest skin joint {_short(bone).split(':')[-1]}: {base:.2f}\nradius {radius:.2f}")
        self._reach_label.setToolTip(bone)

    def _refresh_sharing(self) -> None:
        guide = self._guide
        donors = {_short(d) for d in guide.source_influences or []}
        if not (guide.skin_cluster and donors and self._peers_provider):
            self._sharing_label.setText("")
            return
        shared = []
        for peer in self._peers_provider(guide.skin_cluster):
            if peer is guide:
                continue
            common = donors & {_short(d) for d in getattr(peer, "source_influences", []) or []}
            if common:
                shared.append(f"{peer.name} ({', '.join(sorted(common))})")
        self._sharing_label.setText(
            "Shares donors with: " + "; ".join(shared) if shared else "No other chain takes from these donors.")

    def _refresh_backup_label(self) -> None:
        has = False
        try:
            has = self._guide.has_skin_backup()
        except Exception:
            has = False
        self._backup_label.setText("Backup stored - installs restore it first" if has else "No backup yet "
                                   "(taken automatically on the first install)")

    # -- Handlers ---------------------------------------------------------

    def _warn(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "DynForge", message)

    def _on_register(self) -> None:
        if self._guide is None:
            return
        try:
            self._guide.register_skin()
        except Exception as e:
            self._warn(f"Register failed:\n{e}")
            return
        self._refresh_labels()

    def _set_scale(self,
                   value: float,) -> None:
        if self._guide is None:
            return
        self._guide.radius_scale = value
        self._guide.store_recipe()
        self._refresh_reach()

    def _on_slider_changed(self,
                           ticks: int,) -> None:
        value = ticks / float(_SCALE_STEPS)
        self._scale_spin.blockSignals(True)
        self._scale_spin.setValue(value)
        self._scale_spin.blockSignals(False)
        self._set_scale(value)

    def _on_scale_spin_changed(self,
                               value: float,) -> None:
        self._scale_slider.blockSignals(True)
        self._scale_slider.setValue(int(round(value * _SCALE_STEPS)))
        self._scale_slider.blockSignals(False)
        self._set_scale(value)

    def _on_analyze(self) -> None:
        if self._guide is None:
            return
        try:
            ranked = self._guide.analyze()
        except Exception as e:
            self._warn(f"Analyze failed:\n{e}")
            return
        guide, self._guide = self._guide, None   # mute selection handler while filling
        self._tree.clear()
        donors = {_short(d) for d in guide.source_influences}
        for name, pct in ranked:
            item = QtWidgets.QTreeWidgetItem([_short(name), f"{pct:.1f}"])
            item.setData(0, _INFL_ROLE, name)
            self._tree.addTopLevelItem(item)
            item.setSelected(_short(name) in donors)
        self._guide = guide
        self._refresh_labels()
        if not ranked:
            self._warn("No skin weight found around the _PIN - raise the reach scale.")

    def _on_row_double_clicked(self,
                               item,
                               column: int,) -> None:
        if self._guide is None or item is None:
            return
        influence = item.data(0, _INFL_ROLE)
        if influence:
            self._guide.inspect_influence(influence)

    def _on_selection_changed(self) -> None:
        if self._guide is None:
            return
        names = [it.data(0, _INFL_ROLE) for it in self._tree.selectedItems()]
        self._guide.source_influences = [n for n in names if n]
        self._guide.store_recipe()
        donors = self._guide.source_influences
        self._donors_label.setText("Donors: " + (", ".join(_short(d) for d in donors) if donors else "-"))
        self._refresh_sharing()

    def _on_preview(self) -> None:
        if self._guide is None or not self._guide.skin_cluster:
            self._warn("Register a skinned mesh first.")
            return
        self._refresh_gizmo_label()   # the gizmo may have been moved in the viewport since
        peers = self._peers_provider(self._guide.skin_cluster) if self._peers_provider else [self._guide]
        ready = [g for g in peers if hasattr(g, "is_installable") and g.is_installable()]
        if not ready:
            self._warn("No chain of this skinCluster is ready: build it and pick donor bone(s).")
            return
        try:
            stats = skin_ops.preview_split(self._guide.skin_cluster, [g.skin_spec() for g in ready])
        except Exception as e:
            logger.error(f"DynForge: preview failed: {e}")
            self._warn(f"Preview failed:\n{e}")
            return
        rows = []
        for ci, entry in enumerate(stats):
            r, g, b = (int(c * 255) for c in skin_ops.PREVIEW_COLORS[ci % len(skin_ops.PREVIEW_COLORS)])
            rows.append(f"<span style='color: rgb({r},{g},{b});'>&#9632;</span> {entry['name']}: "
                        f"{entry['verts']} vert(s), {entry['contested']} contested")
        for guide in ready:
            coverage = guide.gizmo_coverage() if hasattr(guide, "gizmo_coverage") else None
            if coverage is not None and coverage < 0.99:
                rows.append(f"<span style='color: #e06c5a;'>{guide.name}: its clip gizmo excludes "
                            f"{100 * (1 - coverage):.0f}% of its own curve</span>")
        skipped = [g.name for g in peers if g not in ready]
        if skipped:
            rows.append(f"<span style='color: #888;'>not ready (no donor / not built): "
                        f"{', '.join(skipped)}</span>")
        self._preview_label.setText("<br>".join(rows))

    def _on_clear_preview(self) -> None:
        try:
            skin_ops.clear_preview()
        except Exception as e:
            self._warn(f"Clear preview failed:\n{e}")
        self._preview_label.setText("")

    def _on_pick_parent(self) -> None:
        if self._guide is None:
            return
        try:
            self._guide.set_parent_from_selection()
        except Exception as e:
            self._warn(f"Pick parent failed:\n{e}")
            return
        self._refresh_labels()

    def _on_power_changed(self, *args) -> None:
        if self._guide is not None:
            self._guide.power = self._power.value()
            self._guide.store_recipe()

    def _on_shape_changed(self, *args) -> None:
        if self._guide is not None:
            self._guide.gizmo_shape = self._shape_combo.currentText().lower()

    def _on_create_gizmo(self) -> None:
        if self._guide is None:
            return
        try:
            self._guide.make_gizmo(self._shape_combo.currentText().lower())
        except Exception as e:
            self._warn(f"Create gizmo failed:\n{e}")
        self._refresh_labels()

    def _on_remove_gizmo(self) -> None:
        if self._guide is None:
            return
        self._guide.delete_gizmo()
        self._refresh_labels()

    def _on_backup(self) -> None:
        if self._guide is None:
            return
        try:
            if self._guide.has_skin_backup():
                reply = QtWidgets.QMessageBox.question(
                    self, "DynForge",
                    "A backup already exists and every install restores it. Overwrite it "
                    "with the current skin? Only do this if the current skin has NO DynForge "
                    "chain installed (e.g. the base rig was updated).",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                if reply != QtWidgets.QMessageBox.Yes:
                    return
                self._guide.backup_skin(force=True)
            else:
                self._guide.backup_skin()
        except Exception as e:
            self._warn(f"Backup failed:\n{e}")
            return
        self._refresh_backup_label()

    def _on_restore(self) -> None:
        if self._guide is None:
            return
        try:
            self._guide.restore_skin()
        except Exception as e:
            self._warn(f"Restore failed:\n{e}")
