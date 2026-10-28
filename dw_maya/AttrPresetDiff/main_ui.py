"""
main_ui.py - AttrPresetDiff window: A vs B, with the node type's Maya default as reference.

Summary:
    Two sources side by side (preset file, scene node, or a type's Maya
    default) and one table: Role | Attribute | Default | A | B.

    - A and B differing: both cells bold on an amber row.
    - A value away from the Maya default: blue text - "what the artist
      changed" reads at a glance even without a B.
    - Double-click an A / B cell to edit it: a file side is edited in memory
      (Save / Save as on its picker), a node side sets the attribute (one undo).
    - Copy buttons push the selected rows' values A -> B, B -> A, or the
      default onto either side (reset).

    Differences only / Own attributes only (hide what the type inherits) /
    Array elements (per-element values, hidden by default) / a name filter.

Classes:
    AttrPresetDiffUI

Functions:
    launch - open the window, optionally with A / B preloaded.

Author:
    DrWeeny
"""

from __future__ import annotations

import functools
import os

from dw_maya.AttrPresetDiff import diff_cmds
from dw_maya.AttrPresetDiff.compat import QtCore, QtGui, QtWidgets, wrapInstance
from dw_maya.AttrPresetDiff.wgt_source import SourcePicker

COL_ROLE, COL_ATTR, COL_DEFAULT, COL_A, COL_B = range(5)
ROLE_ROW = QtCore.Qt.UserRole + 1     # the diff_cmds.Row on the attribute item
_AMBER = QtGui.QColor(120, 90, 30)
_BLUE = QtGui.QColor(110, 170, 240)
_GREY = QtGui.QColor(60, 60, 60)

_window = None


