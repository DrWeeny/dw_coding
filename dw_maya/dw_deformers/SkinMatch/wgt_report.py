"""
wgt_report.py - what a mapping would cost, and what it actually cost.

Two blocks, deliberately kept apart because they answer different questions:

*Before* - the weight MASS sitting on unmatched source influences. Unmatched
count on its own is noise: a rig full of unused twist joints can go unmatched
for free. Mass is what decides whether a remap is lossless.

*After* - the weights are compared directly rather than the deformation, since
at the bind pose every weighting reproduces the rest shape and a positional
check would pass regardless. ``dominant changed`` is the headline: an L1 of 0.02
smeared over eight influences is invisible, one flipped dominant influence is a
visible artefact.
"""

from __future__ import annotations

from typing import Dict

from dw_maya.dw_deformers.SkinMatch.compat import QtWidgets


_OK_COLOR   = "#6cb06c"
_WARN_COLOR = "#d89b3a"
_BAD_COLOR  = "#d86a6a"


class ReportPanel(QtWidgets.QWidget):
    """Pre-transfer risk figure + post-transfer fidelity figures."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # -- Before --------------------------------------------------------
        risk_box = QtWidgets.QGroupBox("Before transfer")
        rv = QtWidgets.QVBoxLayout(risk_box)
        rv.setContentsMargins(8, 6, 8, 6)
        rv.setSpacing(4)

        self.risk_label = QtWidgets.QLabel("No mapping yet.")
        font = self.risk_label.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        self.risk_label.setFont(font)
        self.risk_label.setToolTip(
            "Share of the source's total weight sitting on influences that "
            "have no target.\n"
            "0% means the mapping is lossless no matter how many influences "
            "went unmatched.")
        rv.addWidget(self.risk_label)

        self.counts_label = QtWidgets.QLabel("")
        rv.addWidget(self.counts_label)

        self.unmatched_tree = QtWidgets.QTreeWidget()
        self.unmatched_tree.setHeaderLabels(["Unmatched influence",
                                             "Weight mass", "% of total"])
        self.unmatched_tree.setRootIsDecorated(False)
        self.unmatched_tree.setAlternatingRowColors(True)
        self.unmatched_tree.setUniformRowHeights(True)
        self.unmatched_tree.setToolTip(
            "Only unmatched influences that actually carry weight, worst "
            "first. These are the weights that would be lost.")
        self.unmatched_tree.header().setStretchLastSection(True)
        rv.addWidget(self.unmatched_tree)
        outer.addWidget(risk_box, 1)

        # -- After ---------------------------------------------------------
        verify_box = QtWidgets.QGroupBox("After transfer")
        vv = QtWidgets.QGridLayout(verify_box)
        vv.setContentsMargins(8, 6, 8, 6)
        vv.setVerticalSpacing(3)

        self.dominant_label = QtWidgets.QLabel("-")
        dfont = self.dominant_label.font()
        dfont.setBold(True)
        self.dominant_label.setFont(dfont)
        self.mean_l1_label = QtWidgets.QLabel("-")
        self.max_l1_label = QtWidgets.QLabel("-")
        self.verts_label = QtWidgets.QLabel("-")

        rows = (
            ("Dominant influence changed", self.dominant_label,
             "Vertices whose strongest influence is not the one the mapping "
             "says it should be. This is the visible failure."),
            ("Mean L1 per vertex", self.mean_l1_label,
             "Average summed absolute weight difference per vertex."),
            ("Max L1", self.max_l1_label,
             "Worst single vertex."),
            ("Vertices compared", self.verts_label, ""),
        )
        for row, (text, widget, tip) in enumerate(rows):
            label = QtWidgets.QLabel(text)
            label.setToolTip(tip)
            widget.setToolTip(tip)
            vv.addWidget(label, row, 0)
            vv.addWidget(widget, row, 1)
        vv.setColumnStretch(1, 1)
        outer.addWidget(verify_box)

    # -- Public API -------------------------------------------------------

    def set_report(self, report: Dict) -> None:
        """Show a :func:`skin_match_cmds.match_report` result."""
        pct = report["at_risk_pct"]
        color = _OK_COLOR if pct < 1e-6 else (
            _WARN_COLOR if pct < 1.0 else _BAD_COLOR)
        self.risk_label.setText(f"Weight mass at risk: {pct:.3f}%")
        self.risk_label.setStyleSheet(f"QLabel {{ color: {color}; }}")

        matched = len(report["matched"])
        unmatched = len(report["unmatched"])
        self.counts_label.setText(
            f"{matched} matched, {unmatched} unmatched "
            f"({len(report['unmatched_detail'])} of them carry weight)")

        total = report["total_mass"] or 1.0
        self.unmatched_tree.clear()
        for name, mass in report["unmatched_detail"]:
            item = QtWidgets.QTreeWidgetItem(
                [name, f"{mass:.4f}", f"{mass / total * 100.0:.3f}%"])
            self.unmatched_tree.addTopLevelItem(item)
        self.unmatched_tree.resizeColumnToContents(0)

    def set_verify(self, result: Dict) -> None:
        """Show a :func:`skin_match_cmds.verify_transfer` result."""
        changed = result["dominant_changed"]
        pct = result["dominant_changed_pct"]
        color = _OK_COLOR if changed == 0 else (
            _WARN_COLOR if pct < 1.0 else _BAD_COLOR)
        self.dominant_label.setText(f"{changed}  ({pct:.3f}%)")
        self.dominant_label.setStyleSheet(f"QLabel {{ color: {color}; }}")

        self.mean_l1_label.setText(f"{result['mean_l1']:.6f}")
        self.max_l1_label.setText(f"{result['max_l1']:.6f}")
        self.verts_label.setText(str(result["vertices"]))

    def clear_verify(self) -> None:
        """Blank the after-transfer block (a new mapping invalidates it)."""
        for label in (self.dominant_label, self.mean_l1_label,
                      self.max_l1_label, self.verts_label):
            label.setText("-")
            label.setStyleSheet("")