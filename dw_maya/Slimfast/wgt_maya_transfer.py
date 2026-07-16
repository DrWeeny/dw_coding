"""Maya Map Transfer - store weight maps of meshes and re-apply on a target.

A small companion window for Slimfast (opened from its menu bar). The left
tree stores meshes and their weight maps (per-item checkboxes pick what gets
saved); storages can be saved to JSON ("Json Export" row) and reopened in
another Maya session. The right tree picks a single target mesh and matches
its maps to the stored ones by name - each row carries its own source mesh +
source map pick, so several stored meshes can feed one target. Apply does
either a same-topology copy or a nearest-neighbour transfer.

Usage (inside Maya)::

    from dw_maya.Slimfast import wgt_maya_transfer
    wgt_maya_transfer.launch()

Classes:
    MayaMapTransferWidget: the dockable-style transfer window.

Functions:
    launch: create / raise the singleton window.

Author:
    DrWeeny
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from functools import partial

from maya import cmds
import maya.OpenMayaUI as omui

try:
    from PySide6 import QtCore, QtGui, QtWidgets, QtPositioning
    from PySide6.QtCore import Qt
    from shiboken6 import wrapInstance
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Qt
    from shiboken2 import wrapInstance

from dw_ressources import get_resource_path
import dw_maya.Slimfast.transfer_cmds as transfer_cmds
import dw_maya.Slimfast.type_colors as type_colors
import dw_maya.Slimfast.wgt_splitter_arrow
from dw_logger import get_logger

logger = get_logger()

_ROLE_DATA = Qt.UserRole + 1
# Parent rows in the store tree reflect / drive their children's checkboxes.
_TRISTATE_FLAG = getattr(Qt, "ItemIsAutoTristate", getattr(Qt, "ItemIsTristate", 0))
ICON_PATH = get_resource_path("Feedbin-Icon-left-arrow.svg.png")

def _entry_type(entry: dict) -> str:
    """Return a map entry's grouping type, robust to older saved files."""
    return entry.get("type_name") or entry.get("node_type") or "Unknown"


def _backfill_type_names(meshes: list) -> None:
    """Fill missing ``type_name`` on entries loaded from older save files.

    Pre-``type_name`` storages only carry ``node_type``; deriving the class
    name from the node-type bridge makes their colours and type filters match
    a freshly resolved target (and the Slimfast combo).
    """
    for snap in meshes:
        for entry in snap.get("maps", []):
            if not entry.get("type_name"):
                node_type = entry.get("node_type")
                if node_type:
                    entry["type_name"] = type_colors.type_for_node_type(node_type)


def _color_for(entry: dict) -> "QtGui.QColor":
    """Return the row colour for a map entry.

    Prefers the WeightSource class name (``type_name``). Older entries that
    only carry a Maya ``node_type`` are routed through the node-type bridge, so
    their colour matches the Slimfast combo instead of keying off the raw node
    type string (which would bypass the mapping).
    """
    type_name = entry.get("type_name")
    if type_name:
        return type_colors.get_color(type_name)
    node_type = entry.get("node_type")
    if node_type:
        return type_colors.get_color_for_node_type(node_type)
    return type_colors.get_color("Unknown")

def _menu_exec(menu: QtWidgets.QMenu, pos: "QtCore.QPoint") -> None:
    """Run a context menu on PySide2 (exec_) and PySide6 (exec) alike."""
    runner = getattr(menu, "exec_", None) or menu.exec
    runner(pos)


def _maya_main_window() -> QtWidgets.QWidget:
    """Return Maya's main window so the tool parents correctly."""
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QWidget)


