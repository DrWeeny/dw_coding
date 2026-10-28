"""
wgt_source.py - pick one side of the diff: a preset file, a scene node, or a type's Maya default.

Summary:
    A kind combo, the matching field (path / node / node type) with its helper
    button, the entry combo when a preset file holds several nodes, and Save /
    Save as for a file side. Load builds the source and emits source_changed;
    a problem is shown under the fields, never raised.

Classes:
    SourcePicker

Author:
    DrWeeny
"""

from __future__ import annotations

import os

import maya.cmds as cmds

from dw_maya.AttrPresetDiff import diff_cmds
from dw_maya.AttrPresetDiff.compat import QtCore, QtWidgets, Signal

KINDS = (("Preset file", "file"), ("Scene node", "node"), ("Maya default", "default"))


class SourcePicker(QtWidgets.QGroupBox):
    """One side (A or B): builds a diff_cmds Source from what is typed / picked."""

    source_changed = Signal(object)   # the Source, or None when cleared / failed

    def __init__(self,
                 title: str,
                 parent=None,) -> None:
        super().__init__(title, parent)
        self._source = None
        self._build_ui()
        self._on_kind()

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QtWidgets.QGridLayout(self)
        self._kind = QtWidgets.QComboBox()
        for label, kind in KINDS:
            self._kind.addItem(label, kind)
        self._field = QtWidgets.QLineEdit()
        self._helper = QtWidgets.QPushButton("...")
        self._helper.setMaximumWidth(80)
        self._load = QtWidgets.QPushButton("Load")
        self._entry = QtWidgets.QComboBox()
        self._entry.setToolTip("Node entry of the preset file")
        self._save = QtWidgets.QPushButton("Save")
        self._save_as = QtWidgets.QPushButton("Save as...")
        self._status = QtWidgets.QLabel("")
        self._status.setWordWrap(True)

        layout.addWidget(self._kind, 0, 0)
        layout.addWidget(self._field, 0, 1)
        layout.addWidget(self._helper, 0, 2)
        layout.addWidget(self._load, 0, 3)
        layout.addWidget(self._entry, 1, 0, 1, 2)
        layout.addWidget(self._save, 1, 2)
        layout.addWidget(self._save_as, 1, 3)
        layout.addWidget(self._status, 2, 0, 1, 4)
        layout.setColumnStretch(1, 1)

        self._kind.currentIndexChanged.connect(self._on_kind)
        self._helper.clicked.connect(self._on_helper)
        self._load.clicked.connect(self._on_load)
        self._field.returnPressed.connect(self._on_load)
        self._entry.activated.connect(self._on_entry)
        self._save.clicked.connect(self._on_save)
        self._save_as.clicked.connect(self._on_save_as)

    def _kind_key(self) -> str:
        return self._kind.currentData()

    def _on_kind(self,
                 _index=None,) -> None:
        kind = self._kind_key()
        placeholder = {"file": "preset .json", "node": "node name", "default": "node type (nucleus, nCloth...)"}
        helper = {"file": "...", "node": "Selected", "default": "From A/B"}
        self._field.setPlaceholderText(placeholder[kind])
        self._helper.setText(helper[kind])
        self._helper.setVisible(kind != "default")
        self._update_buttons()

    def _update_buttons(self) -> None:
        is_file = isinstance(self._source, diff_cmds.FileSource)
        self._entry.setVisible(is_file and len(self._source.identities) > 1)
        self._save.setVisible(is_file)
        self._save_as.setVisible(is_file)
        self._save.setEnabled(is_file and self._source.dirty)

    # -- Public -----------------------------------------------------------

    def source(self):
        return self._source

    def set_input(self,
                  kind:  str,
                  value: str,) -> None:
        """Preload a side (launch(a=..., b=...)) and load it."""
        index = self._kind.findData(kind)
        if index >= 0:
            self._kind.setCurrentIndex(index)
        self._field.setText(value)
        self._on_load()

    def refresh_state(self) -> None:
        """After an edit: dirty flag / label follow the source."""
        if self._source is not None:
            self._status.setText(self._source.label)
        self._update_buttons()

    # -- Actions ----------------------------------------------------------

    def _set_status(self,
                    text:  str,
                    error: bool = False,) -> None:
        self._status.setStyleSheet("color: #e06c5c;" if error else "")
        self._status.setText(text)

    def _on_helper(self) -> None:
        kind = self._kind_key()
        if kind == "file":
            start = os.path.dirname(self._field.text()) if self._field.text() else ""
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Preset file", start, "Preset (*.json)")
            if path:
                self._field.setText(path)
                self._on_load()
        elif kind == "node":
            selection = cmds.ls(selection=True, long=False) or []
            if selection:
                self._field.setText(selection[0])
                self._on_load()

    def _on_load(self) -> None:
        if not self._confirm_drop_edits():
            return
        kind, text = self._kind_key(), self._field.text().strip()
        if not text:
            self._source = None
            self._set_status("")
            self._update_buttons()
            self.source_changed.emit(None)
            return
        try:
            if kind == "file":
                source = diff_cmds.FileSource(text)
            elif kind == "node":
                source = diff_cmds.NodeSource(text)
            else:
                source = diff_cmds.DefaultSource(text)
        except Exception as e:
            self._source = None
            self._set_status(str(e), error=True)
            self._update_buttons()
            self.source_changed.emit(None)
            return
        self._source = source
        self._entry.clear()
        if isinstance(source, diff_cmds.FileSource):
            self._entry.addItems(source.identities)
            self._entry.setCurrentText(source.identity)
        self._set_status(source.label)
        self._update_buttons()
        self.source_changed.emit(source)

    def _on_entry(self,
                  _index=None,) -> None:
        if isinstance(self._source, diff_cmds.FileSource):
            self._source.select(self._entry.currentText())
            self.refresh_state()
            self.source_changed.emit(self._source)

    def _on_save(self) -> None:
        if isinstance(self._source, diff_cmds.FileSource):
            try:
                self._source.save()
            except Exception as e:
                self._set_status(f"Not saved: {e}", error=True)
                return
            self.refresh_state()

    def _on_save_as(self) -> None:
        if not isinstance(self._source, diff_cmds.FileSource):
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save preset as", self._source.path, "Preset (*.json)")
        if not path:
            return
        try:
            self._source.save(path)
        except Exception as e:
            self._set_status(f"Not saved: {e}", error=True)
            return
        self._field.setText(path)
        self.refresh_state()

    def _confirm_drop_edits(self) -> bool:
        """Loading over a file with unsaved edits asks first."""
        if not (isinstance(self._source, diff_cmds.FileSource) and self._source.dirty):
            return True
        answer = QtWidgets.QMessageBox.question(
            self, "AttrPresetDiff", f"{os.path.basename(self._source.path)} has unsaved edits. Drop them?")
        return answer == QtWidgets.QMessageBox.Yes

    def has_unsaved(self) -> bool:
        return isinstance(self._source, diff_cmds.FileSource) and self._source.dirty
