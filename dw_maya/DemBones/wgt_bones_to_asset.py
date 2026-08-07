"""
wgt_bones_to_asset.py - "Solve -> Asset": send a solve's joints back to the asset.

Deliberately shaped as a task, not as a panel of options. DemBones inverts the
pipeline (``model -> sim -> solve -> rig -> anim``), so the joints are born in
simulation space and rigging needs them in asset space. That is one job with one
decision - which two meshes - and everything else is derived from the scene.

So the window is built around two lists that are usually hidden inside a tool's
head:

*Checks*  - every precondition that silently ruins this transfer, with the
            reason attached. Run before anything is created.
*Steps*   - the six things the build actually does, updating live so a long
            bake is visible rather than a frozen window.

The regime (rigid / topology / uv) is REPORTED, never asked. Picking it is a
consequence of what the two meshes are, and an artist guessing at it is exactly
the class of silent mistake this tool exists to remove. The override lives in
Advanced for the day it is needed.

Launch::

    from dw_maya.DemBones import wgt_bones_to_asset
    wgt_bones_to_asset.launch()
"""

from __future__ import annotations

from typing import Optional

import maya.cmds as cmds

from dw_maya.DemBones.compat import QtGui, QtWidgets, Qt, wrapInstance
import dw_maya.DemBones.bones_to_asset as b2a

_window = None

_STATUS_COLOR = {
    "ok":   "#6cb06c",
    "warn": "#d89b3a",
    "fail": "#d86a6a",
    "run":  "#6cc0c0",
    "skip": "#8a8a8a",
}
_STATUS_MARK = {
    "ok": "OK", "warn": "!", "fail": "X", "run": "...", "skip": "-",
}

_REGIME_BLURB = {
    "rigid": "The two meshes differ by a pure move. One matrix places every "
             "joint exactly and the animation is relinked, not baked.",
    "topology": "Same topology, non-rigid difference - the mesh was relaxed "
                "before caching, or the first frame is a pose. Each joint is "
                "re-anchored to the same triangle by vertex index, and the "
                "animation is baked.",
    "uv": "Vertex counts differ, so point order is gone and the correspondence "
          "has to cross through UV space. Least reliable regime - check the "
          "result before trusting it.",
}


