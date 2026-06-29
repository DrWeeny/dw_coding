"""Maya Map Transfer - store weight maps of meshes and re-apply on a target.

A small companion window for Slimfast (opened from its menu bar). The left
tree stores meshes and their weight maps; storages can be saved to JSON and
reopened in another Maya session. The right tree picks a single target mesh
and matches its maps to the stored ones by name (auto when names match,
manually otherwise), with a per-row enable toggle. Apply does either a
same-topology copy or a nearest-neighbour transfer.

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

from typing import Any, Dict, List, Optional
from functools import partial

from maya import cmds
import maya.OpenMayaUI as omui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt
    from shiboken6 import wrapInstance
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Qt
    from shiboken2 import wrapInstance

import dw_maya.Slimfast.transfer_cmds as transfer_cmds
import dw_maya.Slimfast.type_colors as type_colors
from dw_logger import get_logger

logger = get_logger()

_ROLE_DATA = Qt.UserRole + 1


def _entry_type(entry: dict) -> str:
    """Return a map entry's grouping type, robust to older saved files."""
    return entry.get("type_name") or entry.get("node_type") or "Unknown"


def _color_for(entry: dict) -> "QtGui.QColor":
    """Return the row colour for a map entry, keyed by its source type name."""
    return type_colors.get_color(_entry_type(entry))


def _maya_main_window() -> QtWidgets.QWidget:
    """Return Maya's main window so the tool parents correctly."""
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QWidget)


