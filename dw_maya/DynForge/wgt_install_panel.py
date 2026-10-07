"""
wgt_install_panel.py - DynForge "Install" tab.

Guides grouped by install unit (ForgeHost.install_unit: a studio part / prop,
default the registered mesh's top group), with per guide its install state,
whether it installs with its skin weights (a checkbox - each guide decides; the
top "with skin" box is only the default given to new guides), the target it
installs under (ForgeHost.describe_target) and its setup home.

Changing the skin flag, the target or the home of an INSTALLED guide asks
"Reinstall now?": yes reinstalls it (uninstall + install), no leaves it marked
"reinstall pending" so the rig never silently disagrees with the tab.

Actions work on the selected units / guides (a unit row = all its guides;
nothing selected = everything, after a confirm):
    Install     place the chains (+ the weights of the guides ticked "Skin")
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
_COL_NAME, _COL_STATE, _COL_SKIN, _COL_TARGET, _COL_HOME = range(5)
# Install-tab columns whose cell can be a combo (ForgeHost.install_choices).
_CHOICE_COLUMNS = {_COL_TARGET: "target", _COL_HOME: "home"}

_STATE_COLOR = {
    "installed": QtGui.QColor("#4aa3df"),
    "ready":     QtGui.QColor("#6ab04c"),
    "needs:":    QtGui.QColor("#d9a441"),
}
_PENDING_COLOR = QtGui.QColor("#e8a33d")


def guide_state(guide) -> str:
    """Install state / readiness of a guide, as shown in the tab (its own skin flag decides what it needs)."""
    if getattr(guide, "installed", False):
        state = "installed" if getattr(guide, "skin_installed", False) else "installed (no skin)"
        if getattr(guide, "reinstall_pending", False):
            state += " - reinstall pending"
        return state
    if guide.status.value != "built":
        return "needs: build"
    if not getattr(guide, "parent_bone", None):
        return "needs: parent bone"
    if getattr(guide, "with_skin", True):
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
    and the panel follows up once the editor is closed, never from inside it:
    an installed guide is offered a reinstall. A host with nothing to offer
    gets no editor.
    """

    def __init__(self,
                 panel,) -> None:
        super().__init__(panel)
        self._panel = panel

    def createEditor(self, parent, option, index):
        guide = self._panel.guide_at(index)
        column = _CHOICE_COLUMNS.get(index.column())
        if guide is None or column is None:
            return None
        options, current = forge_host.get_host().install_choices(guide, column)
        if not options:
            return None
        combo = QtWidgets.QComboBox(parent)
        combo.addItems(options)
        if current in options:
            combo.setCurrentIndex(options.index(current))
        combo.setProperty("dwForgeInitial", combo.currentText())
        combo.activated.connect(functools.partial(self._commit, combo))
        QtCore.QTimer.singleShot(0, combo.showPopup)
        return combo

    def setEditorData(self, editor, index) -> None:
        """The combo is filled in createEditor; nothing to read back from the item."""

    def setModelData(self, editor, model, index) -> None:
        guide = self._panel.guide_at(index)
        column = _CHOICE_COLUMNS.get(index.column())
        if guide is None or column is None:
            return
        if editor.currentText() == editor.property("dwForgeInitial"):
            return   # picked what it already was: nothing to do
        forge_host.get_host().set_install_choice(guide, column, editor.currentText())
        QtCore.QTimer.singleShot(0, functools.partial(self._panel.install_setting_changed, guide))

    def _commit(self,
                combo,
                _index: int = 0,) -> None:
        self.commitData.emit(combo)
        self.closeEditor.emit(combo, QtWidgets.QAbstractItemDelegate.NoHint)


