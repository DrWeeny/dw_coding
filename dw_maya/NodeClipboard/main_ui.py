"""
main_ui.py - NodeClipboard window.

Summary:
    Copy a selection out of one Maya session and paste it into another,
    choosing what comes along. Copy captures a complete ``dw_preset`` entry
    into the shared clipboard folder; paste rebuilds it here.

    The window has two faces. **Simple** (the default) is two big buttons and
    one checkbox per component: Copy takes the selection, Paste rebuilds the
    newest entry into the current namespace - no entry list, no per-node
    decisions. **Advanced** unfolds the entry list, the node x component tree
    and the namespace options, for what the simple face cannot express
    (paste an older entry, keep one node out, retarget a namespace, remap an
    external asset).

Features:
    - The component bar and the tree are one state: a bar toggle drives that
      whole column in the tree, the tree pushes its aggregate back. Switching
      faces never changes what a paste would do.
    - Copy names the entry from the selection unless a name is typed
      (advanced), and the entry list always lands on the newest one - so the
      simple path is copy here, paste there.
    - Copy walks into the selected groups (advanced: "With hierarchy"), so a
      whole COLLIDERS group travels without picking every node inside it.

Classes:
    NodeClipboardUI

Functions:
    launch

Example:
    import dw_maya.NodeClipboard as node_clipboard
    node_clipboard.launch()

Author:
    DrWeeny
"""

import functools
import os
import subprocess
import sys
from typing import Optional

from dw_maya.NodeClipboard.compat import (QtWidgets, Qt, QAction,
                                          QActionGroup, wrapInstance, qt_exec)
import dw_maya.NodeClipboard.clipboard_cmds as clipboard_cmds
from dw_maya.NodeClipboard.wgt_entry_tree import EntryTree
from dw_maya.NodeClipboard.wgt_component_bar import ComponentBar
from dw_maya.NodeClipboard.wgt_paste_options import PasteOptions
from dw_logger import get_logger

logger = get_logger()

_window = None


