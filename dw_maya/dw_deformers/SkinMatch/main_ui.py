"""
main_ui.py - SkinMatch: copy skin weights with an explicit influence mapping.

Summary:
    A skin transfer answers two independent questions - which target VERTEX
    takes which source vertex, and which target INFLUENCE takes which source
    influence. Maya's own paths guess both at once and expose neither, so a
    wrong influence pairing still deforms and looks like it worked.

    This window splits the two axes: the vertex correspondence is picked
    explicitly at the bottom, the influence correspondence is built by rule in
    the middle panel and can be corrected by hand, and the right panel puts a
    number on what the mapping would cost before anything is written.

Features:
    - Per-side regex normalisation with the resulting key shown per row.
    - Weight mass at risk, computed before the transfer.
    - Post-transfer verification against the source weights.
    - Mappings save/load as json, rules included.

Example::

    from dw_maya.dw_deformers.SkinMatch import main_ui
    main_ui.launch()

Author: DrWeeny
"""

from __future__ import annotations

from typing import Optional

import maya.cmds as cmds

from dw_maya.dw_deformers.SkinMatch.compat import (
    QtWidgets, Qt, wrapInstance, QAction)
import dw_maya.dw_deformers.SkinMatch.skin_match_cmds as smc
from dw_maya.dw_deformers.SkinMatch.wgt_influence_match import InfluenceMatchPanel
from dw_maya.dw_deformers.SkinMatch.wgt_report import ReportPanel

_window = None

_OK_COLOR  = "QLabel { color: #6cb06c; }"
_BAD_COLOR = "QLabel { color: #d86a6a; }"


