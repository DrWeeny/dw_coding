"""
wgt_influence_match.py - side-by-side influence matching panel.

Two trees, one per skeleton, each showing the influence name next to the KEY it
normalises to. The key column is the point of the panel: a regex rule is only
trustworthy if you can see what it did before you match on it.

Pairing state is shown on both sides at once - the source row carries the target
it feeds, the target row carries the source that claims it - so an influence
that quietly went unmatched is visible without cross-referencing two lists.

Manual pairs are LOCKED: re-running Auto-match preserves them instead of
overwriting the hand corrections that were the reason to re-run it.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import maya.cmds as cmds

from dw_maya.dw_deformers.SkinMatch.compat import QtGui, QtWidgets, Signal
import dw_maya.dw_deformers.SkinMatch.skin_match_cmds as smc


_UNMATCHED_COLOR = "#d89b3a"    # orange - carries weight, goes nowhere
_LOCKED_COLOR    = "#6cc0c0"    # teal   - hand paired
_AMBIGUOUS_COLOR = "#d86a6a"    # red    - key hit several free targets


class InfluenceMatchPanel(QtWidgets.QWidget):
    """Source/target influence lists with per-side regex normalisation."""

    mapping_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._source_names: List[str] = []
        self._target_names: List[str] = []
        self._mapping: Dict[str, str] = {}
        self._locked: Dict[str, str] = {}
        self._ambiguous: List[str] = []
        self._build_ui()

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.src_tree, src_box = self._make_side(
            "Source influences", "-> Target",
            "Influences of the source skinCluster, in weight-column order.")
        self.tgt_tree, tgt_box = self._make_side(
            "Target influences", "<- Source",
            "Influences of the target skinCluster.\n"
            "Joints not yet influencing the target are added on transfer.")

        # Source rule widgets were stashed on the box by _make_side.
        self.src_preset, self.src_pattern, self.src_replace, self.src_filter = \
            src_box.rule_widgets
        self.tgt_preset, self.tgt_pattern, self.tgt_replace, self.tgt_filter = \
            tgt_box.rule_widgets

        for widget in (self.src_pattern, self.src_replace,
                       self.tgt_pattern, self.tgt_replace):
            widget.textChanged.connect(self._refresh_keys)
        self.src_filter.textChanged.connect(self._apply_filters)
        self.tgt_filter.textChanged.connect(self._apply_filters)
        self.src_preset.currentIndexChanged.connect(self._on_src_preset)
        self.tgt_preset.currentIndexChanged.connect(self._on_tgt_preset)

        outer.addWidget(src_box, 1)
        outer.addLayout(self._make_middle())
        outer.addWidget(tgt_box, 1)

    def _make_side(self,
                   title: str,
                   pair_column: str,
                   tip: str,
                   ) -> Tuple[QtWidgets.QTreeWidget, QtWidgets.QGroupBox]:
        """Build one side: rule row, filter, tree. Returns (tree, box)."""
        box = QtWidgets.QGroupBox(title)
        v = QtWidgets.QVBoxLayout(box)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(3)

        rule_row = QtWidgets.QHBoxLayout()
        preset = QtWidgets.QComboBox()
        for label, _, _ in smc.RULE_PRESETS:
            preset.addItem(label)
        preset.setToolTip("Common normalisations. Picking one fills the two "
                          "fields, which stay editable.")
        pattern = QtWidgets.QLineEdit()
        pattern.setPlaceholderText("regex (empty = name as-is)")
        pattern.setToolTip(
            "Regex searched for in each name. The result is the match KEY - "
            "both sides are matched on key equality.\n"
            "Errors are shown live and leave the names untouched.")
        replace = QtWidgets.QLineEdit()
        replace.setPlaceholderText("replace")
        replace.setFixedWidth(70)
        replace.setToolTip("What each match becomes (usually empty).")
        rule_row.addWidget(preset)
        rule_row.addWidget(pattern, 1)
        rule_row.addWidget(replace)
        v.addLayout(rule_row)

        filter_field = QtWidgets.QLineEdit()
        filter_field.setPlaceholderText("filter...")
        filter_field.setClearButtonEnabled(True)
        v.addWidget(filter_field)

        tree = QtWidgets.QTreeWidget()
        tree.setHeaderLabels(["Influence", "Key", pair_column])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        tree.setToolTip(tip)
        tree.header().setStretchLastSection(True)
        v.addWidget(tree)

        box.rule_widgets = (preset, pattern, replace, filter_field)
        return tree, box

    def _make_middle(self) -> QtWidgets.QVBoxLayout:
        col = QtWidgets.QVBoxLayout()
        col.addStretch(1)

        self.auto_btn = QtWidgets.QPushButton("Auto-match")
        self.auto_btn.setToolTip(
            "Match on normalised keys, one-to-one.\n"
            "Hand-paired rows are preserved.")
        self.auto_btn.clicked.connect(self.auto_match)

        self.pair_btn = QtWidgets.QPushButton("Pair >")
        self.pair_btn.setToolTip(
            "Pair the selected source row with the selected target row.\n"
            "The pair is locked - Auto-match will not overwrite it.")
        self.pair_btn.clicked.connect(self.pair_selected)

        self.unpair_btn = QtWidgets.QPushButton("Unpair")
        self.unpair_btn.setToolTip("Drop the selected rows' pairing.")
        self.unpair_btn.clicked.connect(self.unpair_selected)

        self.clear_btn = QtWidgets.QPushButton("Clear all")
        self.clear_btn.setToolTip("Drop every pair, including hand-paired ones.")
        self.clear_btn.clicked.connect(self.clear_mapping)

        for btn in (self.auto_btn, self.pair_btn, self.unpair_btn,
                    self.clear_btn):
            btn.setFixedWidth(90)
            col.addWidget(btn)
        col.addStretch(1)
        return col

    # -- Population -------------------------------------------------------

    def set_influences(self,
                       source_names: List[str],
                       target_names: List[str],
                       ) -> None:
        """Replace both lists, dropping pairs that no longer resolve."""
        self._source_names = list(source_names)
        self._target_names = list(target_names)

        valid = set(self._source_names)
        valid_t = set(self._target_names)
        self._mapping = {s: t for s, t in self._mapping.items()
                         if s in valid and t in valid_t}
        self._locked = {s: t for s, t in self._locked.items()
                        if s in valid and t in valid_t}
        self._ambiguous = []
        self._rebuild()

    def _rebuild(self) -> None:
        """Rebuild both trees from the current names + mapping."""
        src_keys, src_err = smc.apply_rule(self._source_names,
                                           *self.source_rule())
        tgt_keys, tgt_err = smc.apply_rule(self._target_names,
                                           *self.target_rule())
        self._set_error(self.src_pattern, src_err)
        self._set_error(self.tgt_pattern, tgt_err)

        reverse = {t: s for s, t in self._mapping.items()}

        self.src_tree.clear()
        for name, key in zip(self._source_names, src_keys):
            target = self._mapping.get(name, "")
            item = QtWidgets.QTreeWidgetItem([name, key, target])
            if name in self._ambiguous:
                self._tint(item, _AMBIGUOUS_COLOR)
                item.setText(2, "ambiguous - pair by hand")
            elif not target:
                self._tint(item, _UNMATCHED_COLOR)
            elif name in self._locked:
                self._tint(item, _LOCKED_COLOR)
            self.src_tree.addTopLevelItem(item)

        self.tgt_tree.clear()
        for name, key in zip(self._target_names, tgt_keys):
            source = reverse.get(name, "")
            item = QtWidgets.QTreeWidgetItem([name, key, source])
            if not source:
                self._tint(item, _UNMATCHED_COLOR)
            elif source in self._locked:
                self._tint(item, _LOCKED_COLOR)
            self.tgt_tree.addTopLevelItem(item)

        for tree in (self.src_tree, self.tgt_tree):
            tree.resizeColumnToContents(0)
            tree.resizeColumnToContents(1)

        self._apply_filters()
        self.mapping_changed.emit()

    def _tint(self, item, color: str) -> None:
        brush = QtGui.QBrush(QtGui.QColor(color))
        for col in range(item.columnCount()):
            item.setForeground(col, brush)

    def _set_error(self, field, error: Optional[str]) -> None:
        field.setStyleSheet("" if not error
                            else "QLineEdit { border: 1px solid #d86a6a; }")
        field.setToolTip(error or "")

    def _apply_filters(self) -> None:
        for tree, field in ((self.src_tree, self.src_filter),
                            (self.tgt_tree, self.tgt_filter)):
            needle = field.text().lower()
            for i in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(i)
                item.setHidden(bool(needle) and needle not in
                               item.text(0).lower())

    # -- Rules ------------------------------------------------------------

    def source_rule(self) -> Tuple[str, str]:
        return self.src_pattern.text(), self.src_replace.text()

    def target_rule(self) -> Tuple[str, str]:
        return self.tgt_pattern.text(), self.tgt_replace.text()

    def _on_src_preset(self, index: int) -> None:
        _, pattern, replace = smc.RULE_PRESETS[index]
        self.src_pattern.setText(pattern)
        self.src_replace.setText(replace)

    def _on_tgt_preset(self, index: int) -> None:
        _, pattern, replace = smc.RULE_PRESETS[index]
        self.tgt_pattern.setText(pattern)
        self.tgt_replace.setText(replace)

    def _refresh_keys(self) -> None:
        self._rebuild()

    # -- Pairing ----------------------------------------------------------

    def auto_match(self) -> None:
        """Rule-match everything, keeping the hand-paired rows."""
        self._mapping, self._ambiguous = smc.auto_match(
            self._source_names,
            self._target_names,
            src_rule=self.source_rule(),
            tgt_rule=self.target_rule(),
            locked=self._locked)
        self._rebuild()

    def pair_selected(self) -> None:
        """Lock a pair from the selected row on each side."""
        src_items = self.src_tree.selectedItems()
        tgt_items = self.tgt_tree.selectedItems()
        if len(src_items) != 1 or len(tgt_items) != 1:
            cmds.warning("SkinMatch: select exactly one row on each side.")
            return

        source = src_items[0].text(0)
        target = tgt_items[0].text(0)

        # One-to-one: free whoever held either end.
        for s, t in list(self._mapping.items()):
            if t == target or s == source:
                self._mapping.pop(s, None)
                self._locked.pop(s, None)

        self._mapping[source] = target
        self._locked[source] = target
        if source in self._ambiguous:
            self._ambiguous.remove(source)
        self._rebuild()

    def unpair_selected(self) -> None:
        """Drop the pairing of every selected row, on either side."""
        sources = {i.text(0) for i in self.src_tree.selectedItems()}
        targets = {i.text(0) for i in self.tgt_tree.selectedItems()}
        for s, t in list(self._mapping.items()):
            if s in sources or t in targets:
                self._mapping.pop(s, None)
                self._locked.pop(s, None)
        self._rebuild()

    def clear_mapping(self) -> None:
        self._mapping = {}
        self._locked = {}
        self._ambiguous = []
        self._rebuild()

    # -- Public API -------------------------------------------------------

    def source_names(self) -> List[str]:
        return list(self._source_names)

    def get_mapping(self) -> Dict[str, str]:
        return dict(self._mapping)

    def set_mapping(self,
                    mapping: Dict[str, str],
                    src_rule: Tuple[str, str] = ("", ""),
                    tgt_rule: Tuple[str, str] = ("", ""),
                    ) -> None:
        """Restore a saved mapping and the rules that produced it.

        Pairs are restored as LOCKED: a loaded mapping is an authored decision,
        so a later Auto-match must extend it rather than reinterpret it.
        """
        self.src_pattern.blockSignals(True)
        self.src_replace.blockSignals(True)
        self.tgt_pattern.blockSignals(True)
        self.tgt_replace.blockSignals(True)
        self.src_pattern.setText(src_rule[0])
        self.src_replace.setText(src_rule[1])
        self.tgt_pattern.setText(tgt_rule[0])
        self.tgt_replace.setText(tgt_rule[1])
        self.src_pattern.blockSignals(False)
        self.src_replace.blockSignals(False)
        self.tgt_pattern.blockSignals(False)
        self.tgt_replace.blockSignals(False)

        valid_s = set(self._source_names)
        valid_t = set(self._target_names)
        self._mapping = {s: t for s, t in mapping.items()
                         if s in valid_s and t in valid_t}
        self._locked = dict(self._mapping)
        self._ambiguous = []
        self._rebuild()