class BonesToAssetUI(QtWidgets.QMainWindow):
    """Solve -> Asset: joints, skin and animation, in asset space."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("BonesToAssetUI")
        self.setWindowTitle("Solve -> Asset  (DemBones return leg)")
        self.resize(760, 720)
        self._build_ui()

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        outer.addWidget(self._build_intro())
        outer.addWidget(self._build_meshes())
        outer.addWidget(self._build_regime())
        outer.addWidget(self._build_checks(), 1)
        outer.addWidget(self._build_steps(), 1)
        outer.addWidget(self._build_advanced())
        outer.addLayout(self._build_actions())

        self.status_label = QtWidgets.QLabel(
            "Pick the solved mesh and the asset mesh, then Check.")
        outer.addWidget(self.status_label)

    def _build_intro(self) -> QtWidgets.QWidget:
        label = QtWidgets.QLabel(
            "DemBones runs before rigging, so the solved joints live in "
            "SIMULATION space. This builds them fresh in ASSET space, binds "
            "the asset mesh to them, and carries the animation across.")
        label.setWordWrap(True)
        label.setStyleSheet("QLabel { color: #9a9a9a; }")
        return label

    def _build_meshes(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Meshes")
        grid = QtWidgets.QGridLayout(box)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setVerticalSpacing(3)

        self.src_field = QtWidgets.QLineEdit()
        self.src_field.setReadOnly(True)
        self.src_field.setPlaceholderText("the solved / simulated mesh")
        src_btn = QtWidgets.QPushButton("<< Set")
        src_btn.clicked.connect(self._on_pick_source)
        self.src_info = QtWidgets.QLabel("-")
        self.src_info.setStyleSheet("QLabel { color: #8a8a8a; }")

        self.tgt_field = QtWidgets.QLineEdit()
        self.tgt_field.setReadOnly(True)
        self.tgt_field.setPlaceholderText("the asset mesh, in asset space")
        tgt_btn = QtWidgets.QPushButton("<< Set")
        tgt_btn.clicked.connect(self._on_pick_target)
        self.tgt_info = QtWidgets.QLabel("-")
        self.tgt_info.setStyleSheet("QLabel { color: #8a8a8a; }")

        grid.addWidget(QtWidgets.QLabel("Solved mesh"), 0, 0)
        grid.addWidget(self.src_field, 0, 1)
        grid.addWidget(src_btn, 0, 2)
        grid.addWidget(self.src_info, 1, 1, 1, 2)
        grid.addWidget(QtWidgets.QLabel("Asset mesh"), 2, 0)
        grid.addWidget(self.tgt_field, 2, 1)
        grid.addWidget(tgt_btn, 2, 2)
        grid.addWidget(self.tgt_info, 3, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        return box

    def _build_regime(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Regime")
        v = QtWidgets.QVBoxLayout(box)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(2)

        self.regime_label = QtWidgets.QLabel("not checked yet")
        font = self.regime_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self.regime_label.setFont(font)
        v.addWidget(self.regime_label)

        self.regime_detail = QtWidgets.QLabel(
            "Press Check - the regime is measured from the two meshes, not "
            "chosen.")
        self.regime_detail.setWordWrap(True)
        self.regime_detail.setStyleSheet("QLabel { color: #9a9a9a; }")
        v.addWidget(self.regime_detail)
        return box

    def _build_checks(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Checks")
        v = QtWidgets.QVBoxLayout(box)
        v.setContentsMargins(8, 6, 8, 6)

        self.checks_tree = QtWidgets.QTreeWidget()
        self.checks_tree.setHeaderLabels(["", "Check", "Detail"])
        self.checks_tree.setRootIsDecorated(False)
        self.checks_tree.setAlternatingRowColors(True)
        self.checks_tree.setUniformRowHeights(True)
        self.checks_tree.setToolTip(
            "Preconditions that fail silently if nobody looks. Hover a row for "
            "why it matters.")
        self.checks_tree.header().setStretchLastSection(True)
        self.checks_tree.setColumnWidth(0, 34)
        v.addWidget(self.checks_tree)
        return box

    def _build_steps(self) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox("Steps")
        v = QtWidgets.QVBoxLayout(box)
        v.setContentsMargins(8, 6, 8, 6)

        self.steps_tree = QtWidgets.QTreeWidget()
        self.steps_tree.setHeaderLabels(["", "Step", "Result"])
        self.steps_tree.setRootIsDecorated(False)
        self.steps_tree.setAlternatingRowColors(True)
        self.steps_tree.setUniformRowHeights(True)
        self.steps_tree.header().setStretchLastSection(True)
        self.steps_tree.setColumnWidth(0, 34)
        v.addWidget(self.steps_tree)
        self._reset_steps()
        return box

    def _build_advanced(self) -> QtWidgets.QWidget:
        self.adv_toggle = QtWidgets.QToolButton()
        self.adv_toggle.setText("Advanced")
        self.adv_toggle.setCheckable(True)
        self.adv_toggle.setAutoRaise(True)
        self.adv_toggle.setArrowType(Qt.RightArrow)
        self.adv_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.adv_toggle.toggled.connect(self._toggle_advanced)

        self._adv = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(self._adv)
        grid.setContentsMargins(12, 2, 0, 0)
        grid.setVerticalSpacing(3)

        self.prefix_field = QtWidgets.QLineEdit("assetBone")
        self.max_inf_spin = QtWidgets.QSpinBox()
        self.max_inf_spin.setRange(1, 32)
        self.max_inf_spin.setValue(8)
        self.max_inf_spin.setToolTip(
            "Match the solve's nnz. A narrower cap prunes the incoming "
            "weights on arrival.")
        self.anim_combo = QtWidgets.QComboBox()
        self.anim_combo.addItems(b2a.ANIM_MODES)
        self.anim_combo.setToolTip(
            "auto: relink when rigid, bake otherwise.\n"
            "relink is exact but only correct for a rigid difference; bake is "
            "the right retarget once joints have moved non-rigidly.")
        self.replace_chk = QtWidgets.QCheckBox(
            "Replace an existing skinCluster on the asset")
        self.replace_chk.setToolTip(
            "Without this, binding an already-skinned asset would stack a "
            "second skinCluster, so the build refuses instead.")

        rows = (("Joint prefix", self.prefix_field),
                ("Max influences", self.max_inf_spin),
                ("Animation", self.anim_combo))
        for row, (text, widget) in enumerate(rows):
            grid.addWidget(QtWidgets.QLabel(text), row, 0)
            grid.addWidget(widget, row, 1)
        grid.addWidget(self.replace_chk, len(rows), 0, 1, 2)
        grid.setColumnStretch(1, 1)
        self._adv.setVisible(False)

        holder = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        v.addWidget(self.adv_toggle)
        v.addWidget(self._adv)
        return holder

    def _build_actions(self) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        self.check_btn = QtWidgets.QPushButton("Check")
        self.check_btn.setToolTip("Measure the regime and run every "
                                  "precondition. Creates nothing.")
        self.check_btn.clicked.connect(self.run_checks)
        self.build_btn = QtWidgets.QPushButton("Build")
        self.build_btn.setToolTip("Create the joints, bind the asset, copy the "
                                  "weights and carry the animation.")
        self.build_btn.clicked.connect(self.build)
        row.addWidget(self.check_btn)
        row.addWidget(self.build_btn)
        return row

    def _toggle_advanced(self, on: bool) -> None:
        self.adv_toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self._adv.setVisible(on)

    # -- Pickers ----------------------------------------------------------

    def _selected(self) -> Optional[str]:
        sel = cmds.ls(selection=True, long=True) or []
        if not sel:
            cmds.warning("Solve -> Asset: select a mesh first.")
            return None
        return sel[0]

    def _on_pick_source(self) -> None:
        mesh = self._selected()
        if not mesh:
            return
        self.src_field.setText(mesh)
        skin = b2a.dem_cmds.find_skin_cluster(mesh)
        count = b2a.dem_cmds.mesh_vertex_count(mesh) or 0
        self.src_info.setText(
            f"{skin or 'no skinCluster'}  -  {count} verts")

    def _on_pick_target(self) -> None:
        mesh = self._selected()
        if not mesh:
            return
        self.tgt_field.setText(mesh)
        count = b2a.dem_cmds.mesh_vertex_count(mesh) or 0
        skin = b2a.dem_cmds.find_skin_cluster(mesh)
        self.tgt_info.setText(
            f"{count} verts" + (f"  -  already skinned ({skin})" if skin else ""))

    # -- Checks -----------------------------------------------------------

    def run_checks(self) -> bool:
        """Populate the regime banner and the checks list. Creates nothing."""
        source, target = self.src_field.text(), self.tgt_field.text()
        if not source or not target:
            self._fail("Pick both meshes first.")
            return False

        regime = b2a.classify(source, target)
        name = regime["regime"]
        color = {"rigid": "#6cb06c", "topology": "#d89b3a",
                 "uv": "#d86a6a"}.get(name, "#9a9a9a")
        self.regime_label.setText(name.upper())
        self.regime_label.setStyleSheet(f"QLabel {{ color: {color}; }}")
        self.regime_detail.setText(_REGIME_BLURB.get(name, regime["detail"]))

        checks = b2a.preflight(source, target, self.max_inf_spin.value())
        self.checks_tree.clear()
        blocking = 0
        warnings = 0
        for check in checks:
            item = QtWidgets.QTreeWidgetItem(
                [_STATUS_MARK.get(check["status"], "?"),
                 check["label"], check["detail"]])
            self._tint(item, _STATUS_COLOR.get(check["status"], "#9a9a9a"))
            tip = check["tip"] or check["detail"]
            for col in range(3):
                item.setToolTip(col, tip)
            self.checks_tree.addTopLevelItem(item)
            if check["status"] == "fail":
                blocking += 1
            elif check["status"] == "warn":
                warnings += 1
        self.checks_tree.resizeColumnToContents(1)

        self._reset_steps()
        if blocking:
            self._fail(f"{blocking} blocking problem(s) - hover the red rows.")
            return False
        self._ok(f"Ready. {warnings} warning(s) - hover the orange rows.")
        return True

    # -- Build ------------------------------------------------------------

    def build(self) -> None:
        if not self.run_checks():
            return

        self.build_btn.setEnabled(False)
        try:
            report = b2a.bones_to_asset(
                self.src_field.text(),
                self.tgt_field.text(),
                anim_mode=self.anim_combo.currentText(),
                joint_prefix=self.prefix_field.text() or "assetBone",
                max_influences=self.max_inf_spin.value(),
                replace_existing=self.replace_chk.isChecked(),
                progress=self._on_step)
        finally:
            self.build_btn.setEnabled(True)

        if report["ok"]:
            self._ok(f"Built '{report['skin']}' with "
                     f"{len(report['joints'])} joints.")
        else:
            self._fail(report["detail"] or "Build failed - see the steps.")

        if report["failed"]:
            cmds.warning(f"Solve -> Asset: {len(report['failed'])} joints "
                         f"could not be placed: {report['failed'][:5]}")

    def _on_step(self, index: int, status: str, detail: str = "") -> None:
        """Progress callback - update one step row and repaint immediately."""
        item = self.steps_tree.topLevelItem(index)
        if item is None:
            return
        item.setText(0, _STATUS_MARK.get(status, "?"))
        if detail:
            item.setText(2, detail)
        self._tint(item, _STATUS_COLOR.get(status, "#9a9a9a"))
        # A bake blocks the event loop; without this the window looks frozen.
        QtWidgets.QApplication.processEvents()

    def _reset_steps(self) -> None:
        self.steps_tree.clear()
        for index, name in enumerate(b2a.STEPS):
            item = QtWidgets.QTreeWidgetItem(["", f"{index + 1}. {name}", ""])
            self._tint(item, "#8a8a8a")
            self.steps_tree.addTopLevelItem(item)
        self.steps_tree.resizeColumnToContents(1)

    # -- Helpers ----------------------------------------------------------

    def _tint(self, item, color: str) -> None:
        brush = QtGui.QBrush(QtGui.QColor(color))
        for col in range(item.columnCount()):
            item.setForeground(col, brush)

    def _ok(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet("QLabel { color: #6cb06c; }")

    def _fail(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_label.setStyleSheet("QLabel { color: #d86a6a; }")


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


def launch(parent=None):
    """Create (or re-show) the Solve -> Asset window.

    Args:
        parent: Owning widget. Defaults to Maya's main window, so the tool also
            opens standalone rather than only from the DemBones Tools menu.
    """
    global _window
    if _window is not None:
        try:
            _window.close()
            _window.deleteLater()
        except Exception:
            pass
        _window = None

    _window = BonesToAssetUI(parent=parent or _maya_main_window())
    _window.show()
    return _window