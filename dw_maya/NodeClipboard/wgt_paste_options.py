"""
wgt_paste_options.py - where the pasted nodes land.

Summary:
    The knobs of one paste: the target namespace the entry is rebuilt into,
    whether missing nodes may be created, and what happens to connections
    captured toward *other* assets (external namespaces) - skip them, or
    remap each stored external namespace onto one that exists here.

Features:
    - The namespace combos are editable and pre-filled with the scene's
      namespaces, ``:`` standing for the root on either side of a remap.
    - The remap table only lists the external namespaces the loaded entry
      actually stored (its top-level ``namespaces["external"]`` summary), so
      it stays empty for a self-contained entry.

Classes:
    PasteOptions

Author:
    DrWeeny
"""

from typing import Dict, List, Optional

from dw_maya.NodeClipboard.compat import QtWidgets, Qt
import dw_maya.NodeClipboard.clipboard_cmds as clipboard_cmds

#: Placeholder meaning "leave this external namespace as it was captured".
KEEP = "<keep>"


class PasteOptions(QtWidgets.QWidget):
    """Target namespace, create flag and external-namespace remapping."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super(PasteOptions, self).__init__(parent)
        self._namespaces = [":"]

        self.ns_combo = QtWidgets.QComboBox()
        self.ns_combo.setEditable(True)
        self.ns_combo.setToolTip("Namespace the rebuilt nodes land in "
                                 "(':' = root).")

        self.create_check = QtWidgets.QCheckBox("Create missing nodes")
        self.create_check.setChecked(True)
        self.create_check.setToolTip("Off: only nodes already in the scene "
                                     "are touched, nothing is created.")

        self.external_check = QtWidgets.QCheckBox("Apply external connections")
        self.external_check.setChecked(True)
        self.external_check.setToolTip("Connections captured toward another "
                                       "asset. Off skips them wholesale.")
        self.external_check.toggled.connect(self._on_external_toggled)

        self.remap_table = QtWidgets.QTableWidget(0, 2)
        self.remap_table.setHorizontalHeaderLabels(["Stored namespace",
                                                    "Rebuild against"])
        self.remap_table.verticalHeader().setVisible(False)
        self.remap_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        self.remap_table.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers)
        self.remap_table.setMaximumHeight(120)

        self.remap_group = QtWidgets.QGroupBox("External namespaces")
        remap_layout = QtWidgets.QVBoxLayout(self.remap_group)
        remap_layout.setContentsMargins(4, 4, 4, 4)
        remap_layout.addWidget(self.remap_table)

        form = QtWidgets.QFormLayout()
        form.addRow("Target namespace", self.ns_combo)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(form)
        layout.addWidget(self.create_check)
        layout.addWidget(self.external_check)
        layout.addWidget(self.remap_group)

        self.refresh_namespaces()
        self.set_entry({})

    # -- population ---------------------------------------------------------

    def refresh_namespaces(self) -> None:
        """Re-read the scene namespaces into every combo."""
        self._namespaces = clipboard_cmds.scene_namespaces()
        current = self.ns_combo.currentText() or ":"
        self.ns_combo.clear()
        self.ns_combo.addItems(self._namespaces)
        self.ns_combo.setCurrentText(current)

    def set_entry(self, info: Optional[dict] = None) -> None:
        """Fill the remap table from an entry's namespace summary."""
        info = info or {}
        external = (info.get("namespaces") or {}).get("external") or []
        self.remap_table.setRowCount(0)
        for stored in external:
            row = self.remap_table.rowCount()
            self.remap_table.insertRow(row)
            item = QtWidgets.QTableWidgetItem(stored)
            item.setFlags(Qt.ItemIsEnabled)
            self.remap_table.setItem(row, 0, item)
            combo = QtWidgets.QComboBox()
            combo.setEditable(True)
            combo.addItem(KEEP)
            combo.addItems(self._namespaces)
            # Pre-select the same namespace when the shot already has it -
            # the usual case when both scenes reference the same asset.
            combo.setCurrentText(stored if stored in self._namespaces else KEEP)
            self.remap_table.setCellWidget(row, 1, combo)
        self.remap_group.setVisible(bool(external))
        self._on_external_toggled(self.external_check.isChecked())

    # -- state --------------------------------------------------------------

    def target_namespace(self) -> str:
        """The namespace rebuilt nodes land in."""
        return self.ns_combo.currentText().strip() or ":"

    def create(self) -> bool:
        """True when missing nodes may be created."""
        return self.create_check.isChecked()

    def apply_external(self) -> bool:
        """True when external connections are applied."""
        return self.external_check.isChecked()

    def ext_ns_map(self) -> Dict[str, str]:
        """Return ``{stored external ns: target ns}`` for the changed rows."""
        mapping = {}
        for row in range(self.remap_table.rowCount()):
            stored = self.remap_table.item(row, 0).text()
            combo = self.remap_table.cellWidget(row, 1)
            target = combo.currentText().strip()
            if not target or target == KEEP or target == stored:
                continue
            mapping[stored] = target
        return mapping

    def external_namespaces(self) -> List[str]:
        """The stored external namespaces currently listed."""
        return [self.remap_table.item(row, 0).text()
                for row in range(self.remap_table.rowCount())]

    # -- internals ----------------------------------------------------------

    def _on_external_toggled(self, enabled: bool = True) -> None:
        self.remap_group.setEnabled(enabled and self.remap_table.rowCount() > 0)
