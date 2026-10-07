"""
wgt_skin_panel.py - DynForge "Skinning" tab.

Per the selected guide:
- register its skinCluster (from the selected mesh)
- reach: radius = distance from the _PIN to the nearest skin joint, times a
  per-guide scale slider; it sizes the attachment search and the chain's tube
- Analyze: rank the skin joints under the whole chain (what it takes weight from, read on the vanilla skin);
  selected rows = donor bones, double-click = inspect its paint. When nothing
  is picked yet the top one is taken as donor + parent bone.
- sharing: which other guides of the same skinCluster take from the same donor
- split preview: vertex-colour copy of the meshes, one colour per chain, mixed
  hues where chains compete, grey for what the donors keep
- optional clip gizmo, parent bone, cascade power, the DynForge layer (remove its weights)

Weights are only written by "Install guides" (main window), per skinCluster.
"""

from __future__ import annotations

from dw_maya.DynForge.forge_cmds.compat import QtGui, QtWidgets, Qt
from dw_maya.DynForge.forge_cmds import skin_ops
from dw_maya.DynForge.wgt_base import DynForgeWidgetBase
from dw_logger import get_logger

logger = get_logger()


_SHAPES = ("Box", "Sphere", "Capsule")
_INFL_ROLE = Qt.UserRole + 1
_SCALE_STEPS = 100   # slider ticks per 1.0 of radius scale
_ORANGE = "#e8a33d"  # warning that is not an error (the vertex mask may be stale)
_ZERO_GREY = "#6f6f6f"  # an influence with no weight in reach (Analyze list)


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
        part_box = QtWidgets.QGroupBox("Attachment (skin joints under the chain)")
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
        size_row = QtWidgets.QHBoxLayout()
        self._gizmo_size = QtWidgets.QSpinBox()
        self._gizmo_size.setRange(10, 1000)
        self._gizmo_size.setSingleStep(10)
        self._gizmo_size.setSuffix(" %")
        self._gizmo_size.setKeyboardTracking(False)   # apply on Enter / arrows, not on every digit typed
        self._gizmo_size.setToolTip(
            "Grow / shrink the clip gizmo around its centre, in % of its fitted size. Scaling it in the "
            "viewport works too - this multiplies whatever scale it has, keeping its proportions.")
        size_row.addWidget(self._gizmo_size)
        size_row.addStretch(1)
        form.addRow("Gizmo size", size_row)
        self._gizmo_label = QtWidgets.QLabel("")
        self._gizmo_label.setStyleSheet("color: #888;")
        form.addRow("", self._gizmo_label)
        mask_row = QtWidgets.QHBoxLayout()
        self._mask_set_btn = QtWidgets.QPushButton("Set from selection")
        self._mask_set_btn.setToolTip(
            "Only the selected vertices (faces / edges are converted) can take weight from this chain - "
            "on top of the tube and the clip gizmo. Elsewhere the donor / neighbour chains keep it.")
        self._mask_add_btn = QtWidgets.QPushButton("Add")
        self._mask_add_btn.setToolTip("Add the selected vertices to the mask.")
        self._mask_clear_btn = QtWidgets.QPushButton("Clear")
        self._mask_select_btn = QtWidgets.QPushButton("Select")
        self._mask_select_btn.setToolTip("Select the mask's vertices in the viewport.")
        for button in (self._mask_set_btn, self._mask_add_btn, self._mask_clear_btn, self._mask_select_btn):
            mask_row.addWidget(button)
        mask_row.addStretch(1)
        form.addRow("Vertex mask", mask_row)
        mask_state = QtWidgets.QHBoxLayout()
        self._mask_warn = QtWidgets.QLabel()
        self._mask_warn.setPixmap(
            self.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxWarning).pixmap(16, 16))
        self._mask_warn.hide()
        self._mask_label = QtWidgets.QLabel("")
        self._mask_label.setStyleSheet("color: #888;")
        mask_state.addWidget(self._mask_warn)
        mask_state.addWidget(self._mask_label, stretch=1)
        form.addRow("", mask_state)
        layout.addWidget(bottom_box)

        # DynForge layer: what the installs moved on this skin
        layer_box = QtWidgets.QGroupBox("DynForge layer (what the installs moved on this skin)")
        layer_layout = QtWidgets.QVBoxLayout(layer_box)
        self._layer_label = QtWidgets.QLabel("")
        self._layer_label.setWordWrap(True)
        layer_layout.addWidget(self._layer_label)
        layer_row = QtWidgets.QHBoxLayout()
        self._remove_layer_btn = QtWidgets.QPushButton("Remove DynForge weights from this skin")
        self._remove_layer_btn.setToolTip(
            "Gives back exactly what the installs moved, to the bones they took it from - every other edit "
            "on the skin (new bones, repaints) stays. The chains stay in the rig at weight 0, locked.")
        layer_row.addWidget(self._remove_layer_btn)
        layer_row.addStretch(1)
        layer_layout.addLayout(layer_row)
        layout.addWidget(layer_box)

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
        self._gizmo_size.valueChanged.connect(self._on_gizmo_size)
        self._mask_set_btn.clicked.connect(self._on_mask_set)
        self._mask_add_btn.clicked.connect(self._on_mask_add)
        self._mask_clear_btn.clicked.connect(self._on_mask_clear)
        self._mask_select_btn.clicked.connect(self._on_mask_select)
        self._remove_layer_btn.clicked.connect(self._on_remove_layer)

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
        self._refresh_mask_label()
        self._refresh_reach()
        self._refresh_sharing()
        self._refresh_layer_label()

    def _refresh_mask_label(self) -> None:
        guide = self._guide
        count = guide.mask_count() if hasattr(guide, "mask_count") else 0
        self._mask_clear_btn.setEnabled(bool(count))
        self._mask_select_btn.setEnabled(bool(count))
        if count:
            meshes = ", ".join(_short(m) for m in guide.skin_mask)
            self._mask_label.setText(f"{count} vert(s) on {meshes} - the chain takes weight nowhere else")
        else:
            self._mask_label.setText("no mask - every vert in the tube / gizmo")
        # Safety: the mask is vertex indices - a different vertex count means the
        # topology changed and they may point elsewhere. Flag it, the artist checks with Select.
        changes = guide.mask_count_changes() if count and hasattr(guide, "mask_count_changes") else []
        if changes:
            tip = "Vertex count changed, check if the mask is valid (Select shows it):\n" + "\n".join(
                f"   {_short(mesh)}: {then} -> {now} verts" for mesh, then, now in changes)
            self._mask_label.setStyleSheet(f"color: {_ORANGE};")
            self._mask_label.setToolTip(tip)
            self._mask_warn.setToolTip(tip)
            self._mask_warn.show()
        else:
            self._mask_label.setStyleSheet("color: #888;")
            self._mask_label.setToolTip("")
            self._mask_warn.hide()

    def _refresh_gizmo_size(self) -> None:
        """The size box follows the gizmo (it may have been scaled in the viewport)."""
        size = self._guide.gizmo_size() if hasattr(self._guide, "gizmo_size") else None
        self._gizmo_size.blockSignals(True)
        self._gizmo_size.setEnabled(size is not None)
        self._gizmo_size.setValue(int(round(size)) if size is not None else 100)
        self._gizmo_size.blockSignals(False)

    def _refresh_gizmo_label(self) -> None:
        """Clip state, warning in red when the gizmo cuts the chain's own curve."""
        guide = self._guide
        self._refresh_gizmo_size()
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

    def _refresh_layer_label(self) -> None:
        try:
            info = self._guide.skin_layer_info()
        except Exception as e:
            info = {"chains": [], "verts": 0, "time": "", "legacy": [], "error": str(e)}
        if info.get("legacy"):
            self._layer_label.setStyleSheet("color: #e06c5a;")
            self._layer_label.setText(
                f"This skin carries DynForge weights no layer records ({len(info['legacy'])} chain joint(s)) - "
                "installed before the layer existed and its backup was lost. Install / uninstall refuse it "
                "until it is recovered.")
        elif info.get("chains"):
            self._layer_label.setStyleSheet("")
            self._layer_label.setText(f"{len(info['chains'])} chain(s) on {info['verts']} vert(s) - "
                                      f"{', '.join(info['chains'])}  ({info['time']})")
        else:
            self._layer_label.setStyleSheet("color: #888;")
            self._layer_label.setText("No DynForge weight on this skin.")
        self._remove_layer_btn.setEnabled(bool(info.get("chains")))

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
            if pct <= 0.0:
                # In the skin, but no weight within the reach radius of the chain.
                for column in (0, 1):
                    item.setForeground(column, QtGui.QColor(_ZERO_GREY))
                    item.setToolTip(column, "No weight within the reach radius of the chain - "
                                            "raise Scale and Analyze again to include it.")
            self._tree.addTopLevelItem(item)
            item.setSelected(_short(name) in donors)
        self._guide = guide
        self._refresh_labels()
        if not any(pct > 0.0 for _, pct in ranked):
            self._warn("No skin weight found around the chain - raise the reach scale.")

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

    def _on_gizmo_size(self,
                       value: int,) -> None:
        if self._guide is None:
            return
        self._guide.set_gizmo_size(float(value))
        self._refresh_gizmo_label()   # coverage may drop below the chain when shrinking

    def _set_mask(self,
                  add: bool,) -> None:
        if self._guide is None:
            return
        try:
            self._guide.set_mask_from_selection(add=add)
        except ValueError as e:
            self._warn(str(e))
        self._refresh_mask_label()

    def _on_mask_set(self) -> None:
        self._set_mask(add=False)

    def _on_mask_add(self) -> None:
        self._set_mask(add=True)

    def _on_mask_clear(self) -> None:
        if self._guide is None:
            return
        self._guide.clear_mask()
        self._refresh_mask_label()

    def _on_mask_select(self) -> None:
        if self._guide is not None:
            self._guide.select_mask()

    def _on_remove_layer(self) -> None:
        if self._guide is None:
            return
        reply = QtWidgets.QMessageBox.question(
            self, "DynForge",
            "Give back every weight the DynForge installs moved on this skin? The other edits stay; "
            "the chains stay in the rig at weight 0, locked.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if reply != QtWidgets.QMessageBox.Yes:
            return
        peers = self._peers_provider(self._guide.skin_cluster) if self._peers_provider else []
        try:
            report = self._guide.remove_skin_layer(skin_peers=tuple(peers))
        except Exception as e:
            self._warn(f"Remove failed:\n{e}")
            return
        conflicts = report.get("conflicts") or []
        if conflicts:
            self._warn(f"Removed, with {len(conflicts)} vertex conflict(s) (edited since the install):\n\n"
                       + "\n".join(conflicts[:15]))
        self._refresh_labels()