class _RowCombo(QtWidgets.QComboBox):
    """Combo for narrow tree columns: shrinkable, self-tooltipping, wide popup.

    The closed combo may clip long mesh/map names to the column width, so the
    tooltip always shows the full current text and the dropdown expands to fit
    the longest item instead of the column.
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        # Let the column, not the longest item, drive the closed width.
        self.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(6)

    def event(self, e: "QtCore.QEvent") -> bool:
        # Dynamic tooltip: always the current value, no sync bookkeeping.
        if e.type() == QtCore.QEvent.ToolTip:
            text = self.currentText()
            if text and text != "-":
                QtWidgets.QToolTip.showText(e.globalPos(), text, self)
            else:
                QtWidgets.QToolTip.hideText()
            return True
        return super().event(e)

    def showPopup(self) -> None:
        fm = self.fontMetrics()
        measure = getattr(fm, "horizontalAdvance", fm.width)
        width = self.width()
        for i in range(self.count()):
            width = max(width, measure(self.itemText(i)) + 28)
        self.view().setMinimumWidth(width)
        super().showPopup()

class MayaMapTransferWidget(QtWidgets.QWidget):
    """Two-tree UI to store weight maps and transfer them onto a target."""

    _instance: Optional["MayaMapTransferWidget"] = None

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent or _maya_main_window())
        self.setWindowTitle("Maya Map Transfer")
        self.setWindowFlags(Qt.Window)
        self.setMinimumSize(680, 460)

        # Source of truth: list of snapshot dicts (see transfer_cmds.snapshot_mesh)
        # Each map entry additionally carries a UI-only "enabled" key (saved
        # files never include it) backing the store-tree checkboxes.
        self._storage: List[Dict[str, Any]] = []
        # Live target maps (transfer_cmds.list_target_maps) + the target mesh
        self._target_maps: List[Dict[str, Any]] = []
        self._target_mesh: Optional[str] = None
        # Per-type visibility filters, built dynamically from resolved types
        # (type_name -> shown). New types default to shown.
        self._type_filters: Dict[str, bool] = {}

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        splitter = dw_maya.Slimfast.wgt_splitter_arrow.ArrowSplitter(Qt.Horizontal)
        splitter.setHandleWidth(16)
        splitter.addWidget(self._build_store_panel())
        splitter.addWidget(self._build_match_panel())
        splitter.setSizes([260, 420])
        root.addWidget(splitter, stretch=1)

        root.addWidget(self._build_apply_bar())

        self._status = QtWidgets.QLabel("Ready.")
        self._status.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        root.addWidget(self._status)

    def _build_store_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(QtWidgets.QLabel("Add a mesh"))
        self._add_btn = QtWidgets.QPushButton("+")
        self._add_btn.setFixedWidth(28)
        self._add_btn.setToolTip("Store the selected mesh and all its weight maps")
        self._del_btn = QtWidgets.QPushButton("-")
        self._del_btn.setFixedWidth(28)
        self._del_btn.setToolTip("Remove the selected mesh from the storage")
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._del_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._store_tree = QtWidgets.QTreeWidget()
        self._store_tree.setHeaderLabels(["Stored maps"])
        self._store_tree.setRootIsDecorated(True)
        self._store_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        lay.addWidget(self._store_tree, stretch=1)

        export_row = QtWidgets.QHBoxLayout()
        export_row.addWidget(QtWidgets.QLabel(" Json Export"))
        self._save_btn = QtWidgets.QPushButton("Save...")
        self._save_btn.setToolTip("Save the checked maps to a JSON file")
        self._load_btn = QtWidgets.QPushButton("Load...")
        self._load_btn.setToolTip("Load a storage saved from another Maya session")
        export_row.addWidget(self._save_btn)
        export_row.addWidget(self._load_btn)
        export_row.addStretch()
        lay.addLayout(export_row)

        return panel

    def _build_match_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        tgt_row = QtWidgets.QHBoxLayout()
        tgt_row.addWidget(QtWidgets.QLabel("Target mesh"))
        self._target_edit = QtWidgets.QLineEdit()
        self._target_edit.setPlaceholderText("- no target -")
        self._target_edit.setToolTip(
            "Type a mesh name and press Enter, or use the pick button."
        )
        tgt_row.addWidget(self._target_edit, stretch=1)
        self._pick_target_btn = QtWidgets.QPushButton()
        self._pick_target_btn.setFixedSize(16, 16)
        self._pick_target_btn.setToolTip("Pick the target mesh from the viewport selection")
        pixmap = QtGui.QPixmap(str(ICON_PATH))
        if not pixmap.isNull():
            icon = QtGui.QIcon(pixmap)
            self._pick_target_btn.setIcon(icon)
        else:
            self._pick_target_btn.setText("<")
        tgt_row.addWidget(self._pick_target_btn)
        self._map_count_label = QtWidgets.QLabel("")
        self._map_count_label.setStyleSheet("color: #888888; font-style: italic;")
        tgt_row.addWidget(self._map_count_label)
        lay.addLayout(tgt_row)

        # Per-type filters, rebuilt from whatever types the target exposes.
        # Untick a type to drop those maps entirely.
        self._filter_bar = QtWidgets.QHBoxLayout()
        self._filter_bar.setContentsMargins(0, 0, 0, 0)
        self._filter_checks: Dict[str, QtWidgets.QCheckBox] = {}
        lay.addLayout(self._filter_bar)

        self._match_tree = QtWidgets.QTreeWidget()
        self._match_tree.setHeaderLabels(["On", "Target map", "From source mesh", "From source map"])
        self._match_tree.setRootIsDecorated(False)
        self._match_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        # Multi-selection enables bulk edits: editing a combo on a row that is
        # part of a 2+ selection applies the pick to every selected row.
        self._match_tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        header = self._match_tree.header()
        header.resizeSection(0, 36)
        header.resizeSection(1, 150)
        header.resizeSection(2, 130)
        header.setStretchLastSection(True)
        lay.addWidget(self._match_tree, stretch=1)

        return panel

    def _build_apply_bar(self) -> QtWidgets.QWidget:
        bar = QtWidgets.QFrame()
        bar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(6, 4, 6, 4)

        lay.addWidget(QtWidgets.QLabel("Mode"))
        self._mode_combo = QtWidgets.QComboBox()
        self._mode_combo.addItems(["Copy (same topology)", "Transfer (nearest)"])
        self._mode_combo.setToolTip(
            "Copy: index-for-index; on mismatched vertex counts the overlapping\n"
            "range is copied and the tail follows 'Preserve unmapped' (with a\n"
            "confirmation prompt).\n"
            "Transfer: nearest-neighbour, works across different topology."
        )
        lay.addWidget(self._mode_combo)

        self._limit_check = QtWidgets.QCheckBox("Limit dist")
        self._max_dist_spin = QtWidgets.QDoubleSpinBox()
        self._max_dist_spin.setRange(0.0, 99999.0)
        self._max_dist_spin.setDecimals(3)
        self._max_dist_spin.setEnabled(False)
        self._limit_check.toggled.connect(self._max_dist_spin.setEnabled)
        lay.addWidget(self._limit_check)
        lay.addWidget(self._max_dist_spin)

        self._preserve_check = QtWidgets.QCheckBox("Preserve unmapped")
        self._preserve_check.setChecked(True)
        self._preserve_check.setToolTip(
            "Transfer: vertices farther than the distance limit keep their weight.\n"
            "Copy: target vertices beyond a shorter source keep their weight\n"
            "(unchecked: they get 0)."
        )
        lay.addWidget(self._preserve_check)

        self._mask_check = QtWidgets.QCheckBox("Mask: selection")
        self._mask_check.setToolTip(
            "Only write the target vertices currently selected in the viewport.\n"
            "Other vertices keep their original weight."
        )
        lay.addWidget(self._mask_check)

        lay.addStretch()
        self._apply_btn = QtWidgets.QPushButton("Apply ▶")
        self._apply_btn.setFixedHeight(28)
        self._apply_btn.setStyleSheet(
            "QPushButton { background-color: #405060; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #506070; }"
        )
        lay.addWidget(self._apply_btn)

        # Transfer-only options are meaningless for Copy mode.
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._on_mode_changed(0)
        return bar

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._add_btn.clicked.connect(self._on_add)
        self._del_btn.clicked.connect(self._on_remove)
        self._save_btn.clicked.connect(self._on_save)
        self._load_btn.clicked.connect(self._on_load)
        self._store_tree.itemChanged.connect(self._on_store_item_changed)
        self._store_tree.customContextMenuRequested.connect(self._on_store_menu)
        self._pick_target_btn.clicked.connect(self._on_pick_target)
        self._target_edit.returnPressed.connect(self._on_target_typed)
        self._match_tree.customContextMenuRequested.connect(self._on_match_menu)
        self._apply_btn.clicked.connect(self._on_apply)

    # ------------------------------------------------------------------
    # Storage tree
    # ------------------------------------------------------------------

    def _on_add(self) -> None:
        meshes = transfer_cmds.selected_meshes()
        if not meshes:
            self._warn("Select one or more meshes first, then click +.")
            return
        added: List[str] = []
        no_maps: List[str] = []
        for mesh in meshes:
            snap = transfer_cmds.snapshot_mesh(mesh)
            if not snap["maps"]:
                no_maps.append(snap["mesh"])
                continue
            for entry in snap["maps"]:
                entry.setdefault("enabled", True)
            self._storage.append(snap)
            added.append(f"{snap['mesh']} ({len(snap['maps'])} maps)")
        if added:
            self._rebuild_store_tree()
            self._rebuild_match_tree()
        if not added:
            self._warn(f"No paintable weight maps on: {', '.join(no_maps)}.")
            return
        msg = f"Stored {', '.join(added)}."
        if no_maps:
            msg += f" Skipped (no maps): {', '.join(no_maps)}."
        self._set_status(msg)

    def _on_remove(self) -> None:
        index = self._selected_store_index()
        if index < 0:
            return
        removed = self._storage.pop(index)
        self._rebuild_store_tree()
        self._rebuild_match_tree()
        self._set_status(f"Removed '{removed['mesh']}'.")

    def _rebuild_store_tree(self) -> None:
        # Signals stay blocked for the whole rebuild: clear() would otherwise
        # fire itemChanged / currentItemChanged on dying rows.
        self._store_tree.blockSignals(True)
        try:
            self._store_tree.clear()
            for m_idx, snap in enumerate(self._storage):
                top = QtWidgets.QTreeWidgetItem([f"{snap['mesh']}  ({snap['vtx_count']} vtx)"])
                top.setData(0, _ROLE_DATA, m_idx)
                top.setFlags(top.flags() | Qt.ItemIsUserCheckable | _TRISTATE_FLAG)
                self._store_tree.addTopLevelItem(top)
                all_on = True
                for e_idx, entry in enumerate(snap["maps"]):
                    child = QtWidgets.QTreeWidgetItem([entry["key"]])
                    child.setData(0, _ROLE_DATA, e_idx)
                    child.setToolTip(0, f"{entry['node_name']}.{entry['map_name']} ({entry['node_type']})")
                    child.setForeground(0, _color_for(entry))
                    child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                    enabled = entry.get("enabled", True)
                    all_on = all_on and enabled
                    child.setCheckState(0, Qt.Checked if enabled else Qt.Unchecked)
                    top.addChild(child)
                top.setCheckState(0, Qt.Checked if all_on else Qt.Unchecked)
                top.setExpanded(True)
        finally:
            self._store_tree.blockSignals(False)

    def _selected_store_index(self) -> int:
        item = self._store_tree.currentItem()
        if item is None:
            return -1
        if item.parent() is not None:
            item = item.parent()
        value = item.data(0, _ROLE_DATA)
        return int(value) if value is not None else -1

    def _on_store_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        """Mirror checkbox edits back into the storage entries (Save filter)."""
        if column != 0:
            return
        parent = item.parent()
        if parent is None:
            # Mesh row: auto-tristate propagates to children, whose own
            # itemChanged notifications do the storage writes.
            return
        m_idx = parent.data(0, _ROLE_DATA)
        e_idx = item.data(0, _ROLE_DATA)
        if m_idx is None or e_idx is None:
            return
        try:
            entry = self._storage[int(m_idx)]["maps"][int(e_idx)]
        except (IndexError, ValueError):
            return
        entry["enabled"] = item.checkState(0) == Qt.Checked

    def _on_store_menu(self, pos: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        enable_action = menu.addAction("Enable all")
        disable_action = menu.addAction("Disable all")
        enable_action.triggered.connect(partial(self._set_store_checks, True))
        disable_action.triggered.connect(partial(self._set_store_checks, False))
        _menu_exec(menu, self._store_tree.viewport().mapToGlobal(pos))

    def _set_store_checks(self, checked: bool, *args) -> None:
        """Check / uncheck every stored map (data first, then one rebuild)."""
        for snap in self._storage:
            for entry in snap["maps"]:
                entry["enabled"] = checked
        self._rebuild_store_tree()

    # ------------------------------------------------------------------
    # Target / match tree
    # ------------------------------------------------------------------

    def _on_pick_target(self) -> None:
        mesh = transfer_cmds.selected_mesh()
        if not mesh:
            self._warn("Select the target mesh first, then click the pick button.")
            return
        self._set_target(mesh)

    def _on_target_typed(self) -> None:
        text = self._target_edit.text().strip()
        if not text:
            return
        if not cmds.objExists(text):
            self._warn(f"'{text}' does not exist in the scene.")
            return
        self._set_target(text)

    def _set_target(self, mesh: str) -> None:
        try:
            target_maps = transfer_cmds.list_target_maps(mesh)
        except Exception as e:
            logger.exception(f"set target failed on '{mesh}'")
            self._warn(f"Could not resolve maps on '{mesh}': {e}")
            return
        self._target_mesh = mesh
        self._target_maps = target_maps
        short = mesh.split("|")[-1]
        self._target_edit.setText(short)
        # vtx count mirrors the one shown on stored meshes, so a count
        # mismatch with the intended source is visible before Apply.
        try:
            vtx_count = cmds.polyEvaluate(mesh, vertex=True)
        except Exception:
            vtx_count = None
        counts = f"{len(target_maps)} maps"
        if isinstance(vtx_count, int):
            counts += f", {vtx_count} vtx"
        self._map_count_label.setText(counts)
        self._rebuild_filter_bar()
        self._rebuild_match_tree()
        self._set_status(f"Target set to '{short}'.")

    def refresh_colors(self) -> None:
        """Re-tint both trees and the filter bar after a colour change.

        Called by the Pref-menu colour editor so an open window updates live.
        """
        self._rebuild_store_tree()
        self._rebuild_filter_bar()
        self._rebuild_match_tree()

    def _rebuild_filter_bar(self) -> None:
        """Rebuild the type filter checkboxes from the target's map types."""
        # Drop old widgets.
        while self._filter_bar.count():
            child = self._filter_bar.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        self._filter_checks.clear()

        types = sorted({_entry_type(t) for t in self._target_maps})
        if not types:
            return

        self._filter_bar.addWidget(QtWidgets.QLabel("Show:"))
        for type_name in types:
            self._type_filters.setdefault(type_name, True)
            check = QtWidgets.QCheckBox(type_name)
            check.setChecked(self._type_filters[type_name])
            check.setStyleSheet(f"color: {type_colors.get_color(type_name).name()};")
            check.toggled.connect(partial(self._on_filter_toggled, type_name))
            self._filter_bar.addWidget(check)
            self._filter_checks[type_name] = check
        self._filter_bar.addStretch()

    def _auto_match(self, key: str) -> Tuple[Optional[int], Optional[int]]:
        """Return (mesh index, map index) of the preferred source for *key*.

        Preference order: a stored mesh with the same (namespace-stripped)
        name as the target, then the mesh selected in the store tree, then
        the first stored mesh holding the map. The name match outranks the
        selection so picking a stored target-twin never loses to whatever
        row happens to be highlighted on the left.
        """
        order: List[int] = []
        if self._target_mesh:
            tgt_short = self._target_mesh.split("|")[-1].split(":")[-1]
            for i, snap in enumerate(self._storage):
                if snap["mesh"].split(":")[-1] == tgt_short:
                    order.append(i)
        selected = self._selected_store_index()
        if selected >= 0 and selected not in order:
            order.append(selected)
        for i in range(len(self._storage)):
            if i not in order:
                order.append(i)

        for m_idx in order:
            for e_idx, entry in enumerate(self._storage[m_idx]["maps"]):
                if entry["key"] == key:
                    return m_idx, e_idx
        return None, None

    def _rebuild_match_tree(self) -> None:
        """One row per *target* map with its own source mesh + map combos.

        Target-driven so every map on the target object is listed - including
        ones absent from the saved storage, which simply default to '-' (skip)
        until the user assigns a relevant source. Tree signals stay blocked
        for the whole rebuild (clear() deletes the row combos, and their late
        signals used to land on dead items).
        """
        self._match_tree.blockSignals(True)
        try:
            self._match_tree.clear()
            if not self._target_maps:
                return

            for tgt in self._target_maps:
                if not self._type_filters.get(_entry_type(tgt), True):
                    continue
                item = QtWidgets.QTreeWidgetItem(["", tgt["key"], "", ""])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setData(0, _ROLE_DATA, tgt)
                item.setForeground(1, _color_for(tgt))

                mesh_combo = _RowCombo(self._match_tree)
                mesh_combo.addItem("-", None)
                for m_idx, snap in enumerate(self._storage):
                    mesh_combo.addItem(snap["mesh"], m_idx)
                map_combo = _RowCombo(self._match_tree)
                map_combo.addItem("-", None)

                match_mesh, match_map = self._auto_match(tgt["key"])
                if match_mesh is not None:
                    mesh_combo.setCurrentIndex(match_mesh + 1)
                    self._fill_map_combo(map_combo, match_mesh)
                    map_combo.setCurrentIndex(match_map + 1)
                    item.setCheckState(0, Qt.Checked)
                else:
                    item.setCheckState(0, Qt.Unchecked)

                self._match_tree.addTopLevelItem(item)
                self._match_tree.setItemWidget(item, 2, mesh_combo)
                self._match_tree.setItemWidget(item, 3, map_combo)
                # Connect after the initial population so setup never
                # triggers the handlers.
                mesh_combo.currentIndexChanged.connect(
                    partial(self._on_mesh_combo_changed, item)
                )
                map_combo.currentIndexChanged.connect(
                    partial(self._on_map_combo_changed, item)
                )
        finally:
            self._match_tree.blockSignals(False)

    def _fill_map_combo(self,
                        map_combo: QtWidgets.QComboBox,
                        m_idx: int) -> None:
        """Repopulate a row's map combo with the maps of stored mesh *m_idx*."""
        map_combo.blockSignals(True)
        try:
            map_combo.clear()
            map_combo.addItem("-", None)
            for e_idx, entry in enumerate(self._storage[m_idx]["maps"]):
                map_combo.addItem(entry["key"], (m_idx, e_idx))
        finally:
            map_combo.blockSignals(False)

    def _row_combos(self,
                    item: QtWidgets.QTreeWidgetItem,
                    ) -> Tuple[Optional[QtWidgets.QComboBox], Optional[QtWidgets.QComboBox]]:
        """Return a row's (mesh combo, map combo), or Nones for a dead row.

        Guarded: a combo signal can arrive after clear() deleted the item
        (the historical 'set target errors' bug).
        """
        try:
            mesh_combo = self._match_tree.itemWidget(item, 2)
            map_combo = self._match_tree.itemWidget(item, 3)
        except RuntimeError:
            return None, None
        return mesh_combo, map_combo

    def _on_filter_toggled(self, type_name: str, checked: bool) -> None:
        """Show or hide all maps of one source type in the match tree."""
        self._type_filters[type_name] = checked
        self._rebuild_match_tree()

    def _bulk_targets(self, item: QtWidgets.QTreeWidgetItem) -> List[QtWidgets.QTreeWidgetItem]:
        """Return the other rows a combo edit should propagate to.

        Implicit bulk rule: only when the edited row belongs to a selection of
        two or more rows (ctrl-clicking rows reads as bulk intent). Editing a
        row outside the selection stays local to that row.
        """
        try:
            selected = self._match_tree.selectedItems()
        except RuntimeError:
            return []
        if len(selected) < 2 or item not in selected:
            return []
        return [other for other in selected if other is not item]

    def _refill_row_maps(self, item: QtWidgets.QTreeWidgetItem, m_idx: Optional[int]) -> None:
        """Repopulate a row's map combo for mesh *m_idx*, auto-matching by name."""
        _mesh_combo, map_combo = self._row_combos(item)
        if map_combo is None:
            return
        map_combo.blockSignals(True)
        try:
            map_combo.clear()
            map_combo.addItem("-", None)
            if m_idx is not None:
                tgt = item.data(0, _ROLE_DATA)
                auto_index = 0
                for e_idx, entry in enumerate(self._storage[m_idx]["maps"]):
                    map_combo.addItem(entry["key"], (m_idx, e_idx))
                    if tgt is not None and entry["key"] == tgt["key"]:
                        auto_index = e_idx + 1
                map_combo.setCurrentIndex(auto_index)
        finally:
            map_combo.blockSignals(False)
        self._update_row_check(item)

    def _set_row_mesh(self, item: QtWidgets.QTreeWidgetItem, m_idx: Optional[int]) -> None:
        """Set a row's source mesh programmatically (no handler re-entry)."""
        mesh_combo, map_combo = self._row_combos(item)
        if mesh_combo is None or map_combo is None:
            return
        mesh_combo.blockSignals(True)
        try:
            mesh_combo.setCurrentIndex(0 if m_idx is None else m_idx + 1)
        finally:
            mesh_combo.blockSignals(False)
        self._refill_row_maps(item, m_idx)

    def _set_row_map_by_key(self, item: QtWidgets.QTreeWidgetItem, key: Optional[str]) -> None:
        """Pick *key* in a row's map combo; rows lacking that map keep theirs."""
        _mesh_combo, map_combo = self._row_combos(item)
        if map_combo is None:
            return
        index = 0 if key is None else map_combo.findText(key)
        if index < 0:
            return
        map_combo.blockSignals(True)
        try:
            map_combo.setCurrentIndex(index)
        finally:
            map_combo.blockSignals(False)
        self._update_row_check(item)

    def _on_mesh_combo_changed(self, item: QtWidgets.QTreeWidgetItem, _index: int) -> None:
        """Refill the row's map combo; propagate to a multi-selection."""
        mesh_combo, _map_combo = self._row_combos(item)
        if mesh_combo is None:
            return
        m_idx = mesh_combo.currentData()
        self._refill_row_maps(item, m_idx)
        for other in self._bulk_targets(item):
            self._set_row_mesh(other, m_idx)

    def _on_map_combo_changed(self, item: QtWidgets.QTreeWidgetItem, _index: int) -> None:
        self._update_row_check(item)
        _mesh_combo, map_combo = self._row_combos(item)
        if map_combo is None:
            return
        key = map_combo.currentText() if map_combo.currentData() is not None else None
        for other in self._bulk_targets(item):
            self._set_row_map_by_key(other, key)

    def _update_row_check(self, item: QtWidgets.QTreeWidgetItem) -> None:
        """Auto-enable a row when a real source map is picked, untick otherwise."""
        _mesh_combo, map_combo = self._row_combos(item)
        if map_combo is None:
            return
        try:
            item.setCheckState(0, Qt.Checked if map_combo.currentData() is not None else Qt.Unchecked)
        except RuntimeError:
            pass

    def _on_match_menu(self, pos: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        selected = self._match_tree.selectedItems()

        enable_sel = menu.addAction("Enable selected")
        disable_sel = menu.addAction("Disable selected")
        enable_sel.triggered.connect(partial(self._set_selected_checks, True))
        disable_sel.triggered.connect(partial(self._set_selected_checks, False))

        mesh_menu = menu.addMenu("Set source mesh (selected rows)")
        none_action = mesh_menu.addAction("-")
        none_action.triggered.connect(partial(self._set_selected_mesh, None))
        for m_idx, snap in enumerate(self._storage):
            action = mesh_menu.addAction(snap["mesh"])
            action.triggered.connect(partial(self._set_selected_mesh, m_idx))

        map_menu = menu.addMenu("Set source map (selected rows)")
        none_action = map_menu.addAction("-")
        none_action.triggered.connect(partial(self._set_selected_map, None))
        keys = sorted({entry["key"] for snap in self._storage for entry in snap["maps"]})
        for key in keys:
            action = map_menu.addAction(key)
            action.triggered.connect(partial(self._set_selected_map, key))

        for action in (enable_sel, disable_sel):
            action.setEnabled(bool(selected))
        mesh_menu.setEnabled(bool(selected) and bool(self._storage))
        map_menu.setEnabled(bool(selected) and bool(keys))

        menu.addSeparator()
        enable_action = menu.addAction("Enable all")
        disable_action = menu.addAction("Disable all")
        enable_action.triggered.connect(partial(self._set_match_checks, True))
        disable_action.triggered.connect(partial(self._set_match_checks, False))
        _menu_exec(menu, self._match_tree.viewport().mapToGlobal(pos))

    def _set_selected_checks(self, checked: bool, *_) -> None:
        """Enable (rows with a source only) / disable the selected rows."""
        for item in self._match_tree.selectedItems():
            if not checked:
                item.setCheckState(0, Qt.Unchecked)
                continue
            _mesh_combo, map_combo = self._row_combos(item)
            has_source = map_combo is not None and map_combo.currentData() is not None
            item.setCheckState(0, Qt.Checked if has_source else Qt.Unchecked)

    def _set_selected_mesh(self, m_idx: Optional[int], *_) -> None:
        for item in self._match_tree.selectedItems():
            self._set_row_mesh(item, m_idx)

    def _set_selected_map(self, key: Optional[str], *_) -> None:
        for item in self._match_tree.selectedItems():
            self._set_row_map_by_key(item, key)

    def _set_match_checks(self, checked: bool, *_) -> None:
        """Enable rows that have a source picked / disable every row."""
        for i in range(self._match_tree.topLevelItemCount()):
            item = self._match_tree.topLevelItem(i)
            if not checked:
                item.setCheckState(0, Qt.Unchecked)
                continue
            _mesh_combo, map_combo = self._row_combos(item)
            has_source = map_combo is not None and map_combo.currentData() is not None
            item.setCheckState(0, Qt.Checked if has_source else Qt.Unchecked)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _on_mode_changed(self, index: int) -> None:
        is_transfer = index == 1
        self._limit_check.setEnabled(is_transfer)
        self._max_dist_spin.setEnabled(is_transfer and self._limit_check.isChecked())
        # Preserve unmapped applies to both modes: in Copy it decides whether
        # target vertices beyond a shorter source keep their weight or get 0.

    def _on_apply(self) -> None:
        if not self._storage:
            self._warn("Store at least one mesh on the left.")
            return
        if not self._target_maps:
            self._warn("Set a target mesh on the right first.")
            return

        is_transfer = self._mode_combo.currentIndex() == 1
        max_dist = None
        if is_transfer and self._limit_check.isChecked():
            max_dist = float(self._max_dist_spin.value())
        preserve = self._preserve_check.isChecked()

        mask = None
        if self._mask_check.isChecked():
            mask = transfer_cmds.selected_vertex_indices(self._target_mesh)
            if not mask:
                self._warn("Mask is on but no target vertices are selected.")
                return

        # Collect the enabled rows first so mismatches can be confirmed in a
        # single dialog before anything is written.
        jobs: List[Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], str]] = []
        skipped = 0
        for i in range(self._match_tree.topLevelItemCount()):
            item = self._match_tree.topLevelItem(i)
            if item.checkState(0) != Qt.Checked:
                skipped += 1
                continue
            _mesh_combo, map_combo = self._row_combos(item)
            picked = map_combo.currentData() if map_combo else None
            if picked is None:
                skipped += 1
                continue
            m_idx, e_idx = picked
            snap = self._storage[m_idx]
            source = snap["maps"][e_idx]
            target = item.data(0, _ROLE_DATA)
            label = f"{snap['mesh']}.{source['key']} -> {target['key']}"
            jobs.append((snap, source, target, label))

        if not is_transfer and not self._confirm_copy_mismatches(jobs):
            self._set_status("Apply cancelled.")
            return

        done = 0
        errors: List[str] = []

        cmds.undoInfo(openChunk=True, chunkName="mayaMapTransfer")
        try:
            for snap, source, target, label in jobs:
                try:
                    if is_transfer:
                        transfer_cmds.transfer_weights(
                            source["weights"],
                            snap["vtx_positions"],
                            target["source"],
                            target_map=target["map_name"],
                            max_distance=max_dist,
                            preserve_unmapped=preserve,
                            mask=mask,
                        )
                    else:
                        transfer_cmds.copy_weights(
                            source["weights"],
                            target["source"],
                            target_map=target["map_name"],
                            mask=mask,
                            preserve_unmapped=preserve,
                        )
                    done += 1
                except Exception as e:
                    errors.append(f"{label}: {e}")
                    logger.error(f"map transfer failed: {label}: {e}")
        finally:
            cmds.undoInfo(closeChunk=True)

        msg = f"Applied {done} map(s), skipped {skipped}."
        if errors:
            msg += f" {len(errors)} failed."
            QtWidgets.QMessageBox.warning(self, "Map Transfer", msg + "\n\n" + "\n".join(errors))
        self._set_status(msg)

    def _confirm_copy_mismatches(self, jobs: List[tuple]) -> bool:
        """Warn once when Copy rows have mismatched vertex counts.

        Copy is lenient: the overlapping index range copies 1:1 and the tail
        follows 'Preserve unmapped'. That is only meaningful when the shared
        range kept its vertex ids (tail edits), so the artist confirms before
        anything is written. Returns False when the apply should abort.
        """
        mismatched: List[str] = []
        for snap, source, target, label in jobs:
            try:
                tgt_count = target["source"].vtx_count
            except Exception:
                continue
            src_count = len(source["weights"])
            if src_count != tgt_count:
                mismatched.append(f"{label}  (source {src_count} vs target {tgt_count} vtx)")
        if not mismatched:
            return True

        shown = mismatched[:10]
        if len(mismatched) > len(shown):
            shown.append(f"... and {len(mismatched) - len(shown)} more")
        tail = ("keep their current weight ('Preserve unmapped' is on)"
                if self._preserve_check.isChecked() else
                "be set to 0 ('Preserve unmapped' is off)")
        text = (
            f"Be careful: vertex counts do not match on {len(mismatched)} row(s):\n\n"
            + "\n".join(shown)
            + "\n\nCopy will write index-for-index over the overlapping range; "
            + f"target vertices beyond the source range will {tail}. "
            + "This is only exact if the shared range kept its vertex ids "
            + "(tail edits). If the mesh was renumbered, you might want to "
            + "use Transfer (nearest) mode instead.\n\nApply anyway?"
        )
        answer = QtWidgets.QMessageBox.warning(
            self,
            "Map Transfer",
            text,
            QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel,
        )
        return answer == QtWidgets.QMessageBox.Ok

    # ------------------------------------------------------------------
    # Save / load
    # ------------------------------------------------------------------

    def _checked_storage(self) -> List[Dict[str, Any]]:
        """Return the storage filtered to checked maps, UI keys stripped."""
        out: List[Dict[str, Any]] = []
        for snap in self._storage:
            maps = [
                {k: v for k, v in entry.items() if k != "enabled"}
                for entry in snap["maps"]
                if entry.get("enabled", True)
            ]
            if maps:
                kept = dict(snap)
                kept["maps"] = maps
                out.append(kept)
        return out

    def _on_save(self) -> None:
        payload = self._checked_storage()
        if not payload:
            self._warn("Nothing to save - store a mesh and check at least one map.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save map storage", "", "JSON (*.json)"
        )
        if not path:
            return
        if transfer_cmds.save_storage(path, payload):
            n_maps = sum(len(s["maps"]) for s in payload)
            self._set_status(f"Saved {len(payload)} mesh(es) / {n_maps} map(s) to {path}.")
        else:
            self._warn(f"Failed to save to {path}.")

    def _on_load(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load map storage", "", "JSON (*.json)"
        )
        if not path:
            return
        data = transfer_cmds.load_storage(path)
        if data is None:
            self._warn(f"'{path}' is not a valid map storage file.")
            return
        meshes = list(data.get("meshes", []))
        _backfill_type_names(meshes)
        for snap in meshes:
            for entry in snap.get("maps", []):
                entry.setdefault("enabled", True)
        self._storage = meshes
        self._rebuild_store_tree()
        self._rebuild_match_tree()
        self._set_status(f"Loaded {len(self._storage)} mesh(es) from {path}.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, text: str) -> None:
        self._status.setText(text)

    def _warn(self, text: str) -> None:
        self._set_status(text)
        QtWidgets.QMessageBox.warning(self, "Map Transfer", text)


def launch() -> MayaMapTransferWidget:
    """Create or raise the singleton Maya Map Transfer window."""
    if MayaMapTransferWidget._instance is not None:
        try:
            MayaMapTransferWidget._instance.close()
            MayaMapTransferWidget._instance.deleteLater()
        except Exception:
            pass
    win = MayaMapTransferWidget()
    MayaMapTransferWidget._instance = win
    win.show()
    win.raise_()
    return win