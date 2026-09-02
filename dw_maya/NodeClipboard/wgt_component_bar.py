"""
wgt_component_bar.py - one checkbox per component, across every node.

Summary:
    The simple-mode control: instead of the node x component tree, a flat row
    of checkboxes (Hierarchy / Attributes / Connections / Keyframes /
    Geometry / Network rebuild) covering every node in the entry at once.
    It is a *view over the tree* - toggling one calls ``set_component`` on the
    tree, and the tree pushes its aggregate state back - so both halves of
    the UI always agree on a single source of truth.

Features:
    - Keys come from the loaded entry, so a component no node stored never
      shows up as a dead checkbox.
    - A component checked on some nodes only (set from the advanced tree)
      displays as partially checked.

Classes:
    ComponentBar

Author:
    DrWeeny
"""

import functools
from typing import Dict, List, Optional

from dw_maya.NodeClipboard.compat import QtWidgets, Qt, Signal
import dw_maya.NodeClipboard.clipboard_cmds as clipboard_cmds


class ComponentBar(QtWidgets.QWidget):
    """Flat per-component checkboxes for the whole entry."""

    component_toggled = Signal(str, bool)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super(ComponentBar, self).__init__(parent)
        self._boxes = {}
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._empty = QtWidgets.QLabel("No entry on the clipboard yet.")
        self._layout.addWidget(self._empty)
        self._layout.addStretch(1)

    # -- population ---------------------------------------------------------

    def set_keys(self, keys: Optional[List[str]] = None) -> None:
        """Rebuild the checkboxes for the component keys of one entry."""
        for box in self._boxes.values():
            self._layout.removeWidget(box)
            box.setParent(None)
            box.deleteLater()
        self._boxes = {}
        keys = keys or []
        self._empty.setVisible(not keys)
        for index, key in enumerate(keys):
            # Held in the dict, not just the layout: an unreferenced widget
            # can outlive its Python handle in the wrong order otherwise.
            box = QtWidgets.QCheckBox(clipboard_cmds.component_label(key))
            box.setToolTip(clipboard_cmds.component_tip(key))
            box.setChecked(True)
            box.clicked.connect(functools.partial(self._on_clicked, key))
            self._boxes[key] = box
            self._layout.insertWidget(index + 1, box)

    def keys(self) -> List[str]:
        """The component keys currently shown."""
        return list(self._boxes)

    # -- state --------------------------------------------------------------

    def set_states(self, states: Optional[Dict[str, int]] = None) -> None:
        """Display an aggregate state per key without re-emitting signals.

        Args:
            states: ``{component key: Qt check state}``, as produced by
                :meth:`EntryTree.component_state`.
        """
        for key, box in self._boxes.items():
            state = (states or {}).get(key, Qt.Unchecked)
            box.blockSignals(True)
            box.setCheckState(state)
            box.blockSignals(False)

    def checked_keys(self) -> List[str]:
        """Keys whose checkbox is not fully unchecked."""
        return [key for key, box in self._boxes.items()
                if box.checkState() != Qt.Unchecked]

    # -- internals ----------------------------------------------------------

    def _on_clicked(self, key: str = "") -> None:
        """A user click is always all-or-nothing for that component.

        The new state is read back from the box rather than taken from the
        ``clicked(bool)`` argument: bound through ``functools.partial``, PySide
        matches the no-argument ``clicked()`` overload and the flag would keep
        its default, so every click re-checked the box it had just cleared.
        A partially checked box goes to fully checked, as Qt already did.
        """
        box = self._boxes.get(key)
        if box is None:
            return
        checked = box.checkState() != Qt.Unchecked
        box.blockSignals(True)
        box.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        box.blockSignals(False)
        self.component_toggled.emit(key, checked)
