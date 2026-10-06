"""
wgt_naming_panel.py - DynForge top naming panel.

Composes a guide name from the pattern  prefix _ side _ index _ name.
The index auto-increments so every guide gets a unique name: when a new guide
is added, compose_unique() walks the index up from the current value until the
composed name is free, and writes the chosen index back into the spin box.

Empty prefix / side parts are skipped. A Maya node name cannot start with a
digit (Maya silently strips it: "0_chain_src_crv" becomes "_chain_src_crv", so
0_chain / 1_chain would collide), hence with no prefix and no side the index
goes after the name: "chain_0".
"""

from __future__ import annotations

from dw_maya.DynForge.forge_cmds.compat import QtWidgets
from dw_maya.DynForge.wgt_base import DynForgeWidgetBase


_SIDES = ("M", "L", "R", "C")


class NamingPanel(DynForgeWidgetBase):
    """Top panel holding the naming pattern fields."""

    def __init__(self,
                 hub,
                 defaults: dict = None,
                 parent=None,) -> None:
        super().__init__(hub, parent)
        # {"prefix": str, "sides": (str, ...)} - from the active ForgeHost.
        self._defaults = defaults or {}
        self._build_ui()

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._prefix = QtWidgets.QLineEdit(self._defaults.get("prefix", ""))
        self._prefix.setPlaceholderText("prefix")
        self._prefix.setMaximumWidth(90)

        self._side = QtWidgets.QComboBox()
        self._side.setEditable(True)
        self._side.addItems(list(self._defaults.get("sides", _SIDES)))
        self._side.setMaximumWidth(60)

        self._index = QtWidgets.QSpinBox()
        self._index.setRange(0, 999)
        self._index.setMaximumWidth(60)

        self._name = QtWidgets.QLineEdit("chain")
        self._name.setPlaceholderText("name")

        layout.addWidget(QtWidgets.QLabel("Prefix"))
        layout.addWidget(self._prefix)
        layout.addWidget(QtWidgets.QLabel("Side"))
        layout.addWidget(self._side)
        layout.addWidget(QtWidgets.QLabel("Index"))
        layout.addWidget(self._index)
        layout.addWidget(QtWidgets.QLabel("Name"))
        layout.addWidget(self._name, stretch=1)

    # -- Logic ------------------------------------------------------------

    def prefix(self) -> str:
        """The prefix field as typed (main_ui persists it)."""
        return self._prefix.text().strip()

    def _compose(self,
                 index: int,) -> str:
        """Join the non-empty pattern parts with underscores."""
        parts = []
        prefix = self._prefix.text().strip()
        side   = self._side.currentText().strip()
        name   = self._name.text().strip() or "chain"
        if prefix:
            parts.append(prefix)
        if side:
            parts.append(side)
        if not parts:
            return f"{name}_{index}"   # never lead with a digit (see module doc)
        parts.append(f"{index}")   # padding 1 (no leading zeros)
        parts.append(name)
        return "_".join(parts)

    def compose_unique(self,
                       existing: list,) -> str:
        """
        Return a composed name not present in `existing`, advancing the index
        from its current value and writing the chosen index back into the UI.
        """
        taken = set(existing)
        index = self._index.value()
        candidate = self._compose(index)
        while candidate in taken:
            index += 1
            candidate = self._compose(index)
        self._index.setValue(index)
        return candidate

    def bump_index(self) -> None:
        """Advance the index by one (call after a successful add)."""
        self._index.setValue(self._index.value() + 1)