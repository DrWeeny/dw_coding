"""
wgt_entry_tree.py - the node x component checkbox tree.

Summary:
    Shows one clipboard entry: a top-level row per saved node (identity +
    node type), a child row per component slice that node actually holds
    (hierarchy / attributes / connections / keyframes / geometry / network).
    Checking rows builds the ``include`` mapping the paste command takes, so
    the artist decides per node what travels between the two Maya sessions.

Features:
    - Manual tristate propagation (parent -> children, children -> parent);
      PySide2 and PySide6 disagree on the auto-tristate flag name.
    - Per-component bulk toggles: check / uncheck one component key on every
      node at once (right-click menu), which is the common case.

Classes:
    EntryTree

Author:
    DrWeeny
"""

import functools
from typing import Dict, List, Optional

from dw_maya.NodeClipboard.compat import QtCore, QtWidgets, Qt, Signal, qt_exec
import dw_maya.NodeClipboard.clipboard_cmds as clipboard_cmds

IDENTITY_ROLE = Qt.UserRole + 1
COMPONENT_ROLE = Qt.UserRole + 2


class EntryTree(QtWidgets.QTreeWidget):
    """Checkbox tree over one clipboard entry."""

    selection_changed = Signal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super(EntryTree, self).__init__(parent)
        self.setColumnCount(2)
        self.setHeaderLabels(["Node / component", "Type"])
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.itemChanged.connect(self._on_item_changed)
        self.customContextMenuRequested.connect(self._on_context_menu)

    # -- population ---------------------------------------------------------

    def set_entry(self, info: Optional[dict] = None) -> None:
        """Rebuild the tree from a :func:`clipboard_cmds.entry_info` dict."""
        self.blockSignals(True)
        self.clear()
        info = info or {}
        nodes = info.get("nodes", {})
        components = info.get("components", {})
        for identity, node_type in nodes.items():
            # Kept in a variable on purpose: an unreferenced QTreeWidgetItem
            # can be collected before the C++ side takes ownership.
            top = QtWidgets.QTreeWidgetItem(self, [identity, node_type or ""])
            top.setData(0, IDENTITY_ROLE, identity)
            top.setFlags(top.flags() | Qt.ItemIsUserCheckable)
            top.setCheckState(0, Qt.Checked)
            for key in components.get(identity, []):
                child = QtWidgets.QTreeWidgetItem(
                    top, [clipboard_cmds.component_label(key), ""])
                child.setData(0, IDENTITY_ROLE, identity)
                child.setData(0, COMPONENT_ROLE, key)
                child.setToolTip(0, clipboard_cmds.component_tip(key))
                child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Checked)
        # Nodes visible, their slices folded away: the tree is first read as
        # "what is in this entry", the per-slice detail is opened on demand.
        self.collapseAll()
        self.blockSignals(False)
        self.selection_changed.emit()

    # -- state --------------------------------------------------------------

    def include(self) -> Dict[str, List[str]]:
        """Return ``{identity: [component keys]}`` for the checked rows.

        A node whose row is unchecked is left out entirely; a node kept with
        no checked child yields an empty list, which rebuilds the bare node
        without applying any slice.
        """
        picked = {}
        for index in range(self.topLevelItemCount()):
            top = self.topLevelItem(index)
            if top.checkState(0) == Qt.Unchecked:
                continue
            identity = top.data(0, IDENTITY_ROLE)
            keys = []
            for row in range(top.childCount()):
                child = top.child(row)
                if child.checkState(0) == Qt.Checked:
                    keys.append(child.data(0, COMPONENT_ROLE))
            picked[identity] = keys
        return picked

    def counts(self) -> tuple:
        """Return ``(checked nodes, total nodes, checked components)``."""
        picked = self.include()
        return (len(picked),
                self.topLevelItemCount(),
                sum(len(keys) for keys in picked.values()))

    def component_keys(self) -> List[str]:
        """Every distinct component key present in the current entry."""
        keys = []
        for index in range(self.topLevelItemCount()):
            top = self.topLevelItem(index)
            for row in range(top.childCount()):
                key = top.child(row).data(0, COMPONENT_ROLE)
                if key not in keys:
                    keys.append(key)
        return keys

    def component_state(self, key: str = "") -> int:
        """Aggregate check state of one component key over every node.

        Returns Qt.Checked when every node that stores the slice has it on,
        Qt.Unchecked when none does, Qt.PartiallyChecked in between - the
        state the flat component bar displays. Nodes whose own row is
        unchecked do not count: they contribute nothing to the paste.
        """
        checked = 0
        total = 0
        for index in range(self.topLevelItemCount()):
            top = self.topLevelItem(index)
            for row in range(top.childCount()):
                child = top.child(row)
                if child.data(0, COMPONENT_ROLE) != key:
                    continue
                total += 1
                if (child.checkState(0) == Qt.Checked
                        and top.checkState(0) != Qt.Unchecked):
                    checked += 1
        if not total or not checked:
            return Qt.Unchecked
        return Qt.Checked if checked == total else Qt.PartiallyChecked

    def component_states(self) -> Dict[str, int]:
        """``{component key: aggregate check state}`` for the whole entry."""
        return {key: self.component_state(key) for key in self.component_keys()}

    # -- bulk toggles -------------------------------------------------------

    def set_all(self, checked: bool = True) -> None:
        """Check or uncheck every node and component."""
        state = Qt.Checked if checked else Qt.Unchecked
        self.blockSignals(True)
        for index in range(self.topLevelItemCount()):
            top = self.topLevelItem(index)
            top.setCheckState(0, state)
            for row in range(top.childCount()):
                top.child(row).setCheckState(0, state)
        self.blockSignals(False)
        self.selection_changed.emit()

    def set_component(self, key: str = "", checked: bool = True) -> None:
        """Check or uncheck one component key across every node."""
        state = Qt.Checked if checked else Qt.Unchecked
        self.blockSignals(True)
        for index in range(self.topLevelItemCount()):
            top = self.topLevelItem(index)
            for row in range(top.childCount()):
                child = top.child(row)
                if child.data(0, COMPONENT_ROLE) == key:
                    child.setCheckState(0, state)
            self._sync_parent(top)
        self.blockSignals(False)
        self.selection_changed.emit()

    # -- internals ----------------------------------------------------------

    def _sync_parent(self, parent: QtWidgets.QTreeWidgetItem) -> None:
        """Set a node row to checked / partial from its children.

        A node with every slice off is not turned off: "rebuild the bare
        node" stays a valid choice, so the row only drops to partial.
        """
        if not parent.childCount() or parent.checkState(0) == Qt.Unchecked:
            # A node switched off in the tree stays off: a component toggle
            # must not silently bring it back into the paste.
            return
        checked = sum(1 for row in range(parent.childCount())
                      if parent.child(row).checkState(0) == Qt.Checked)
        if checked == parent.childCount():
            parent.setCheckState(0, Qt.Checked)
        elif parent.checkState(0) != Qt.Unchecked:
            parent.setCheckState(0, Qt.PartiallyChecked)

    def _on_item_changed(self,
                         item: QtWidgets.QTreeWidgetItem,
                         column: int) -> None:
        if column != 0:
            return
        self.blockSignals(True)
        if item.childCount():
            state = item.checkState(0)
            if state != Qt.PartiallyChecked:
                for row in range(item.childCount()):
                    item.child(row).setCheckState(0, state)
        else:
            parent = item.parent()
            if parent is not None:
                self._sync_parent(parent)
        self.blockSignals(False)
        self.selection_changed.emit()

    def _on_context_menu(self, point: QtCore.QPoint) -> None:
        keys = self.component_keys()
        if not keys:
            return
        menu = QtWidgets.QMenu(self)
        check_all = menu.addAction("Check all")
        check_all.triggered.connect(functools.partial(self.set_all, True))
        uncheck_all = menu.addAction("Uncheck all")
        uncheck_all.triggered.connect(functools.partial(self.set_all, False))
        menu.addSeparator()
        for key in keys:
            label = clipboard_cmds.component_label(key)
            on = menu.addAction(f"Check '{label}' everywhere")
            on.triggered.connect(functools.partial(self.set_component, key, True))
            off = menu.addAction(f"Uncheck '{label}' everywhere")
            off.triggered.connect(functools.partial(self.set_component, key, False))
        qt_exec(menu, self.viewport().mapToGlobal(point))