class NodeClipboardUI(QtWidgets.QWidget):
    """Copy / paste nodes between Maya sessions, component by component."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super(NodeClipboardUI, self).__init__(parent)
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle("NodeClipboard")
        self.setObjectName("dwNodeClipboardUI")

        self._build_ui()
        self._connect_ui()
        # Expire stale entries before the list is read, so a week-old entry
        # never shows up as the newest one waiting to be pasted.
        self.run_cleanup(announce=False)
        self.refresh_entries()
        self.set_advanced(False)

    # -- construction -------------------------------------------------------

    def _build_menu(self) -> QtWidgets.QMenuBar:
        """Build the menu bar: Preferences > Cleanup delay."""
        menu_bar = QtWidgets.QMenuBar(self)
        prefs = menu_bar.addMenu("Preferences")

        self.cleanup_menu = prefs.addMenu("Cleanup delay")
        self.cleanup_menu.setToolTip("How long an entry stays on the "
                                     "clipboard before it is dropped.")
        self.cleanup_group = QActionGroup(self)
        self.cleanup_group.setExclusive(True)
        current = clipboard_cmds.cleanup_hours()
        for label, hours in clipboard_cmds.CLEANUP_CHOICES:
            # Held by the group and the menu, but named here too: a QAction
            # left unreferenced can be collected before Qt takes ownership.
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(hours == current)
            action.triggered.connect(
                functools.partial(self._set_cleanup_hours, hours))
            self.cleanup_group.addAction(action)
            self.cleanup_menu.addAction(action)

        prefs.addSeparator()
        self.cleanup_now_action = QAction("Run cleanup now", self)
        self.cleanup_now_action.triggered.connect(self._on_cleanup_now)
        prefs.addAction(self.cleanup_now_action)
        self.folder_action = QAction("Open clipboard folder", self)
        self.folder_action.triggered.connect(self.open_folder)
        prefs.addAction(self.folder_action)
        return menu_bar

    def _build_ui(self) -> None:
        self.copy_btn = QtWidgets.QPushButton("Copy")
        self.copy_btn.setMinimumHeight(44)
        self.copy_btn.setToolTip("Capture the selected nodes into the "
                                 "clipboard - every component, so the paste "
                                 "side keeps every choice.")
        self.paste_btn = QtWidgets.QPushButton("Paste")
        self.paste_btn.setMinimumHeight(44)
        self.paste_btn.setToolTip("Rebuild the checked components of the "
                                  "entry in this scene.")

        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(self.copy_btn)
        button_row.addWidget(self.paste_btn)

        self.entry_label = QtWidgets.QLabel("Clipboard is empty.")
        self.entry_label.setWordWrap(True)

        self.component_bar = ComponentBar()

        self.advanced_btn = QtWidgets.QPushButton("Advanced")
        self.advanced_btn.setCheckable(True)
        self.advanced_btn.setToolTip("Entry list, per-node components and "
                                     "namespace options.")

        advanced_row = QtWidgets.QHBoxLayout()
        advanced_row.addStretch(1)
        advanced_row.addWidget(self.advanced_btn)

        # -- advanced half --------------------------------------------------
        self.name_field = QtWidgets.QLineEdit()
        self.name_field.setPlaceholderText("entry name (empty = from selection)")
        self.hierarchy_check = QtWidgets.QCheckBox("With hierarchy")
        self.hierarchy_check.setChecked(True)
        self.hierarchy_check.setToolTip(
            "Copy everything under the selected nodes, so a group can be "
            "picked instead of each node inside it. Shapes are left out - "
            "their transform already carries them.")
        name_row = QtWidgets.QHBoxLayout()
        name_row.addWidget(QtWidgets.QLabel("Copy as"))
        name_row.addWidget(self.name_field, 1)
        name_row.addWidget(self.hierarchy_check)

        self.entry_list = QtWidgets.QListWidget()
        self.entry_list.setToolTip("Clipboard entries, newest first.")
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.delete_btn = QtWidgets.QPushButton("Delete")
        self.clear_btn = QtWidgets.QPushButton("Clear All")
        self.folder_btn = QtWidgets.QPushButton("Open Folder")
        self.folder_btn.setToolTip(clipboard_cmds.clipboard_location())

        entry_buttons = QtWidgets.QGridLayout()
        entry_buttons.addWidget(self.refresh_btn, 0, 0)
        entry_buttons.addWidget(self.delete_btn, 0, 1)
        entry_buttons.addWidget(self.clear_btn, 1, 0)
        entry_buttons.addWidget(self.folder_btn, 1, 1)

        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QtWidgets.QLabel("Entries"))
        left_layout.addWidget(self.entry_list, 1)
        left_layout.addLayout(entry_buttons)

        self.tree = EntryTree()
        self.all_btn = QtWidgets.QPushButton("Check All")
        self.none_btn = QtWidgets.QPushButton("Uncheck All")
        self.expand_btn = QtWidgets.QPushButton("Expand")
        self.expand_btn.setCheckable(True)

        check_row = QtWidgets.QHBoxLayout()
        check_row.addWidget(self.all_btn)
        check_row.addWidget(self.none_btn)
        check_row.addWidget(self.expand_btn)
        check_row.addStretch(1)

        self.options = PasteOptions()

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.tree, 1)
        right_layout.addLayout(check_row)
        right_layout.addWidget(self.options)

        self.splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.splitter.addWidget(left)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)

        self.advanced_panel = QtWidgets.QWidget()
        panel_layout = QtWidgets.QVBoxLayout(self.advanced_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addLayout(name_row)
        panel_layout.addWidget(self.splitter, 1)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setMenuBar(self._build_menu())
        layout.addLayout(button_row)
        layout.addWidget(self.entry_label)
        layout.addWidget(self.component_bar)
        layout.addLayout(advanced_row)
        layout.addWidget(self.advanced_panel, 1)
        layout.addWidget(self.status_label)

    def _connect_ui(self) -> None:
        self.copy_btn.clicked.connect(self.copy_selection)
        self.paste_btn.clicked.connect(self.paste_entry)
        self.advanced_btn.toggled.connect(self.set_advanced)
        self.component_bar.component_toggled.connect(self.tree.set_component)
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        self.delete_btn.clicked.connect(self.delete_entry)
        self.clear_btn.clicked.connect(self.clear_entries)
        self.folder_btn.clicked.connect(self.open_folder)
        self.entry_list.currentTextChanged.connect(self.load_entry)
        self.tree.selection_changed.connect(self._on_tree_changed)
        self.all_btn.clicked.connect(self._on_check_all)
        self.none_btn.clicked.connect(self._on_uncheck_all)
        self.expand_btn.toggled.connect(self._on_expand_toggled)

    # Button slots taking no argument: clicked() carries a bool, which would
    # land in 'select' / 'checked' if the target were connected directly.
    def _on_refresh_clicked(self) -> None:
        self.refresh_entries()

    def _on_check_all(self) -> None:
        self.tree.set_all(True)

    def _on_uncheck_all(self) -> None:
        self.tree.set_all(False)

    def _on_expand_toggled(self, expanded: bool = False) -> None:
        if expanded:
            self.tree.expandAll()
        else:
            self.tree.collapseAll()
        self.expand_btn.setText("Collapse" if expanded else "Expand")

    # -- faces --------------------------------------------------------------

    def set_advanced(self, advanced: bool = False) -> None:
        """Fold the entry list / tree / namespace options in or out.

        The component bar stays visible in both: it is the same state as the
        tree, and hiding it would leave the simple face with no way to see -
        or change - what a paste carries.
        """
        self.advanced_panel.setVisible(advanced)
        if self.advanced_btn.isChecked() != advanced:
            self.advanced_btn.blockSignals(True)
            self.advanced_btn.setChecked(advanced)
            self.advanced_btn.blockSignals(False)
        self.advanced_btn.setText("Advanced (hide)" if advanced else "Advanced")
        if advanced:
            self.resize(max(self.width(), 780), 620)
        else:
            # Let the window shrink back around the two buttons: a hidden
            # child still reports its size hint through the layout until the
            # pending resize is processed.
            self.layout().activate()
            self.resize(max(self.width(), 380), self.minimumSizeHint().height())

    # -- entries ------------------------------------------------------------

    def current_entry(self) -> str:
        """Name of the selected clipboard entry ('' when none)."""
        item = self.entry_list.currentItem()
        return item.text() if item is not None else ""

    def refresh_entries(self, select: str = "") -> None:
        """Re-read the clipboard folder; land on ``select`` or the newest."""
        previous = select or self.current_entry()
        self.entry_list.blockSignals(True)
        self.entry_list.clear()
        entries = clipboard_cmds.list_entries()
        self.entry_list.addItems(entries)
        self.entry_list.blockSignals(False)
        if previous in entries:
            self.entry_list.setCurrentRow(entries.index(previous))
        elif entries:
            self.entry_list.setCurrentRow(0)
        else:
            self.load_entry("")

    def load_entry(self, name: str = "") -> None:
        """Show one entry in the tree, the component bar and the options."""
        info = clipboard_cmds.entry_info(name) if name else {}
        self.options.refresh_namespaces()
        self.options.set_entry(info)
        self.tree.set_entry(info)
        self.component_bar.set_keys(self.tree.component_keys())
        self.component_bar.set_states(self.tree.component_states())
        if not info:
            self.entry_label.setText("Clipboard is empty - copy a selection "
                                     "to fill it.")
            self.paste_btn.setEnabled(False)
            self.status_label.setText(
                f"Clipboard: {clipboard_cmds.clipboard_location()}")
            return
        self.paste_btn.setEnabled(True)
        node_count = len(info.get("nodes", {}))
        asset = (info.get("namespaces") or {}).get("asset") or []
        asset_txt = ", ".join(asset) if asset else "root"
        self.entry_label.setText(f"<b>{info['name']}</b> - {node_count} nodes "
                                 f"- saved {info['saved']} - from {asset_txt}")
        self._update_counts()

    def _on_tree_changed(self) -> None:
        self.component_bar.set_states(self.tree.component_states())
        self._update_counts()

    def _update_counts(self) -> None:
        kept, total, slices = self.tree.counts()
        if not total:
            return
        self.status_label.setText(f"{kept}/{total} nodes, {slices} component "
                                  f"slices selected - clipboard: "
                                  f"{clipboard_cmds.clipboard_location()}")

    # -- actions ------------------------------------------------------------

    def copy_selection(self) -> None:
        """Capture the current Maya selection into a new entry."""
        nodes = clipboard_cmds.selected_nodes()
        if not nodes:
            self._warn("Copy", "Nothing selected.")
            return
        name = self.name_field.text().strip()
        entry = clipboard_cmds.sanitize_name(name) if name \
            else clipboard_cmds.default_entry_name(nodes)
        if entry in clipboard_cmds.list_entries() and not self._confirm(
                "Copy", f"'{entry}' already exists on the clipboard.\n"
                        f"Overwrite it?"):
            return
        expand = self.hierarchy_check.isChecked()
        path = clipboard_cmds.copy_selection(entry, nodes, expand=expand)
        if not path:
            self._warn("Copy", "Nothing was captured - see the script editor.")
            return
        logger.info(f"NodeClipboard: copied {len(nodes)} selected node(s) to "
                    f"'{entry}'{' with hierarchy' if expand else ''}")
        self.refresh_entries(select=entry)

    def paste_entry(self) -> None:
        """Rebuild the checked nodes / components in this scene."""
        name = self.current_entry()
        if not name:
            self._warn("Paste", "The clipboard is empty.")
            return
        include = self.tree.include()
        if not include:
            self._warn("Paste", "Nothing is checked.")
            return
        built = clipboard_cmds.paste_entry(
            name,
            include=include,
            target_ns=self.options.target_namespace(),
            create=self.options.create(),
            apply_external=self.options.apply_external(),
            ext_ns_map=self.options.ext_ns_map())
        logger.info(f"NodeClipboard: pasted '{name}' -> {len(built)} node(s)")
        self.status_label.setText(f"Pasted '{name}': {len(built)} node(s) "
                                  f"rebuilt.")

    def delete_entry(self) -> None:
        """Remove the selected entry from the clipboard folder."""
        name = self.current_entry()
        if not name:
            return
        if not self._confirm("Delete", f"Delete clipboard entry '{name}'?"):
            return
        clipboard_cmds.delete_entry(name)
        self.refresh_entries()

    def clear_entries(self) -> None:
        """Remove every entry from the clipboard folder."""
        entries = clipboard_cmds.list_entries()
        if not entries:
            return
        if not self._confirm("Clear All",
                             f"Delete all {len(entries)} clipboard entries?"):
            return
        removed = clipboard_cmds.clear_entries()
        logger.info(f"NodeClipboard: cleared {removed} entrie(s)")
        self.refresh_entries()

    def _set_cleanup_hours(self, hours: int = 24, checked: bool = True) -> None:
        """Menu slot - store the delay, then apply it right away."""
        clipboard_cmds.set_cleanup_hours(hours)
        logger.info(f"NodeClipboard: cleanup delay set to "
                    f"{clipboard_cmds.cleanup_label(hours)}")
        self.run_cleanup()

    def _on_cleanup_now(self) -> None:
        """Menu slot - triggered() carries a bool that isn't 'announce'."""
        self.run_cleanup()

    def run_cleanup(self, announce: bool = True) -> None:
        """Drop entries older than the cleanup delay and refresh the list."""
        removed = clipboard_cmds.run_cleanup()
        if removed:
            self.refresh_entries()
        if not announce:
            return
        delay = clipboard_cmds.cleanup_label()
        if removed:
            self.status_label.setText(f"Cleanup ({delay}): removed "
                                      f"{len(removed)} entrie(s) - "
                                      f"{', '.join(removed)}")
        else:
            self.status_label.setText(f"Cleanup ({delay}): nothing to remove.")

    def open_folder(self) -> None:
        """Open the clipboard folder in the OS file browser."""
        folder = clipboard_cmds.clipboard_location()
        if sys.platform.startswith("win"):
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    # -- helpers ------------------------------------------------------------

    def _warn(self, title: str = "", message: str = "") -> None:
        QtWidgets.QMessageBox.warning(self, f"NodeClipboard - {title}", message)

    def _confirm(self, title: str = "", message: str = "") -> bool:
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(f"NodeClipboard - {title}")
        box.setText(message)
        box.setStandardButtons(QtWidgets.QMessageBox.Yes |
                               QtWidgets.QMessageBox.No)
        box.setDefaultButton(QtWidgets.QMessageBox.No)
        return qt_exec(box) == QtWidgets.QMessageBox.Yes


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

def _maya_main_window():
    """Return Maya's main window as a QWidget, or None outside Maya."""
    try:
        import maya.OpenMayaUI as omui
    except ImportError:
        return None
    ptr = omui.MQtUtil.mainWindow()
    if ptr is None:
        return None
    return wrapInstance(int(ptr), QtWidgets.QWidget)


def launch():
    """Create (or re-show) the NodeClipboard window, parented to Maya."""
    global _window
    if _window is not None:
        try:
            _window.close()
            _window.deleteLater()
        except Exception:
            pass
        _window = None

    _window = NodeClipboardUI(parent=_maya_main_window())
    _window.show()
    return _window
