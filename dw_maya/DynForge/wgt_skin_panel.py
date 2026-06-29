"""
wgt_skin_panel.py - DynForge "Skinning" tab (phase 1: read-only).

Per the selected guide: register its skinCluster, drop a region gizmo on the
_PIN joint, and rank the current influences by participation inside the gizmo.
Nothing writes weights here - that happens on Install (later phase). The picked
donor influences, parent bone and falloff power are stored on the guide.
"""

from __future__ import annotations

from functools import partial

from dw_maya.DynForge.forge_cmds.compat import QtWidgets, Qt
from dw_maya.DynForge.wgt_base import DynForgeWidgetBase
from dw_logger import get_logger

logger = get_logger()


_SHAPES = ("Box", "Sphere", "Capsule")
_INFL_ROLE = Qt.UserRole + 1


class SkinPanel(DynForgeWidgetBase):
    """Skinning setup for the selected guide (registration + region + analysis)."""

    def __init__(self,
                 hub,
                 parent=None,) -> None:
        super().__init__(hub, parent)
        self._guide = None
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

        self._stack.addWidget(self._build_content())

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

        # Region gizmo
        giz_box = QtWidgets.QGroupBox("Region gizmo (centered on _PIN)")
        giz_layout = QtWidgets.QHBoxLayout(giz_box)
        self._shape_combo = QtWidgets.QComboBox()
        self._shape_combo.addItems(_SHAPES)
        giz_layout.addWidget(self._shape_combo)
        self._gizmo_btn = QtWidgets.QPushButton("Create / reset gizmo")
        giz_layout.addWidget(self._gizmo_btn)
        giz_layout.addStretch(1)
        layout.addWidget(giz_box)

        # Participation
        part_box = QtWidgets.QGroupBox("Influence participation (inside gizmo)")
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
        part_layout.addWidget(QtWidgets.QLabel(
            "Click a row to inspect its paint; selection = donor bones."))
        layout.addWidget(part_box, stretch=1)

        # Parent bone + power
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
        self._power.setToolTip("Spatial cascade falloff width (used on install).")
        form.addRow("Power", self._power)
        layout.addWidget(bottom_box)

        # Backup / restore
        backup_box = QtWidgets.QGroupBox("Backup")
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
        self._gizmo_btn.clicked.connect(self._on_create_gizmo)
        self._shape_combo.currentIndexChanged.connect(self._on_shape_changed)
        self._analyze_btn.clicked.connect(self._on_analyze)
        self._tree.itemClicked.connect(self._on_row_clicked)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._parent_btn.clicked.connect(self._on_pick_parent)
        self._power.valueChanged.connect(self._on_power_changed)
        self._backup_btn.clicked.connect(self._on_backup)
        self._restore_btn.clicked.connect(self._on_restore)

        return content

    # -- Public -----------------------------------------------------------

    def load_guide(self,
                   guide,) -> None:
        """Show the panel for `guide`, or the placeholder when None."""
        self._guide = None   # mute handlers while populating
        if guide is None:
            self._tree.clear()
            self._stack.setCurrentIndex(0)
            return

        skin = getattr(guide, "skin_cluster", None)
        meshes = getattr(guide, "skin_meshes", []) or []
        self._skin_label.setText(
            f"skinCluster: {skin}  ({len(meshes)} mesh)" if skin else "skinCluster: -")

        idx = self._shape_combo.findText(getattr(guide, "gizmo_shape", "box").capitalize())
        if idx >= 0:
            self._shape_combo.setCurrentIndex(idx)
        self._power.setValue(getattr(guide, "power", 1.0))
        parent = getattr(guide, "parent_bone", None)
        self._parent_label.setText(parent.split("|")[-1] if parent else "-")
        self._tree.clear()

        self._guide = guide
        self._refresh_backup_label()
        self._stack.setCurrentIndex(1)

    def _refresh_backup_label(self) -> None:
        has = False
        if self._guide is not None and hasattr(self._guide, "has_skin_backup"):
            try:
                has = self._guide.has_skin_backup()
            except Exception:
                has = False
        self._backup_label.setText("Backup stored" if has else "No backup")

    def reload_if_current(self,
                          guide,) -> None:
        if guide is self._guide:
            self.load_guide(guide)

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
        meshes = self._guide.skin_meshes or []
        self._skin_label.setText(
            f"skinCluster: {self._guide.skin_cluster}  ({len(meshes)} mesh)")

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

    def _on_analyze(self) -> None:
        if self._guide is None:
            return
        try:
            ranked = self._guide.analyze()
        except Exception as e:
            self._warn(f"Analyze failed:\n{e}")
            return
        self._tree.clear()
        for name, pct in ranked:
            item = QtWidgets.QTreeWidgetItem([name.split("|")[-1], f"{pct:.1f}"])
            item.setData(0, _INFL_ROLE, name)
            self._tree.addTopLevelItem(item)
        if not ranked:
            self._warn("No influences found inside the gizmo.")

    def _on_row_clicked(self,
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

    def _on_pick_parent(self) -> None:
        if self._guide is None:
            return
        try:
            parent = self._guide.set_parent_from_selection()
        except Exception as e:
            self._warn(f"Pick parent failed:\n{e}")
            return
        self._parent_label.setText(parent.split("|")[-1])

    def _on_power_changed(self, *args) -> None:
        if self._guide is not None:
            self._guide.power = self._power.value()

    def _on_backup(self) -> None:
        if self._guide is None:
            return
        try:
            if self._guide.has_skin_backup():
                reply = QtWidgets.QMessageBox.question(
                    self, "DynForge",
                    "A backup already exists. Overwrite it with the current "
                    "(possibly modified) skin?",
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