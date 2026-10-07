"""
wgt_install_panel.py - DynForge "Install" tab.

Guides grouped by install unit (ForgeHost.install_unit: a studio part / prop,
default the registered mesh's top group), with per guide its install state, the
target it installs under (ForgeHost.describe_target) and its setup home.

Actions work on the selected units / guides (a unit row = all its guides;
nothing selected = everything, after a confirm):
    Install     place the chains (+ the weights when "with skin" is checked)
    Uninstall   weights off the skin, chains back into their guide groups
    Cleanup     tidy only: split preview, clip gizmos, empty setup groups
    Save JSON   one file per unit

The panel only builds the view and emits intent signals; main_ui runs them.
"""

from __future__ import annotations

import functools

from dw_maya.DynForge.forge_cmds.compat import QtCore, QtGui, QtWidgets, Qt, Signal
from dw_maya.DynForge import forge_host
from dw_maya.DynForge.wgt_base import DynForgeWidgetBase

_GUIDE_ROLE = Qt.UserRole + 1
_UNIT_ROLE  = Qt.UserRole + 2
_COL_TARGET, _COL_HOME = 2, 3
# Install-tab columns whose cell can be a combo (ForgeHost.install_choices).
_CHOICE_COLUMNS = {_COL_TARGET: "target", _COL_HOME: "home"}

_STATE_COLOR = {
    "installed": QtGui.QColor("#4aa3df"),
    "ready":     QtGui.QColor("#6ab04c"),
    "needs:":    QtGui.QColor("#d9a441"),
}


def guide_state(guide,
                with_skin: bool,) -> str:
    """Install state / readiness of a guide, as shown in the tab."""
    if getattr(guide, "installed", False):
        return "installed" if getattr(guide, "skin_installed", False) else "installed (no skin)"
    if guide.status.value != "built":
        return "needs: build"
    if not getattr(guide, "parent_bone", None):
        return "needs: parent bone"
    if with_skin:
        if not getattr(guide, "skin_cluster", None):
            return "needs: skin"
        if not getattr(guide, "source_influences", None):
            return "needs: donor"
    return "ready"


class _ChoiceDelegate(QtWidgets.QStyledItemDelegate):
    """
    Combo editor on a guide's Target / Home cell, filled by the host
    (ForgeHost.install_choices). The pick is handed back to the host
    (set_install_choice) as soon as it is made - no second click to commit -
    and the panel rebuilds once the editor is closed, never from inside it.
    An installed guide, or a host with nothing to offer, gets no editor.
    """

    def __init__(self,
                 panel,) -> None:
        super().__init__(panel)
        self._panel = panel

    def createEditor(self, parent, option, index):
        guide = self._panel.guide_at(index)
        column = _CHOICE_COLUMNS.get(index.column())
        if guide is None or column is None or getattr(guide, "installed", False):
            return None
        options, current = forge_host.get_host().install_choices(guide, column)
        if not options:
            return None
        combo = QtWidgets.QComboBox(parent)
        combo.addItems(options)
        if current in options:
            combo.setCurrentIndex(options.index(current))
        combo.activated.connect(functools.partial(self._commit, combo))
        QtCore.QTimer.singleShot(0, combo.showPopup)
        return combo

    def setEditorData(self, editor, index) -> None:
        """The combo is filled in createEditor; nothing to read back from the item."""

    def setModelData(self, editor, model, index) -> None:
        guide = self._panel.guide_at(index)
        column = _CHOICE_COLUMNS.get(index.column())
        if guide is not None and column is not None:
            forge_host.get_host().set_install_choice(guide, column, editor.currentText())
        QtCore.QTimer.singleShot(0, self._panel.refresh)

    def _commit(self,
                combo,
                _index: int = 0,) -> None:
        self.commitData.emit(combo)
        self.closeEditor.emit(combo, QtWidgets.QAbstractItemDelegate.NoHint)


