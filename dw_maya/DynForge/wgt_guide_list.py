"""
wgt_guide_list.py - DynForge guide list panel (bottom-left).

A 3-column QTreeView (Name | Build/Rebuild | Status), one row per guide:
    column 0  name + a mode/status badge icon
    column 1  a per-row Build (pending) / Rebuild (built) button
    column 2  the status text, colour-coded

[+] / [-] add and remove guides. The panel only manages rows and emits intent
signals; main_ui owns the naming, the creation params and the build calls.
"""

from __future__ import annotations

from functools import partial

from dw_maya.DynForge.forge_cmds.compat import (
    QtCore, QtGui, QtWidgets, Qt, Signal,
)
from dw_maya.DynForge.forge_cmds.icons import make_mode_icon
from dw_maya.DynForge.wgt_base import DynForgeWidgetBase


class GuideListPanel(DynForgeWidgetBase):
    """Guide rows with add / remove and per-row build."""

    GUIDE_ROLE = Qt.UserRole + 1

    add_requested       = Signal()
    remove_requested    = Signal(object)
    build_requested     = Signal(object)
    build_all_requested = Signal()
    load_requested      = Signal()
    selection_changed   = Signal(object)

    _STATUS_COLOR = {
        "pending": QtGui.QColor("#d9a441"),
        "built":   QtGui.QColor("#6ab04c"),
        "broken":  QtGui.QColor("#c0392b"),
    }

    def __init__(self,
                 hub,
                 parent=None,) -> None:
        super().__init__(hub, parent)
        self._build_ui()

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        self._view  = QtWidgets.QTreeView()
        self._model = QtGui.QStandardItemModel(self)
        self._model.setHorizontalHeaderLabels(["Name", "Build", "Status"])
        self._proxy = QtCore.QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._view.setModel(self._proxy)
        self._view.setRootIsDecorated(False)
        self._view.setAllColumnsShowFocus(True)
        self._view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        header = self._view.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        layout.addWidget(self._view, stretch=1)

        btn_row = QtWidgets.QHBoxLayout()
        self._add_btn    = QtWidgets.QPushButton("+")
        self._remove_btn = QtWidgets.QPushButton("-")
        for btn in (self._add_btn, self._remove_btn):
            btn.setMaximumWidth(30)
            btn_row.addWidget(btn)
        self._load_btn = QtWidgets.QPushButton("Load...")
        self._load_btn.setToolTip("Load a guide system from a file or from the scene.")
        btn_row.addWidget(self._load_btn)
        btn_row.addStretch(1)
        self._build_all_btn = QtWidgets.QPushButton("(Re-)build all")
        btn_row.addWidget(self._build_all_btn)
        layout.addLayout(btn_row)

        self._add_btn.clicked.connect(self.add_requested.emit)
        self._remove_btn.clicked.connect(self._on_remove)
        self._load_btn.clicked.connect(self.load_requested.emit)
        self._build_all_btn.clicked.connect(self.build_all_requested.emit)
        self._view.selectionModel().selectionChanged.connect(self._on_selection_changed)

    # -- Public -----------------------------------------------------------

    def existing_names(self) -> list:
        """Names of all guides currently in the list (for unique naming)."""
        names = []
        for row in range(self._model.rowCount()):
            guide = self._model.item(row, 0).data(self.GUIDE_ROLE)
            if guide is not None:
                names.append(guide.name)
        return names

    def all_guides(self) -> list:
        """Every guide currently in the list, top to bottom."""
        guides = []
        for row in range(self._model.rowCount()):
            guide = self._model.item(row, 0).data(self.GUIDE_ROLE)
            if guide is not None:
                guides.append(guide)
        return guides

    def clear(self) -> None:
        """Remove all rows (UI only - does not touch the scene)."""
        self._model.removeRows(0, self._model.rowCount())
        self._refresh_row_widgets()

    def add_guide(self,
                  guide,) -> None:
        """Append a guide as a new row and select it."""
        name_item = QtGui.QStandardItem()
        name_item.setEditable(False)
        name_item.setData(guide, self.GUIDE_ROLE)
        build_item  = QtGui.QStandardItem()
        build_item.setEditable(False)
        status_item = QtGui.QStandardItem()
        status_item.setEditable(False)
        self._model.appendRow([name_item, build_item, status_item])
        self._refresh_row(name_item.row())
        self._refresh_row_widgets()

        proxy_idx = self._proxy.mapFromSource(name_item.index())
        self._view.setCurrentIndex(proxy_idx)

    def refresh_guide(self,
                      guide,) -> None:
        """Refresh the row showing `guide` (icon / status / button label)."""
        row = self._row_of(guide)
        if row is not None:
            self._refresh_row(row)
            self._refresh_row_widgets()

    # -- Logic ------------------------------------------------------------

    def _row_of(self,
                guide,):
        for row in range(self._model.rowCount()):
            if self._model.item(row, 0).data(self.GUIDE_ROLE) is guide:
                return row
        return None

    def _selected_guide(self):
        indexes = self._view.selectionModel().selectedIndexes()
        if not indexes:
            return None
        source_index = self._proxy.mapToSource(indexes[0])
        item = self._model.item(source_index.row(), 0)
        return item.data(self.GUIDE_ROLE) if item is not None else None

    def _on_remove(self) -> None:
        guide = self._selected_guide()
        if guide is None:
            return
        row = self._row_of(guide)
        self.remove_requested.emit(guide)
        if row is not None:
            self._model.removeRow(row)
            self._refresh_row_widgets()

    def _on_selection_changed(self,
                              *args,) -> None:
        self.selection_changed.emit(self._selected_guide())

    def _refresh_row(self,
                     row: int,) -> None:
        name_item   = self._model.item(row, 0)
        status_item = self._model.item(row, 2)
        guide       = name_item.data(self.GUIDE_ROLE)
        if guide is None:
            return
        status = guide.status.value
        name_item.setText(guide.name)
        name_item.setIcon(make_mode_icon(getattr(guide, "mode", "edge"), status))
        name_item.setToolTip(f"{guide.label}  -  {status}")
        status_item.setText(status)
        color = self._STATUS_COLOR.get(status)
        if color is not None:
            status_item.setForeground(color)

    def _refresh_row_widgets(self) -> None:
        """(Re)install the per-row Build/Rebuild button in column 1."""
        for row in range(self._model.rowCount()):
            guide = self._model.item(row, 0).data(self.GUIDE_ROLE)
            if guide is None:
                continue
            proxy_idx = self._proxy.mapFromSource(self._model.index(row, 1))
            btn = self._view.indexWidget(proxy_idx)
            if btn is None:
                btn = QtWidgets.QPushButton()
                self._view.setIndexWidget(proxy_idx, btn)
            btn.setText("Rebuild" if guide.status.value == "built" else "Build")
            try:
                btn.clicked.disconnect()
            except (RuntimeError, TypeError):
                pass
            btn.clicked.connect(partial(self.build_requested.emit, guide))