class InstallPanel(DynForgeWidgetBase):
    """Install units -> guides, with install / uninstall / cleanup / JSON per selection."""

    install_requested   = Signal(object)         # guides (each with its own skin flag)
    reinstall_requested = Signal(object)         # guides: uninstall + install
    uninstall_requested = Signal(object)         # guides
    cleanup_requested   = Signal(object)         # guides
    save_json_requested = Signal(object, str)    # guides, default file stem (the unit)

    def __init__(self,
                 hub,
                 context,
                 parent=None,) -> None:
        super().__init__(hub, parent)
        self._context = context
        self._filling = False
        self._build_ui()
        self._context.guides_changed.connect(self.refresh)

    # -- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        # Host options (filled by main_ui) + default skin flag + refresh
        top = QtWidgets.QHBoxLayout()
        self.options_row = QtWidgets.QHBoxLayout()
        top.addLayout(self.options_row)
        top.addStretch(1)
        self.with_skin_cb = QtWidgets.QCheckBox("with skin (new guides)")
        self.with_skin_cb.setToolTip(
            "The Skin flag given to new guides. Each guide then has its own, in the Skin column:\n"
            "on = install also transfers its weights, off = only place it (joints at weight 0, locked).")
        top.addWidget(self.with_skin_cb)
        self._refresh_btn = QtWidgets.QPushButton("Refresh")
        top.addWidget(self._refresh_btn)
        layout.addLayout(top)

        self._tree = QtWidgets.QTreeWidget()
        self._tree.setColumnCount(5)
        self._tree.setHeaderLabels(["Unit / guide", "State", "Skin", "Target", "Home"])
        self._tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._tree.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        header = self._tree.header()
        header.setSectionResizeMode(_COL_NAME, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_STATE, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_SKIN, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_TARGET, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_HOME, QtWidgets.QHeaderView.ResizeToContents)
        self._choice_delegate = _ChoiceDelegate(self)
        self._tree.setItemDelegateForColumn(_COL_TARGET, self._choice_delegate)
        self._tree.setItemDelegateForColumn(_COL_HOME, self._choice_delegate)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.itemChanged.connect(self._on_item_changed)
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
        self._filling = True
        self._tree.clear()
        for key, label, guides in self._units(self._context.all_guides()):
            states = [guide_state(g) for g in guides]
            n_installed = sum(1 for s in states if s.startswith("installed"))
            unit_item = QtWidgets.QTreeWidgetItem(
                [label, f"{n_installed}/{len(guides)} installed", "", "", ""])
            unit_item.setData(0, _UNIT_ROLE, key)
            font = unit_item.font(0)
            font.setBold(True)
            unit_item.setFont(0, font)
            unit_item.setToolTip(0, key or "guides without a registered mesh")
            self._tree.addTopLevelItem(unit_item)
            for guide, state in zip(guides, states):
                unit_item.addChild(self._guide_item(host, guide, state))
            unit_item.setExpanded(True)
        self._filling = False

    def _guide_item(self,
                    host,
                    guide,
                    state: str,):
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
        item = QtWidgets.QTreeWidgetItem([guide.name, state, "", target, home_text])
        item.setData(0, _GUIDE_ROLE, guide)
        # Editable for the delegate's columns (the others open no editor), checkable for Skin.
        item.setFlags(item.flags() | Qt.ItemIsEditable | Qt.ItemIsUserCheckable)
        item.setCheckState(_COL_SKIN, Qt.Checked if getattr(guide, "with_skin", True) else Qt.Unchecked)
        installed = getattr(guide, "installed", False)
        skin_tip = "Install transfers this guide's weights too" if getattr(guide, "with_skin", True) \
            else "Install only places this guide (joints at weight 0, locked)"
        if installed:
            skin_tip += "\n(installed - changing it offers a reinstall)"
        item.setToolTip(_COL_SKIN, skin_tip)
        for column, tip in ((_COL_TARGET, target), (_COL_HOME, home_tip)):
            if self._has_choices(host, guide, _CHOICE_COLUMNS[column]):
                tip += "\nDouble-click to pick another one" + (" (installed: offers a reinstall)." if installed
                                                               else ".")
            item.setToolTip(column, tip)
        if "pending" in state:
            item.setForeground(_COL_STATE, _PENDING_COLOR)
            item.setToolTip(_COL_STATE, "Its skin flag / target / home changed since it was installed - "
                                        "Install it again (or Uninstall + Install) to apply.")
        else:
            color = _STATE_COLOR.get(state.split(" ")[0])
            if color is not None:
                item.setForeground(_COL_STATE, color)
        return item

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

    def _on_item_changed(self,
                         item,
                         column: int,) -> None:
        """The Skin checkbox: the guide's own flag (read back off the item, not trusted from the signal)."""
        if self._filling or column != _COL_SKIN:
            return
        guide = item.data(0, _GUIDE_ROLE)
        if guide is None:
            return
        checked = item.checkState(_COL_SKIN) == Qt.Checked
        if checked == getattr(guide, "with_skin", True):
            return
        guide.with_skin = checked
        guide.store_recipe()
        # Followed up outside the item signal (the follow-up rebuilds the tree).
        QtCore.QTimer.singleShot(0, functools.partial(self.install_setting_changed, guide))

    def install_setting_changed(self,
                                guide,) -> None:
        """
        A setting that decides how a guide installs changed (skin flag, target,
        home). Not installed: nothing to do but redraw. Installed: offer the
        reinstall now; declined, the guide is marked pending so the tab says the
        rig does not match it yet.
        """
        if getattr(guide, "installed", False):
            reply = QtWidgets.QMessageBox.question(
                self, "DynForge",
                f"{guide.name} is installed. Reinstall it now so the change applies?\n\n"
                "No: it stays as installed, marked 'reinstall pending'.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if reply == QtWidgets.QMessageBox.Yes:
                self.reinstall_requested.emit([guide])
                return
            guide.reinstall_pending = True
            guide.store_recipe()
        self.refresh()

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
            self.install_requested.emit(guides)

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