class MayaMapTransferWidget(QtWidgets.QWidget):
    """Two-tree UI to store weight maps and transfer them onto a target."""

    _instance: Optional["MayaMapTransferWidget"] = None

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent or _maya_main_window())
        self.setWindowTitle("Maya Map Transfer")
        self.setWindowFlags(Qt.Window)
        self.setMinimumSize(620, 460)

        # Source of truth: list of snapshot dicts (see transfer_cmds.snapshot_mesh)
        self._storage: List[Dict[str, Any]] = []
        # Live target maps (transfer_cmds.list_target_maps) + the target mesh
        self._target_maps: List[Dict[str, Any]] = []
        self._target_mesh: Optional[str] = None
        # Index of the stored mesh currently driving the match tree
        self._active_index: int = -1
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

        splitter = QtWidgets.QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_store_panel())
        splitter.addWidget(self._build_match_panel())
        splitter.setSizes([260, 360])
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
        self._add_btn = QtWidgets.QPushButton("+")
        self._add_btn.setFixedWidth(28)
        self._add_btn.setToolTip("Store the selected mesh and all its weight maps")
        self._del_btn = QtWidgets.QPushButton("-")
        self._del_btn.setFixedWidth(28)
        self._del_btn.setToolTip("Remove the selected mesh from the storage")
        self._save_btn = QtWidgets.QPushButton("Save...")
        self._save_btn.setToolTip("Save the whole storage to a JSON file")
        self._load_btn = QtWidgets.QPushButton("Load...")
        self._load_btn.setToolTip("Load a storage saved from another Maya session")
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._del_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._load_btn)
        lay.addLayout(btn_row)

        self._store_tree = QtWidgets.QTreeWidget()
        self._store_tree.setHeaderLabels(["Stored maps"])
        self._store_tree.setRootIsDecorated(True)
        lay.addWidget(self._store_tree, stretch=1)

        return panel

    def _build_match_panel(self) -> QtWidgets.QWidget:
        panel = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        tgt_row = QtWidgets.QHBoxLayout()
        self._set_target_btn = QtWidgets.QPushButton("Set target from selection")
        tgt_row.addWidget(self._set_target_btn)
        self._target_label = QtWidgets.QLabel("- no target -")
        self._target_label.setStyleSheet("color: #a0c8ff; font-weight: bold;")
        tgt_row.addWidget(self._target_label, stretch=1)
        lay.addLayout(tgt_row)

        # Per-type filters, rebuilt from whatever types the target exposes.
        # Untick a type to drop those maps entirely.
        self._filter_bar = QtWidgets.QHBoxLayout()
        self._filter_bar.setContentsMargins(0, 0, 0, 0)
        self._filter_checks: Dict[str, QtWidgets.QCheckBox] = {}
        lay.addLayout(self._filter_bar)

        self._match_tree = QtWidgets.QTreeWidget()
        self._match_tree.setHeaderLabels(["On", "Target map", "From source"])
        self._match_tree.setRootIsDecorated(False)
        header = self._match_tree.header()
        header.resizeSection(0, 36)
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
            "Copy: index-for-index, needs identical vertex count.\n"
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
        self._store_tree.currentItemChanged.connect(self._on_store_selection)
        self._set_target_btn.clicked.connect(self._on_set_target)
        self._apply_btn.clicked.connect(self._on_apply)

    # ------------------------------------------------------------------
    # Storage tree
    # ------------------------------------------------------------------

    def _on_add(self) -> None:
        mesh = transfer_cmds.selected_mesh()
        if not mesh:
            self._warn("Select a mesh first, then click +.")
            return
        snap = transfer_cmds.snapshot_mesh(mesh)
        if not snap["maps"]:
            self._warn(f"'{snap['mesh']}' has no paintable weight maps.")
            return
        self._storage.append(snap)
        self._rebuild_store_tree()
        self._set_status(f"Stored '{snap['mesh']}' ({len(snap['maps'])} maps).")

    def _on_remove(self) -> None:
        index = self._selected_store_index()
        if index < 0:
            return
        removed = self._storage.pop(index)
        self._rebuild_store_tree()
        self._set_status(f"Removed '{removed['mesh']}'.")

    def _rebuild_store_tree(self) -> None:
        self._store_tree.clear()
        for m_idx, snap in enumerate(self._storage):
            top = QtWidgets.QTreeWidgetItem([f"{snap['mesh']}  ({snap['vtx_count']} vtx)"])
            top.setData(0, _ROLE_DATA, m_idx)
            self._store_tree.addTopLevelItem(top)
            for entry in snap["maps"]:
                child = QtWidgets.QTreeWidgetItem([entry["key"]])
                child.setToolTip(0, f"{entry['node_name']}.{entry['map_name']} ({entry['node_type']})")
                child.setForeground(0, _color_for(entry))
                top.addChild(child)
            top.setExpanded(True)
        # Selection changed implicitly -> refresh match tree
        self._active_index = -1
        self._rebuild_match_tree()

    def _selected_store_index(self) -> int:
        item = self._store_tree.currentItem()
        if item is None:
            return -1
        if item.parent() is not None:
            item = item.parent()
        value = item.data(0, _ROLE_DATA)
        return int(value) if value is not None else -1

    def _on_store_selection(self, *args) -> None:
        index = self._selected_store_index()
        if index != self._active_index:
            self._active_index = index
            self._rebuild_match_tree()

    # ------------------------------------------------------------------
    # Target / match tree
    # ------------------------------------------------------------------

    def _on_set_target(self) -> None:
        mesh = transfer_cmds.selected_mesh()
        if not mesh:
            self._warn("Select the target mesh first, then click the button.")
            return
        self._target_mesh = mesh
        self._target_maps = transfer_cmds.list_target_maps(mesh)
        self._target_label.setText(
            f"{mesh.split('|')[-1]}  ({len(self._target_maps)} maps)"
        )
        self._rebuild_filter_bar()
        self._rebuild_match_tree()
        self._set_status(f"Target set to '{mesh.split('|')[-1]}'.")

    def refresh_colors(self) -> None:
        """Re-tint both trees and the filter bar after a colour change.

        Called by the Pref-menu colour editor so an open window updates live,
        without losing the current stored-mesh selection.
        """
        active = self._active_index
        self._rebuild_store_tree()      # resets _active_index to -1
        self._active_index = active
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

    def _rebuild_match_tree(self) -> None:
        """One row per *target* map; the combo picks the stored source to use.

        Target-driven so every map on the target object is listed - including
        ones absent from the saved storage, which simply default to '-' (skip)
        until the user assigns a relevant source map.
        """
        self._match_tree.clear()
        if not self._target_maps:
            return

        if 0 <= self._active_index < len(self._storage):
            source_maps = self._storage[self._active_index]["maps"]
        else:
            source_maps = []
        source_keys = [s["key"] for s in source_maps]

        for tgt in self._target_maps:
            if not self._type_filters.get(_entry_type(tgt), True):
                continue
            item = QtWidgets.QTreeWidgetItem(["", tgt["key"], ""])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setData(0, _ROLE_DATA, tgt)
            item.setForeground(1, _color_for(tgt))

            combo = QtWidgets.QComboBox(self._match_tree)
            combo.addItem("-", None)
            for src in source_maps:
                combo.addItem(src["key"], src)

            # Auto-match the source whose name equals this target map's name.
            matched = tgt["key"] in source_keys
            if matched:
                combo.setCurrentIndex(source_keys.index(tgt["key"]) + 1)
            item.setCheckState(0, Qt.Checked if matched else Qt.Unchecked)

            self._match_tree.addTopLevelItem(item)
            self._match_tree.setItemWidget(item, 2, combo)
            combo.currentIndexChanged.connect(
                lambda _idx, it=item: self._on_combo_changed(it)
            )

    def _on_filter_toggled(self, type_name: str, checked: bool) -> None:
        """Show or hide all maps of one source type in the match tree."""
        self._type_filters[type_name] = checked
        self._rebuild_match_tree()

    def _on_combo_changed(self, item: QtWidgets.QTreeWidgetItem) -> None:
        """Auto-enable a row when a real source map gets picked for it."""
        combo = self._match_tree.itemWidget(item, 2)
        if combo is None:
            return
        # No source selected -> nothing to transfer, untick the row.
        item.setCheckState(0, Qt.Checked if combo.currentData() is not None else Qt.Unchecked)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _on_mode_changed(self, index: int) -> None:
        is_transfer = index == 1
        self._limit_check.setEnabled(is_transfer)
        self._max_dist_spin.setEnabled(is_transfer and self._limit_check.isChecked())
        self._preserve_check.setEnabled(is_transfer)

    def _on_apply(self) -> None:
        if self._active_index < 0:
            self._warn("Select a stored mesh on the left.")
            return
        if not self._target_maps:
            self._warn("Set a target mesh on the right first.")
            return

        snap = self._storage[self._active_index]
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

        done = 0
        skipped = 0
        errors: List[str] = []

        cmds.undoInfo(openChunk=True, chunkName="mayaMapTransfer")
        try:
            for i in range(self._match_tree.topLevelItemCount()):
                item = self._match_tree.topLevelItem(i)
                if item.checkState(0) != Qt.Checked:
                    skipped += 1
                    continue
                combo = self._match_tree.itemWidget(item, 2)
                source = combo.currentData() if combo else None
                if source is None:
                    skipped += 1
                    continue

                target = item.data(0, _ROLE_DATA)
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
                        )
                    done += 1
                except Exception as e:
                    errors.append(f"{source['key']} -> {target['key']}: {e}")
                    logger.error(f"map transfer failed: {source['key']} -> {target['key']}: {e}")
        finally:
            cmds.undoInfo(closeChunk=True)

        msg = f"Applied {done} map(s), skipped {skipped}."
        if errors:
            msg += f" {len(errors)} failed."
            QtWidgets.QMessageBox.warning(self, "Map Transfer", msg + "\n\n" + "\n".join(errors))
        self._set_status(msg)

    # ------------------------------------------------------------------
    # Save / load
    # ------------------------------------------------------------------

    def _on_save(self) -> None:
        if not self._storage:
            self._warn("Nothing to save - store at least one mesh first.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save map storage", "", "JSON (*.json)"
        )
        if not path:
            return
        if transfer_cmds.save_storage(path, self._storage):
            self._set_status(f"Saved {len(self._storage)} mesh(es) to {path}.")
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
        self._storage = list(data.get("meshes", []))
        self._rebuild_store_tree()
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