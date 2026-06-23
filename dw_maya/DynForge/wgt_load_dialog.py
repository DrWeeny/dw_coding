"""
wgt_load_dialog.py - DynForge "Load system" dialog.

Two sources, picked with a radio:
- from file: a combo of preset files (placeholder for now - the preset directory
  is not wired yet) plus a Browse button to point at any .json
- from Maya: a combo of the guide groups detected in the current scene

selection() returns ("file", path) or ("maya", group_long_path), or None.
"""

from __future__ import annotations

from dw_maya.DynForge.forge_cmds.compat import QtWidgets


class LoadDialog(QtWidgets.QDialog):
    """Pick where to load a DynForge system from (file or scene)."""

    def __init__(self,
                 maya_groups,
                 parent=None,) -> None:
        super().__init__(parent)
        self.setWindowTitle("Load system")
        self.setMinimumWidth(340)
        self._build_ui(maya_groups or [])

    # -- UI ---------------------------------------------------------------

    def _build_ui(self,
                  maya_groups: list,) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        # Source: from file
        self._rb_file = QtWidgets.QRadioButton("Load from file")
        self._rb_file.setChecked(True)
        layout.addWidget(self._rb_file)

        file_row = QtWidgets.QHBoxLayout()
        self._file_combo = QtWidgets.QComboBox()
        # Placeholder until a preset directory is configured.
        self._file_combo.addItem("(browse for a file...)", None)
        self._browse_btn = QtWidgets.QPushButton("Browse...")
        file_row.addWidget(self._file_combo, stretch=1)
        file_row.addWidget(self._browse_btn)
        layout.addLayout(file_row)

        # Source: from Maya
        self._rb_maya = QtWidgets.QRadioButton("Load from Maya")
        layout.addWidget(self._rb_maya)

        maya_row = QtWidgets.QHBoxLayout()
        self._maya_combo = QtWidgets.QComboBox()
        for group in maya_groups:
            self._maya_combo.addItem(group.split("|")[-1], group)
        if not maya_groups:
            self._maya_combo.addItem("(no guide groups found)", None)
            self._rb_maya.setEnabled(False)
        maya_row.addWidget(self._maya_combo, stretch=1)
        layout.addLayout(maya_row)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._browse_btn.clicked.connect(self._on_browse)
        self._rb_file.toggled.connect(self._sync_enabled)
        self._sync_enabled()

    # -- Logic ------------------------------------------------------------

    def _sync_enabled(self,
                      *args,) -> None:
        from_file = self._rb_file.isChecked()
        self._file_combo.setEnabled(from_file)
        self._browse_btn.setEnabled(from_file)
        self._maya_combo.setEnabled(not from_file)

    def _on_browse(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load DynForge system", "", "JSON files (*.json)")
        if not path:
            return
        self._file_combo.addItem(path.split("/")[-1], path)
        self._file_combo.setCurrentIndex(self._file_combo.count() - 1)

    def selection(self):
        """Return ('file', path) / ('maya', group) for the active source, or None."""
        if self._rb_file.isChecked():
            path = self._file_combo.currentData()
            return ("file", path) if path else None
        group = self._maya_combo.currentData()
        return ("maya", group) if group else None