class AttrPresetDiffUI(QtWidgets.QMainWindow):
    """Diff / edit attribute values between two presets, nodes or Maya defaults."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AttrPresetDiff")
        self.setObjectName("AttrPresetDiffUI")
        self.resize(900, 640)
        self._default = None
        self._filling = False
        self._build_ui()

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        sides = QtWidgets.QHBoxLayout()
        self.picker_a = SourcePicker("A")
        self.picker_b = SourcePicker("B")
        sides.addWidget(self.picker_a)
        sides.addWidget(self.picker_b)
        layout.addLayout(sides)

        options = QtWidgets.QHBoxLayout()
        self._differences = QtWidgets.QCheckBox("Differences only")
        self._differences.setChecked(True)
        self._own = QtWidgets.QCheckBox("Own attributes only")
        self._own.setChecked(True)
        self._own.setToolTip("Hide what the node type inherits (visibility, intermediateObject...).")
        self._elements = QtWidgets.QCheckBox("Array elements")
        self._elements.setToolTip("Per-element values (bones[3].mass...): a chain-length layer, not a preset.")
        self._filter = QtWidgets.QLineEdit()
        self._filter.setPlaceholderText("filter attributes")
        self._default_label = QtWidgets.QLabel("Default: -")
        self._refresh_default = QtWidgets.QPushButton("Re-measure default")
        self._refresh_default.setToolTip("Create the node type again and update the cached default values.")
        for widget in (self._differences, self._own, self._elements):
            options.addWidget(widget)
        options.addWidget(self._filter, stretch=1)
        self._refresh = QtWidgets.QPushButton("Refresh")
        self._refresh.setToolTip("Re-read the scene node sides (after changing them in Maya).")
        self._refresh.clicked.connect(self._rebuild)
        options.addWidget(self._refresh)
        options.addWidget(self._default_label)
        options.addWidget(self._refresh_default)
        layout.addLayout(options)

        self._model = QtGui.QStandardItemModel(0, 5)
        self._model.setHorizontalHeaderLabels(["Role", "Attribute", "Default", "A", "B"])
        self._proxy = QtCore.QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._view = QtWidgets.QTreeView()
        self._view.setModel(self._proxy)
        self._view.setRootIsDecorated(False)
        self._view.setAlternatingRowColors(True)
        self._view.setSortingEnabled(True)
        self._view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._view.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked
                                   | QtWidgets.QAbstractItemView.EditKeyPressed)
        layout.addWidget(self._view, stretch=1)

        copies = QtWidgets.QHBoxLayout()
        self._summary = QtWidgets.QLabel("")
        copies.addWidget(self._summary, stretch=1)
        for label, origin, target in (("A -> B", "a", "b"), ("B -> A", "b", "a"),
                                      ("Default -> A", "default", "a"), ("Default -> B", "default", "b")):
            button = QtWidgets.QPushButton(label)
            button.setToolTip(f"Copy the selected rows' {origin} value onto {target.upper()}.")
            button.clicked.connect(functools.partial(self._on_copy, origin, target))
            copies.addWidget(button)
        layout.addLayout(copies)

        self.picker_a.source_changed.connect(self._on_sources)
        self.picker_b.source_changed.connect(self._on_sources)
        for box in (self._differences, self._own, self._elements):
            box.toggled.connect(self._rebuild)
        self._filter.textChanged.connect(self._rebuild)
        self._refresh_default.clicked.connect(self._on_refresh_default)
        self._model.itemChanged.connect(self._on_item_changed)

    # -- Sources ----------------------------------------------------------

    def _sides(self) -> dict:
        return {"a": self.picker_a.source(), "b": self.picker_b.source()}

    def _on_sources(self,
                    _source=None,
                    refresh: bool = False,) -> None:
        """A side changed: the default follows A's node type (else B's)."""
        sides = self._sides()
        types = [s.node_type for s in sides.values() if s is not None and s.node_type]
        node_type = types[0] if types else ""
        text = f"Default: {node_type or '-'}"
        if len(set(types)) > 1:
            text += f"   (A is {types[0]}, B is {types[1]})"
        self._default = None
        if node_type:
            try:
                self._default = diff_cmds.DefaultSource(node_type, refresh=refresh)
            except Exception as e:
                text += f"   - unavailable: {e}"
        self._default_label.setText(text)
        self._rebuild()

    def _on_refresh_default(self) -> None:
        self._on_sources(refresh=True)

    # -- Table ------------------------------------------------------------

    def _rebuild(self,
                 *_args) -> None:
        sides = self._sides()
        # A node side is re-read every time: the scene changes under the tool
        # (undo, the Attribute Editor, a script) and a cached read would show
        # differences that are gone - or hide new ones.
        for source in sides.values():
            if source is not None:
                try:
                    source.refresh()
                except Exception:
                    pass   # a deleted node shows its last values rather than breaking the table
        rows = diff_cmds.diff_rows(sides["a"], sides["b"], self._default,
                                   differences_only=self._differences.isChecked(),
                                   own_only=self._own.isChecked(),
                                   elements=self._elements.isChecked(),
                                   text=self._filter.text())
        self._filling = True
        self._model.removeRows(0, self._model.rowCount())
        for row in rows:
            self._model.appendRow(self._row_items(row, sides))
        self._filling = False
        for column in range(5):
            self._view.resizeColumnToContents(column)
        n_diff = sum(1 for r in rows if r.a_vs_b) if sides["a"] and sides["b"] else 0
        self._summary.setText(f"{len(rows)} row(s)" + (f", {n_diff} differ between A and B" if n_diff else ""))
        self.picker_a.refresh_state()
        self.picker_b.refresh_state()

    def _row_items(self,
                   row,
                   sides: dict,) -> list:
        role_item = QtGui.QStandardItem(row.key[0])
        attr_item = QtGui.QStandardItem(row.key[1])
        attr_item.setData(row, ROLE_ROW)
        default_item = QtGui.QStandardItem(diff_cmds.format_value(row.default))
        a_item = QtGui.QStandardItem(diff_cmds.format_value(row.a))
        b_item = QtGui.QStandardItem(diff_cmds.format_value(row.b))
        items = [role_item, attr_item, default_item, a_item, b_item]
        for item in items:
            item.setEditable(False)
        for item, side, changed in ((a_item, "a", row.a_changed), (b_item, "b", row.b_changed)):
            source = sides[side]
            item.setEditable(bool(source is not None and source.editable))
            if changed:
                item.setForeground(QtGui.QBrush(_BLUE))
            if getattr(row, side) is diff_cmds.MISSING and source is not None:
                item.setBackground(QtGui.QBrush(_GREY))
        if sides["a"] is not None and sides["b"] is not None and row.a_vs_b:
            font = QtGui.QFont()
            font.setBold(True)
            for item in items:
                item.setBackground(QtGui.QBrush(_AMBER))
            a_item.setFont(font)
            b_item.setFont(font)
        return items

    def _row_of(self,
                model_row: int):
        return self._model.item(model_row, COL_ATTR).data(ROLE_ROW)

    def _on_item_changed(self,
                         item,) -> None:
        if self._filling or item.column() not in (COL_A, COL_B):
            return
        side = "a" if item.column() == COL_A else "b"
        source = self._sides()[side]
        row = self._row_of(item.row())
        current = getattr(row, side)
        like = current if current is not diff_cmds.MISSING else (row.b if side == "a" else row.a)
        try:
            value = diff_cmds.parse_value(item.text(), like)
            source.set(row.key, value)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "AttrPresetDiff", f"{row.key[1]}: {e}")
        # Rebuilt after the edit has finished, never inside the model's own signal.
        QtCore.QTimer.singleShot(0, self._rebuild)

    def _selected_rows(self) -> list:
        model_rows = sorted({self._proxy.mapToSource(i).row() for i in self._view.selectionModel().selectedRows()})
        return [self._row_of(r) for r in model_rows]

    def _on_copy(self,
                 origin: str,
                 target: str,
                 _checked: bool = False,) -> None:
        source = self._sides()[target]
        if source is None or not source.editable:
            QtWidgets.QMessageBox.information(self, "AttrPresetDiff", f"{target.upper()} cannot be edited.")
            return
        rows = self._selected_rows()
        if not rows:
            QtWidgets.QMessageBox.information(self, "AttrPresetDiff", "Select the rows to copy.")
            return
        problems = diff_cmds.copy_rows(rows, source, origin)
        if problems:
            QtWidgets.QMessageBox.warning(self, "AttrPresetDiff", "Not copied:\n\n" + "\n".join(problems))
        self._rebuild()

    # -- Window -----------------------------------------------------------

    def preload(self,
                a: str = "",
                b: str = "",) -> None:
        """Fill A / B from a preset path or a node name."""
        for picker, value in ((self.picker_a, a), (self.picker_b, b)):
            if value:
                kind = "file" if value.lower().endswith(".json") and os.path.isfile(value) else "node"
                picker.set_input(kind, value)

    def closeEvent(self, event) -> None:
        if self.picker_a.has_unsaved() or self.picker_b.has_unsaved():
            answer = QtWidgets.QMessageBox.question(self, "AttrPresetDiff", "Unsaved preset edits. Close anyway?")
            if answer != QtWidgets.QMessageBox.Yes:
                event.ignore()
                return
        super().closeEvent(event)


def _maya_main_window():
    try:
        import maya.OpenMayaUI as omui
    except ImportError:
        return None
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QWidget) if ptr else None


def launch(a: str = "",
           b: str = "",) -> AttrPresetDiffUI:
    """Open (or re-open) the window; `a` / `b` preload a preset path or a node name."""
    global _window
    if _window is not None:
        try:
            _window.close()
            _window.deleteLater()
        except Exception:
            pass
        _window = None
    _window = AttrPresetDiffUI(parent=_maya_main_window())
    _window.preload(a, b)
    _window.show()
    return _window