class SkinMatchUI(QtWidgets.QMainWindow):
    """Skin weight transfer with a visible, editable influence mapping."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SkinMatchUI")
        self.setWindowTitle("SkinMatch - skin weight transfer")
        self.resize(1180, 660)

        self._src_skin: Optional[str] = None
        self._tgt_skin: Optional[str] = None
        self._vertex_map = None

        self._build_menu()
        self._build_ui()

    # -- UI ---------------------------------------------------------------

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("File")
        save_action = QAction("Save mapping...", self)
        save_action.triggered.connect(self._on_save_mapping)
        menu.addAction(save_action)
        load_action = QAction("Load mapping...", self)
        load_action.triggered.connect(self._on_load_mapping)
        menu.addAction(load_action)

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        outer.addLayout(self._build_mesh_row())

        splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.match_panel = InfluenceMatchPanel()
        self.match_panel.mapping_changed.connect(self._on_mapping_changed)
        self.report_panel = ReportPanel()
        splitter.addWidget(self.match_panel)
        splitter.addWidget(self.report_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, 1)

        outer.addLayout(self._build_action_row())

        self.status_label = QtWidgets.QLabel("Pick a source and a target mesh.")
        outer.addWidget(self.status_label)

    def _build_mesh_row(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()

        self.src_field = QtWidgets.QLineEdit()
        self.src_field.setReadOnly(True)
        self.src_field.setPlaceholderText("source mesh (the solve)")
        src_btn = QtWidgets.QPushButton("<< Source")
        src_btn.setToolTip("Use the selected mesh as the source to read from.")
        src_btn.clicked.connect(self._on_pick_source)
        self.src_skin_label = QtWidgets.QLabel("-")

        self.tgt_field = QtWidgets.QLineEdit()
        self.tgt_field.setReadOnly(True)
        self.tgt_field.setPlaceholderText("target mesh (the asset)")
        tgt_btn = QtWidgets.QPushButton("<< Target")
        tgt_btn.setToolTip("Use the selected mesh as the target to write to.")
        tgt_btn.clicked.connect(self._on_pick_target)
        self.tgt_skin_label = QtWidgets.QLabel("-")

        for label, field, btn, skin_label in (
                ("Source", self.src_field, src_btn, self.src_skin_label),
                ("Target", self.tgt_field, tgt_btn, self.tgt_skin_label)):
            box = QtWidgets.QGroupBox(label)
            grid = QtWidgets.QGridLayout(box)
            grid.setContentsMargins(6, 4, 6, 4)
            grid.setVerticalSpacing(2)
            grid.addWidget(field, 0, 0)
            grid.addWidget(btn, 0, 1)
            grid.addWidget(skin_label, 1, 0, 1, 2)
            grid.setColumnStretch(0, 1)
            row.addWidget(box, 1)
        return row

    def _build_action_row(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()

        row.addWidget(QtWidgets.QLabel("Vertex correspondence"))
        self.vertex_combo = QtWidgets.QComboBox()
        self.vertex_combo.addItems(smc.VERTEX_MODES)
        self.vertex_combo.setToolTip(
            "How each TARGET vertex finds its source vertex - the topology "
            "axis, independent of the influence mapping.\n"
            "index: same vertex order, exact. Requires equal counts.\n"
            "closestPoint: closest point on the source surface, then the "
            "nearest vertex of that face. Exact when the target is the source "
            "with points removed.\n"
            "closestVertex: nearest source vertex outright.")
        self.vertex_combo.currentIndexChanged.connect(self._invalidate_vertex_map)
        row.addWidget(self.vertex_combo)

        self.add_inf_chk = QtWidgets.QCheckBox("Add missing influences")
        self.add_inf_chk.setChecked(True)
        self.add_inf_chk.setToolTip(
            "Add mapped joints that are not yet influences of the target "
            "skinCluster. Without it the transfer refuses rather than dropping "
            "those columns.")
        row.addWidget(self.add_inf_chk)

        self.normalize_chk = QtWidgets.QCheckBox("Normalize")
        self.normalize_chk.setChecked(True)
        self.normalize_chk.setToolTip(
            "Normalise each vertex row on write. With unmatched influences "
            "carrying weight, this rescales what is left to sum to 1.")
        row.addWidget(self.normalize_chk)

        row.addStretch(1)

        self.analyze_btn = QtWidgets.QPushButton("Analyze")
        self.analyze_btn.setToolTip(
            "Compute the weight mass at risk for the current mapping. "
            "Writes nothing.")
        self.analyze_btn.clicked.connect(self._on_analyze)
        row.addWidget(self.analyze_btn)

        self.transfer_btn = QtWidgets.QPushButton("Transfer")
        self.transfer_btn.setToolTip("Write the weights onto the target.")
        self.transfer_btn.clicked.connect(self._on_transfer)
        row.addWidget(self.transfer_btn)

        self.verify_btn = QtWidgets.QPushButton("Verify")
        self.verify_btn.setToolTip(
            "Compare the target's weights against the source's, through the "
            "mapping. Run after a transfer.")
        self.verify_btn.clicked.connect(self._on_verify)
        row.addWidget(self.verify_btn)
        return row

    # -- Mesh pickers -----------------------------------------------------

    def _selected_mesh(self) -> Optional[str]:
        sel = cmds.ls(selection=True, long=True) or []
        if not sel:
            cmds.warning("SkinMatch: select a mesh first.")
            return None
        return sel[0]

    def _on_pick_source(self) -> None:
        mesh = self._selected_mesh()
        if not mesh:
            return
        self.src_field.setText(mesh)
        self._src_skin = smc.find_skin_cluster(mesh)
        self._set_skin_label(self.src_skin_label, self._src_skin, mesh)
        self._invalidate_vertex_map()
        self._reload_influences()

    def _on_pick_target(self) -> None:
        mesh = self._selected_mesh()
        if not mesh:
            return
        self.tgt_field.setText(mesh)
        self._tgt_skin = smc.find_skin_cluster(mesh)
        self._set_skin_label(self.tgt_skin_label, self._tgt_skin, mesh)
        self._invalidate_vertex_map()
        self._reload_influences()

    def _set_skin_label(self, label, skin: Optional[str], mesh: str) -> None:
        if skin:
            n = smc.vertex_count(mesh)
            label.setText(f"{skin}  -  {n} verts")
            label.setStyleSheet(_OK_COLOR)
        else:
            label.setText("no skinCluster found")
            label.setStyleSheet(_BAD_COLOR)

    def _reload_influences(self) -> None:
        """Refill both lists. The target falls back to scene joints."""
        source = smc.list_influences(self._src_skin) if self._src_skin else []
        if self._tgt_skin:
            target = smc.list_influences(self._tgt_skin)
        else:
            # No target skinCluster yet - offer the scene's joints so a mapping
            # can still be authored before the bind exists.
            target = cmds.ls(type="joint") or []
        self.match_panel.set_influences(source, target)

    # -- Actions ----------------------------------------------------------

    def _invalidate_vertex_map(self) -> None:
        self._vertex_map = None

    def _on_mapping_changed(self) -> None:
        self.report_panel.clear_verify()

    def _ready(self) -> bool:
        if not self._src_skin:
            self._fail("Pick a source mesh carrying a skinCluster.")
            return False
        if not self._tgt_skin:
            self._fail("Pick a target mesh carrying a skinCluster.")
            return False
        return True

    def _ensure_vertex_map(self) -> bool:
        if self._vertex_map is not None:
            return True
        vertex_map, err = smc.build_vertex_map(
            self.src_field.text(), self.tgt_field.text(),
            self.vertex_combo.currentText())
        if err:
            self._fail(err)
            return False
        self._vertex_map = vertex_map
        return True

    def _on_analyze(self) -> None:
        if not self._src_skin:
            self._fail("Pick a source mesh carrying a skinCluster.")
            return
        report = smc.match_report(self._src_skin,
                                  self.src_field.text(),
                                  self.match_panel.source_names(),
                                  self.match_panel.get_mapping())
        self.report_panel.set_report(report)
        self._ok(f"Analyzed - {report['at_risk_pct']:.3f}% of the weight mass "
                 f"has nowhere to go.")

    def _on_transfer(self) -> None:
        if not self._ready() or not self._ensure_vertex_map():
            return

        mapping = self.match_panel.get_mapping()
        report = smc.match_report(self._src_skin, self.src_field.text(),
                                  self.match_panel.source_names(), mapping)
        self.report_panel.set_report(report)

        if report["at_risk_pct"] > 1e-6:
            answer = QtWidgets.QMessageBox.warning(
                self, "Transfer",
                f"{report['at_risk_pct']:.3f}% of the source's weight sits on "
                f"unmatched influences and will be lost.\n\nTransfer anyway?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No)
            if answer != QtWidgets.QMessageBox.Yes:
                self._fail("Transfer cancelled.")
                return

        ok, message = smc.transfer_weights(
            self._src_skin, self.src_field.text(),
            self._tgt_skin, self.tgt_field.text(),
            mapping,
            vertex_map=self._vertex_map,
            add_missing_influences=self.add_inf_chk.isChecked(),
            normalize=self.normalize_chk.isChecked())

        if not ok:
            self._fail(message)
            return
        self._ok(message)
        # Influences may have been added - keep the target list truthful.
        self._reload_influences()
        self.match_panel.set_mapping(mapping,
                                     self.match_panel.source_rule(),
                                     self.match_panel.target_rule())

    def _on_verify(self) -> None:
        if not self._ready() or not self._ensure_vertex_map():
            return
        result = smc.verify_transfer(
            self._src_skin, self.src_field.text(),
            self._tgt_skin, self.tgt_field.text(),
            self.match_panel.get_mapping(), self._vertex_map)
        self.report_panel.set_verify(result)
        self._ok(f"Verified - {result['dominant_changed']} vertices "
                 f"({result['dominant_changed_pct']:.3f}%) changed dominant "
                 f"influence.")

    # -- Mapping I/O ------------------------------------------------------

    def _on_save_mapping(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save mapping", "", "JSON (*.json)")
        if not path:
            return
        if smc.save_mapping(path, self.match_panel.get_mapping(),
                            self.match_panel.source_rule(),
                            self.match_panel.target_rule()):
            self._ok(f"Saved mapping to '{path}'.")
        else:
            self._fail("Failed to save - see the script editor.")

    def _on_load_mapping(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load mapping", "", "JSON (*.json)")
        if not path:
            return
        mapping, src_rule, tgt_rule = smc.load_mapping(path)
        if not mapping:
            self._fail("Nothing loaded - see the script editor.")
            return
        self.match_panel.set_mapping(mapping, src_rule, tgt_rule)
        self._ok(f"Loaded {len(mapping)} pairs from '{path}'.")

    # -- Status -----------------------------------------------------------

    def _ok(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet(_OK_COLOR)

    def _fail(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet(_BAD_COLOR)


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

def _maya_main_window():
    """Return Maya's main window as a QWidget, or None outside Maya."""
    try:
        import maya.OpenMayaUI as omui
    except ImportError:
        return None
    ptr = omui.MQtUtil.mainWindow()
    if ptr is None:
        return None
    return wrapInstance(int(ptr), QtWidgets.QWidget)


def launch():
    """Create (or re-show) the SkinMatch window, parented to Maya."""
    global _window
    if _window is not None:
        try:
            _window.close()
            _window.deleteLater()
        except Exception:
            pass
        _window = None

    _window = SkinMatchUI(parent=_maya_main_window())
    _window.show()
    return _window