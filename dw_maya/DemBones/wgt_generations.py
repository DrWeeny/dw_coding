"""
wgt_generations.py - DemBones generations list.

A tree of every solved FBX in the output dir (backed by fbx + sidecar json),
with a button bar acting on the selected row: Import, Restore params, Reveal,
Delete. The list is rebuilt by scanning the output dir, so it survives restarts.

Signals
-------
    restore_requested(dict)  ask the params panel to load these params.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from dw_maya.DemBones.compat import QtWidgets, Qt, Signal
from dw_maya.DemBones import dem_cmds
from dw_logger import get_logger

logger = get_logger()

_COLS = ["name", "bones", "nnz", "range", "rmse", "mode"]


class GenerationsPanel(QtWidgets.QWidget):
    """List of solved FBX generations + per-selection actions."""

    restore_requested = Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._out_dir: Optional[str] = None
        self._build_ui()
        self._connect()

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        box = QtWidgets.QGroupBox("Generations")
        v = QtWidgets.QVBoxLayout(box)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(len(_COLS))
        self.tree.setHeaderLabels(_COLS)
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        v.addWidget(self.tree, 1)

        bar = QtWidgets.QHBoxLayout()
        self.import_btn = QtWidgets.QPushButton("Import")
        self.restore_btn = QtWidgets.QPushButton("Restore params")
        self.delete_btn = QtWidgets.QPushButton("Delete")
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        for b in (self.import_btn, self.restore_btn, self.delete_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(self.refresh_btn)
        v.addLayout(bar)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(box)

    def _connect(self) -> None:
        self.import_btn.clicked.connect(self._on_import)
        self.restore_btn.clicked.connect(self._on_restore)
        self.delete_btn.clicked.connect(self._on_delete)
        self.refresh_btn.clicked.connect(self.refresh)

    # -- Data -------------------------------------------------------------

    def set_output_dir(self, out_dir: str) -> None:
        self._out_dir = out_dir
        self.refresh()

    def refresh(self) -> None:
        self.tree.clear()
        if not self._out_dir:
            return
        for meta in dem_cmds.scan_generations(self._out_dir):
            params = meta.get("params", {})
            rng = meta.get("range", [None, None])
            rmse = meta.get("rmse")
            item = QtWidgets.QTreeWidgetItem([
                meta.get("name", "?"),
                str(params.get("nBones", "-")),
                str(params.get("nnz", "-")),
                f"{rng[0]}-{rng[1]}" if rng and rng[0] is not None else "-",
                f"{rmse:.4f}" if isinstance(rmse, (int, float)) else "-",
                meta.get("mode", "-"),
            ])
            item.setData(0, Qt.UserRole, meta)
            self.tree.addTopLevelItem(item)
        self.tree.resizeColumnToContents(0)

    def _selected_meta(self) -> Optional[Dict]:
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.UserRole)

    # -- Slots ------------------------------------------------------------

    def _on_import(self) -> None:
        meta = self._selected_meta()
        if not meta:
            return
        index = meta.get("index")
        namespace = f"dem{int(index):03d}" if isinstance(index, int) else None
        try:
            roots = dem_cmds.import_generation(meta["fbx"], namespace=namespace)
            logger.info(f"Imported generation -> {roots}")
        except Exception as e:
            logger.error(f"Import failed: {e}")
            QtWidgets.QMessageBox.critical(self, "DemBones", f"Import failed:\n{e}")

    def _on_restore(self) -> None:
        meta = self._selected_meta()
        if meta and meta.get("params"):
            self.restore_requested.emit(meta["params"])

    def _on_delete(self) -> None:
        meta = self._selected_meta()
        if not meta:
            return
        ok = QtWidgets.QMessageBox.question(
            self, "DemBones",
            f"Delete generation '{meta.get('name')}' (fbx + sidecar)?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if ok != QtWidgets.QMessageBox.Yes:
            return
        for path in (meta["fbx"], dem_cmds.sidecar_path(meta["fbx"])):
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception as e:
                logger.warning(f"Could not delete '{path}': {e}")
        self.refresh()