class InstallPanel(DynForgeWidgetBase):
    """Install units -> guides, with install / uninstall / cleanup / JSON per selection."""

    install_requested   = Signal(object, bool)   # guides, with_skin
    uninstall_requested = Signal(object)         # guides
    cleanup_requested   = Signal(object)         # guides
    save_json_requested = Signal(object, str)    # guides, default file stem (the unit)

    def __init__(self,
                 hub,
                 context,
                 parent=None,) -> None:
        super().__init__(hub, parent)
        self._context = context
        self._build_ui()
        self._context.guides_changed.connect(self.refresh)

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        # Host options (filled by main_ui) + with skin + refresh
        top = QtWidgets.QHBoxLayout()
        self.options_row = QtWidgets.QHBoxLayout()
        top.addLayout(self.options_row)
        top.addStretch(1)
        self.with_skin_cb = QtWidgets.QCheckBox("with skin")
        self.with_skin_cb.setToolTip(
            "On: also transfer the weights (per skinCluster, from the original skin backup).\n"
            "Off: only place the chains in the rig - the skin is left untouched.")
        top.addWidget(self.with_skin_cb)
        self._refresh_btn = QtWidgets.QPushButton("Refresh")
        top.addWidget(self._refresh_btn)
        layout.addLayout(top)

        self._tree = QtWidgets.QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels(["Unit / guide", "State", "Target", "Home"])
        self._tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._tree.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        header = self._tree.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        self._choice_delegate = _ChoiceDelegate(self)
        self._tree.setItemDelegateForColumn(_COL_TARGET, self._choice_delegate)
        self._tree.setItemDelegateForColumn(_COL_HOME, self._choice_delegate)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._tree, stretch=1)

        hint = QtWidgets.QLabel("Acts on the selected units / guides - nothing selected = everything.")
        hint.setStyleSheet("color: #888;")
        layout.addWidget(hint)

        buttons = QtWidgets.QHBoxLayout()
        self._install_btn   = QtWidgets.QPushButton("Install")
        self._uninstall_btn = QtWidgets.QPushButton("Uninstall")
        self._cleanup_btn   = QtWidgets.QPushButton("Cleanup")
        self._cleanup_btn.setToolTip("Tidy: delete the split preview, the clip gizmos and empty setup groups. "
                                     "Points, curves and recipes stay.")
        self._json_btn      = QtWidgets.QPushButton("Save JSON")
        self._json_btn.setToolTip("One JSON file per unit.")
        for btn in (self._install_btn, self._uninstall_btn, self._cleanup_btn, self._json_btn):
            buttons.addWidget(btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._refresh_btn.clicked.connect(self.refresh)
        self.with_skin_cb.toggled.connect(self.refresh)
        self._install_btn.clicked.connect(self._on_install)
        self._uninstall_btn.clicked.connect(self._on_uninstall)
        self._cleanup_btn.clicked.connect(self._on_cleanup)
        self._json_btn.clicked.connect(self._on_save_json)

    # -- View -------------------------------------------------------------

    def _units(self,
               guides: list,) -> list:
        """[(key, label, [guides])] in first-seen order."""
        host = forge_host.get_host()
        order, units = [], {}
        for guide in guides:
            try:
                key, label = host.install_unit(guide)
            except Exception:
                key, label = "", "unassigned"
            if key not in units:
                units[key] = (label, [])
                order.append(key)
            units[key][1].append(guide)
        return [(key, units[key][0], units[key][1]) for key in order]

    def refresh(self, *args) -> None:
        host = forge_host.get_host()
        with_skin = self.with_skin_cb.isChecked()
        self._tree.clear()
        for key, label, guides in self._units(self._context.all_guides()):
            states = [guide_state(g, with_skin) for g in guides]
            n_installed = sum(1 for s in states if s.startswith("installed"))
            unit_item = QtWidgets.QTreeWidgetItem(
                [label, f"{n_installed}/{len(guides)} installed", "", ""])
            unit_item.setData(0, _UNIT_ROLE, key)
            font = unit_item.font(0)
            font.setBold(True)
            unit_item.setFont(0, font)
            unit_item.setToolTip(0, key or "guides without a registered mesh")
            self._tree.addTopLevelItem(unit_item)
            for guide, state in zip(guides, states):
                try:
                    target = host.describe_target(guide)
                except Exception as e:
                    target = f"? ({e})"
                home = getattr(guide, "setup_home", None) or getattr(guide, "setup", None) or "-"
                home_text, home_tip = home.split("|")[-1], home
                try:
                    home_options, home_current = host.install_choices(guide, "home")
                except Exception:
                    home_options, home_current = [], ""
                if home_options:   # the container, not the dwForge_GRP inside it
                    home_text = home_current
                item = QtWidgets.QTreeWidgetItem([guide.name, state, target, home_text])
                item.setData(0, _GUIDE_ROLE, guide)
                item.setFlags(item.flags() | Qt.ItemIsEditable)   # only the delegate's columns open an editor
                installed = getattr(guide, "installed", False)
                for column, tip in ((_COL_TARGET, target), (_COL_HOME, home_tip)):
                    if self._has_choices(host, guide, _CHOICE_COLUMNS[column]):
                        tip += ("\n(installed - uninstall to change it)" if installed
                                else "\nDouble-click to pick another one.")
                    item.setToolTip(column, tip)
                color = _STATE_COLOR.get(state.split(" ")[0])
                if color is not None:
                    item.setForeground(1, color)
                unit_item.addChild(item)
            unit_item.setExpanded(True)

    @staticmethod
    def _has_choices(host,
                     guide,
                     column: str,) -> bool:
        try:
            return bool(host.install_choices(guide, column)[0])
        except Exception:
            return False

    def guide_at(self,
                 index,):
        """The guide of the row at a model index (None for a unit row)."""
        item = self._tree.itemFromIndex(index)
        return item.data(0, _GUIDE_ROLE) if item is not None else None

    def _on_double_click(self,
                         item,
                         column: int,) -> None:
        """Target / Home cell: open the delegate's combo (the other cells are not editable)."""
        if column in _CHOICE_COLUMNS and item.data(0, _GUIDE_ROLE) is not None:
            self._tree.editItem(item, column)

    # -- Selection --------------------------------------------------------

    def _selected_guides(self) -> list:
        """Guides of the selected rows (a unit row = all its guides); empty when nothing is selected."""
        picked = []
        for item in self._tree.selectedItems():
            guide = item.data(0, _GUIDE_ROLE)
            if guide is not None:
                picked.append(guide)
                continue
            for i in range(item.childCount()):
                child = item.child(i).data(0, _GUIDE_ROLE)
                if child is not None:
                    picked.append(child)
        seen, ordered = set(), []
        for guide in picked:
            if id(guide) not in seen:
                seen.add(id(guide))
                ordered.append(guide)
        return ordered

    def _targets(self,
                 action: str,) -> list:
        """Selected guides, or every guide after a confirm when nothing is selected."""
        guides = self._selected_guides()
        if guides:
            return guides
        everything = self._context.all_guides()
        if not everything:
            return []
        reply = QtWidgets.QMessageBox.question(
            self, "DynForge", f"Nothing selected: {action} all {len(everything)} guide(s)?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        return everything if reply == QtWidgets.QMessageBox.Yes else []

    # -- Actions ----------------------------------------------------------

    def _on_install(self) -> None:
        guides = self._targets("install")
        if guides:
            self.install_requested.emit(guides, self.with_skin_cb.isChecked())

    def _on_uninstall(self) -> None:
        guides = self._targets("uninstall")
        if guides:
            self.uninstall_requested.emit(guides)

    def _on_cleanup(self) -> None:
        guides = self._targets("clean up")
        if guides:
            self.cleanup_requested.emit(guides)

    def _on_save_json(self) -> None:
        guides = self._targets("save")
        for key, label, unit_guides in self._units(guides):
            self.save_json_requested.emit(unit_guides, label)
