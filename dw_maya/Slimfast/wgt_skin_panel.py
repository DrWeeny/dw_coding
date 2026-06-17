"""SkinCluster influence list panel for Slimfast — complex panel demo.

This module demonstrates how to implement a non-trivial sub-panel using the
zone-based ``DeformerPanelBase`` API introduced in ``wgt_deformer_panel.py``.

What it shows
-------------
- ``@panel_for`` decorator for one-shot registration + capability declaration.
- ``build_body()`` returning a self-contained container widget; all widget
  construction and signal wiring happens inside that method.
- State attributes initialised *before* ``super().__init__()`` because the
  base class calls ``build_body()`` from its own ``__init__``.
- ``JointInfluenceModel`` / ``_LockDelegate`` / ``_InfluenceTreeView`` as a
  pattern for a model/view stack with a custom interaction column.
- ``_iter_all_items`` / ``_set_all_locks_recursive`` for DFS traversal of a
  ``QStandardItemModel`` tree.
- The ``blockSignals``-free pattern: ``item.setData()`` (QStandardItem method)
  bypasses the model override so bulk operations never push back to Maya.

Disabling
---------
Comment out the import in ``main_ui.py`` to remove the radio button and
revert skinCluster to the default panel::

    # from . import wgt_skin_panel   # comment = no SkinCluster radio button

Author: DrWeeny
"""

from __future__ import annotations

import math
import os
from typing import Dict, Generator, List, Optional, TYPE_CHECKING

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Signal, Slot, Qt
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Signal, Slot, Qt

from dw_ressources import get_icon_path
from dw_maya.Slimfast.wgt_deformer_panel import DeformerPanelBase, panel_for, register_deformer_panel
from dw_logger import get_logger

if TYPE_CHECKING:
    from dw_maya.dw_paint.protocol import WeightSource
    from dw_maya.Slimfast.cmds import SlimfastController

logger = get_logger()

# ---------------------------------------------------------------------------
# Data roles
# ---------------------------------------------------------------------------
_ROLE_FULL_PATH = Qt.UserRole        # str  : full DAG path
_ROLE_LOCKED    = Qt.UserRole + 1    # bool : .lockInfluenceWeights
_ROLE_IS_ACTIVE = Qt.UserRole + 2    # bool : currently active paint influence

_LOCK_COL_W = 26
_ROW_HEIGHT = 22

def _as_fs_path(value) -> str:
    """Return a Qt-friendly filesystem path string (handles pathlib paths)."""
    if not value:
        return ''
    return str(os.fspath(value))


_LOCK_ICON_PATH = _as_fs_path(get_icon_path("padlock_locked"))
_UNLOCK_ICON_PATH = _as_fs_path(get_icon_path("padlock_unlocked"))

# ---------------------------------------------------------------------------
# Model — lock_changed fires only via model.setData, not item.setData
# ---------------------------------------------------------------------------

class JointInfluenceModel(QtGui.QStandardItemModel):
    """One row (possibly with children) per influence joint.

    ``lock_changed`` fires ONLY when ``model.setData(_ROLE_LOCKED, ...)`` is
    called explicitly (lock column click, context menu, Lock All).
    ``item.setData()`` on a ``QStandardItem`` bypasses this override — used
    safely during populate and refresh so Maya is never called back.
    """

    lock_changed = Signal(str, bool)

    def setData(self,
                index: QtCore.QModelIndex,
                value,
                role: int = Qt.EditRole) -> bool:
        ok = super().setData(index, value, role)
        if ok and role == _ROLE_LOCKED:
            full_path = index.data(_ROLE_FULL_PATH)
            if full_path:
                self.lock_changed.emit(full_path, bool(value))
        return ok


# ---------------------------------------------------------------------------
# Delegate — lock glyph + joint name with colour coding
# ---------------------------------------------------------------------------

class _LockDelegate(QtWidgets.QStyledItemDelegate):
    """Renders each row:   [icon]  │  JointShortName

    Visual states
    -------------
    locked   → greyed name (#505050), dark row background
    active   → teal bold name (#4ecdc4)
    selected → palette highlight
    normal   → palette defaults
    """

    _ICON_SIZE = 14   # px — lock icon is scaled to this square

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        size = QtCore.QSize(self._ICON_SIZE, self._ICON_SIZE)
        self._px_locked   = (
            QtGui.QPixmap(_LOCK_ICON_PATH).scaled(
                size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if _LOCK_ICON_PATH else QtGui.QPixmap()
        )
        self._px_unlocked = (
            QtGui.QPixmap(_UNLOCK_ICON_PATH).scaled(
                size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            if _UNLOCK_ICON_PATH else QtGui.QPixmap()
        )

    def paint(self,
              painter: QtGui.QPainter,
              option: QtWidgets.QStyleOptionViewItem,
              index: QtCore.QModelIndex) -> None:
        painter.save()
        rect = option.rect

        locked    = bool(index.data(_ROLE_LOCKED))
        is_active = bool(index.data(_ROLE_IS_ACTIVE))
        selected  = bool(option.state & QtWidgets.QStyle.State_Selected)
        name      = index.data(Qt.DisplayRole) or ''

        # Background
        if selected:
            bg = option.palette.highlight().color()
        elif locked:
            bg = QtGui.QColor('#1c1c1c')
        else:
            bg = option.palette.base().color()
        painter.fillRect(rect, bg)

        # Lock icon — centred in the left column
        lock_rect = QtCore.QRect(rect.left(), rect.top(), _LOCK_COL_W, rect.height())
        pixmap    = self._px_locked if locked else self._px_unlocked
        if not pixmap.isNull():
            px = lock_rect.left() + (lock_rect.width()  - pixmap.width())  // 2
            py = lock_rect.top()  + (lock_rect.height() - pixmap.height()) // 2
            painter.setOpacity(0.55 if locked else 0.85)
            painter.drawPixmap(px, py, pixmap)
            painter.setOpacity(1.0)

        # Separator
        painter.setPen(QtGui.QColor('#2e2e2e'))
        painter.drawLine(rect.left() + _LOCK_COL_W, rect.top(),
                         rect.left() + _LOCK_COL_W, rect.bottom())

        # Joint name
        name_rect = QtCore.QRect(
            rect.left() + _LOCK_COL_W + 4, rect.top(),
            rect.width() - _LOCK_COL_W - 6, rect.height(),
        )
        if locked:
            name_color = QtGui.QColor('#505050')
        elif is_active:
            name_color = QtGui.QColor('#4ecdc4')
        elif selected:
            name_color = option.palette.highlightedText().color()
        else:
            name_color = option.palette.text().color()

        font = QtGui.QFont(option.font)
        font.setBold(is_active)
        painter.setFont(font)
        painter.setPen(name_color)
        painter.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft, name)

        painter.restore()

    def sizeHint(self,
                 option: QtWidgets.QStyleOptionViewItem,
                 index: QtCore.QModelIndex) -> QtCore.QSize:
        return QtCore.QSize(100, _ROW_HEIGHT)


# ---------------------------------------------------------------------------
# Tree view — lock-column click interception + context menu
# ---------------------------------------------------------------------------

class _InfluenceTreeView(QtWidgets.QTreeView):
    """QTreeView that routes lock-zone clicks to the model without triggering
    row selection, and exposes a right-click context menu for bulk lock ops.

    Lock-column interception
    ------------------------
    ``mousePressEvent`` checks if the click is within the left ``_LOCK_COL_W``
    pixels of the item's content rect (i.e. after the branch-indicator area).
    If so it toggles the lock via the model and returns early — Qt's selection
    machinery never fires, and the active row is preserved.

    Clicking the expand/collapse arrow returns an *invalid* index from
    ``indexAt``, so it falls through to ``super()`` correctly.
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.pos())
            if index.isValid():
                item_rect = self.visualRect(index)
                lock_rect = QtCore.QRect(
                    item_rect.left(), item_rect.top(),
                    _LOCK_COL_W, item_rect.height(),
                )
                if lock_rect.contains(event.pos()):
                    src_index, src_model = self._resolve(index)
                    locked = bool(src_index.data(_ROLE_LOCKED))
                    src_model.setData(src_index, not locked, _ROLE_LOCKED)
                    return   # consume — no selection change
        super().mousePressEvent(event)

    def _resolve(self, index: QtCore.QModelIndex):
        """Unwrap proxy → (source_index, source_model)."""
        proxy = self.model()
        if hasattr(proxy, 'mapToSource'):
            return proxy.mapToSource(index), proxy.sourceModel()
        return index, proxy

    @Slot(QtCore.QPoint)
    def _show_context_menu(self, pos: QtCore.QPoint) -> None:
        proxy = self.model()
        src_model = proxy.sourceModel() if hasattr(proxy, 'sourceModel') else proxy

        icon_lock   = QtGui.QIcon(_LOCK_ICON_PATH)   if _LOCK_ICON_PATH   else QtGui.QIcon()
        icon_unlock = QtGui.QIcon(_UNLOCK_ICON_PATH) if _UNLOCK_ICON_PATH else QtGui.QIcon()

        menu  = QtWidgets.QMenu(self)
        a_lock_all   = menu.addAction(icon_lock,   'Lock All')
        a_unlock_all = menu.addAction(icon_unlock, 'Unlock All')

        a_lock_sel = a_unlock_sel = None
        index = self.indexAt(pos)
        if index.isValid():
            menu.addSeparator()
            a_lock_sel   = menu.addAction(icon_lock,   'Lock Selected')
            a_unlock_sel = menu.addAction(icon_unlock, 'Unlock Selected')

        action = menu.exec_(self.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action is a_lock_all:
            _set_all_locks_recursive(src_model, src_model.invisibleRootItem(), True)
        elif action is a_unlock_all:
            _set_all_locks_recursive(src_model, src_model.invisibleRootItem(), False)
        elif action is a_lock_sel and index.isValid():
            si, sm = self._resolve(index)
            sm.setData(si, True, _ROLE_LOCKED)
        elif action is a_unlock_sel and index.isValid():
            si, sm = self._resolve(index)
            sm.setData(si, False, _ROLE_LOCKED)


# ---------------------------------------------------------------------------
# Module-level tree helpers
# ---------------------------------------------------------------------------

def _iter_all_items(
        root: QtGui.QStandardItem,
) -> Generator[QtGui.QStandardItem, None, None]:
    """DFS generator over all QStandardItem descendants of *root*."""
    for row in range(root.rowCount()):
        child = root.child(row)
        if child is not None:
            yield child
            yield from _iter_all_items(child)


def _set_all_locks_recursive(
        model: QtGui.QStandardItemModel,
        root: QtGui.QStandardItem,
        locked: bool,) -> None:
    """Call ``model.setData(_ROLE_LOCKED)`` on every descendant.

    Using ``model.setData()`` (not ``item.setData()``) so ``lock_changed``
    fires per joint and Maya is updated for each.
    """
    for item in _iter_all_items(root):
        model.setData(item.index(), locked, _ROLE_LOCKED)


# ---------------------------------------------------------------------------
# Adaptive-precision spin box
# ---------------------------------------------------------------------------

class _AdaptiveDoubleSpinBox(QtWidgets.QDoubleSpinBox):
    """Double spin box whose shown precision follows the entered value.

    A plain ``QDoubleSpinBox`` rounds input to its fixed ``decimals()`` — so with
    3 decimals, typing ``0.0005`` is lost.  Here ``decimals`` is set high enough
    to accept very small values, but ``textFromValue`` strips trailing zeros so
    the field stays compact and displays exactly the precision the user typed
    (``0.05`` shows ``0.05``, ``0.0005`` shows ``0.0005``).

    ``stepBy`` is magnitude-aware: one up/down nudge changes the value by one
    unit just below its leading digit, so stepping is useful at both ``0.5`` and
    ``0.0005`` instead of a single coarse step.
    """

    def textFromValue(self, value: float) -> str:
        s = f'{value:.{self.decimals()}f}'
        if '.' in s:
            s = s.rstrip('0').rstrip('.')
        return s or '0'

    def stepBy(self, steps: int) -> None:
        v = self.value()
        if v <= 0.0:
            step = self.singleStep()
        else:
            step = 10.0 ** (math.floor(math.log10(v)) - 1)
        self.setValue(v + steps * step)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class SkinPanel(DeformerPanelBase):
    """Influence tree panel for skinCluster — complex panel demo.

    Layout (inside the zone returned by build_body)::

        ┌──────────────────────────────────────┐
        │ [ Filter influences…              ✕ ]│
        ├──────────────────────────────────────┤
        │  ▼ 🔓 │ pelvis                        │
        │    ▼ 🔓 │ L_thigh                     │
        │       🔒 │ L_knee   ← locked           │
        │    🔓 │ spine_01                       │
        │    🔓 │ spine_02  ← active (teal)      │
        ├──────────────────────────────────────┤
        │ Right-click: Lock / Unlock     [ ↺ ] │
        └──────────────────────────────────────┘

    Design notes
    ------------
    * State attrs and the model/proxy are initialised BEFORE ``super().__init__``
      because the base class calls ``build_body()`` from its own ``__init__``.
    * ``build_body()`` returns one container widget; signals are wired at the
      end of that method.
    * ``on_source_changed`` skips repopulate when the node name hasn't changed —
      just re-marks the active row.  This preserves scroll position and filter
      text across paint → refresh → repaint cycles.
    * ``_mark_active`` accepts both a full DAG path and a short joint name so it
      works whether ``ctrl.active_map`` is one or the other.
    * ``_restore_selection`` scrolls the Qt view to the active row after a full
      repopulate without re-triggering ``_on_item_clicked``.
    """

    _min_size = 5
    _max_size = 200

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        # ── Initialise all state BEFORE super().__init__() ──────────────────
        # DeformerPanelBase.__init__ calls build_body() immediately, so these
        # must exist before the base class constructor runs.
        self._node_name:  str       = ''
        self._influences: List[str] = []
        self._source                = None
        self._ctrl                  = None   # set in on_source_changed

        self._model = JointInfluenceModel()
        self._proxy = QtCore.QSortFilterProxyModel()
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy.setFilterRole(Qt.DisplayRole)
        try:
            self._proxy.setRecursiveFilteringEnabled(True)   # Qt ≥ 5.10
        except AttributeError:
            pass

        super().__init__(parent)   # ← calls build_body() here

    # ------------------------------------------------------------------
    # Zone factory
    # ------------------------------------------------------------------

    def build_body(self) -> Optional[QtWidgets.QWidget]:
        """Return the influence tree + filter + refresh as a single widget."""
        container = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)

        # Filter field
        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText('Filter influences…')
        self._search.setClearButtonEnabled(True)
        self._search.setFixedHeight(22)
        lay.addWidget(self._search)

        # Influence tree
        self._view = _InfluenceTreeView()
        self._view.setModel(self._proxy)
        self._view.setItemDelegate(_LockDelegate(self._view))
        self._view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setUniformRowHeights(True)
        self._view.header().hide()
        self._view.setIndentation(14)
        self._view.setMinimumHeight(5  * _ROW_HEIGHT)
        self._view.setMaximumHeight(15 * _ROW_HEIGHT)
        lay.addWidget(self._view)

        # Bottom row — prune field + hint + refresh button
        bot = QtWidgets.QHBoxLayout()
        bot.setSpacing(3)
        bot.setContentsMargins(0, 0, 0, 0)

        prune_lbl = QtWidgets.QLabel('Prune below')
        prune_lbl.setStyleSheet('color: #888888; font-size: 10px;')
        bot.addWidget(prune_lbl)

        self._prune_spin = _AdaptiveDoubleSpinBox()
        self._prune_spin.setRange(0.0, 1.0)
        self._prune_spin.setDecimals(6)        # accept values down to 0.000001
        self._prune_spin.setSingleStep(0.0005)  # base step from 0
        self._prune_spin.setValue(0.0)
        self._prune_spin.setFixedWidth(70)
        self._prune_spin.setToolTip(
            'Flood (Set) skips verts whose current weight on the active '
            'influence is below this, so tiny garbage weights are not moved '
            'onto an unlocked sibling.\n0.0 = off. Shown precision follows the '
            'value you type (e.g. 0.0005).'
        )
        bot.addWidget(self._prune_spin)

        hint = QtWidgets.QLabel('Right-click to lock / unlock')
        hint.setStyleSheet('color: #555555; font-size: 10px;')
        bot.addWidget(hint, stretch=1)
        self._refresh_btn = QtWidgets.QPushButton('↺')
        self._refresh_btn.setFixedSize(22, 20)
        self._refresh_btn.setToolTip('Re-read lock states from Maya')
        bot.addWidget(self._refresh_btn)
        lay.addLayout(bot)

        # Wire signals
        self._search.textChanged.connect(self._proxy.setFilterFixedString)
        self._view.clicked.connect(self._on_item_clicked)
        self._model.lock_changed.connect(self._on_lock_changed)
        self._refresh_btn.clicked.connect(self._on_refresh_locks)
        self._prune_spin.valueChanged.connect(self._on_prune_changed)

        return container

    # ------------------------------------------------------------------
    # DeformerPanelBase lifecycle hooks
    # ------------------------------------------------------------------

    def on_source_changed(self,
                          source: Optional['WeightSource'],
                          active_map: str,
                          ctrl: 'SlimfastController') -> None:
        """Repopulate or just re-mark the active row.

        Full repopulate only when the skinCluster node changes.  When the same
        node is re-activated (e.g. after a paint → selection-changed → refresh
        cycle), only the active-row highlight is updated so scroll position and
        filter text are preserved.
        """
        self._source = source
        self._ctrl = ctrl
        # Keep the controller's prune threshold in sync with this panel's field
        # whenever a skin source becomes active.
        if ctrl is not None:
            ctrl.set_prune(self._prune_spin.value())
        if source is None:
            self._clear()
            return

        if self._node_name == source.node_name:
            # Same node — just update the active highlight, keep everything else.
            self._mark_active(active_map)
            self._restore_selection(active_map)
            return

        self._node_name = source.node_name
        self._populate(self._node_name, active_influence=active_map or '')
        self._restore_selection(active_map or '')

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clear(self) -> None:
        self._model.clear()
        self._influences = []
        self._node_name  = ''

    @staticmethod
    def _build_parent_map(full_paths: List[str]) -> Dict[str, Optional[str]]:
        """Derive parent–child relationships from DAG path strings.

        For each influence, walks up the ``|``-delimited path and returns the
        deepest ancestor that is also an influence (or ``None`` for roots).
        """
        inf_set    = set(full_paths)
        parent_map = {}
        for path in full_paths:
            parts  = path.split('|')
            parent = None
            for depth in range(len(parts) - 1, 0, -1):
                candidate = '|'.join(parts[:depth])
                if candidate in inf_set:
                    parent = candidate
                    break
            parent_map[path] = parent
        return parent_map

    def _populate(self, node_name: str, active_influence: str = '') -> None:
        """Rebuild the tree from scratch.

        1. Query Maya for influence short names.
        2. Convert to full DAG paths via ``cmds.ls(..., long=True)``.
        3. Derive hierarchy with ``_build_parent_map``.
        4. Create detached ``QStandardItem`` objects (``item.setData()`` safe —
           no ``lock_changed`` emitted, no Maya round-trip).
        5. Append to model shallowest-first (``rowsInserted`` fires → proxy
           updates → view shows items).  No ``blockSignals`` needed or used.
        6. Expand all, restore active highlight.
        """
        try:
            from maya import cmds
        except ImportError:
            logger.warning("SkinPanel._populate: Maya not available")
            return

        if not cmds.objExists(node_name):
            self._clear()
            return

        try:
            short_names = cmds.skinCluster(node_name, q=True, influence=True) or []
        except Exception as exc:
            logger.warning(f"SkinPanel._populate: cannot query influences: {exc}")
            self._clear()
            return

        full_paths: List[str] = (
            cmds.ls(short_names, long=True) if short_names else []
        ) or short_names

        self._influences = list(full_paths)
        parent_map       = self._build_parent_map(full_paths)

        # Create all items detached (item.setData before appendRow → no model
        # override → no lock_changed → no Maya push)
        item_by_path: Dict[str, QtGui.QStandardItem] = {}
        for path in full_paths:
            short = path.rsplit('|', 1)[-1]
            try:
                locked = bool(cmds.getAttr(f'{path}.lockInfluenceWeights'))
            except Exception:
                locked = False

            is_active = self._path_matches(path, active_influence)

            item = QtGui.QStandardItem(short)
            item.setData(path,      _ROLE_FULL_PATH)
            item.setData(locked,    _ROLE_LOCKED)
            item.setData(is_active, _ROLE_IS_ACTIVE)
            item.setEditable(False)
            item_by_path[path] = item

        # Wire parent → child, shallowest-first so parents always exist first
        self._model.clear()
        root = self._model.invisibleRootItem()
        for path in sorted(full_paths, key=lambda p: p.count('|')):
            parent_path = parent_map[path]
            parent_item = item_by_path.get(parent_path, root)
            parent_item.appendRow(item_by_path[path])   # rowsInserted → proxy

        self._view.expandAll()
        logger.debug(f"SkinPanel: populated {len(full_paths)} influences for '{node_name}'")

    @staticmethod
    def _path_matches(full_path: str, query: str) -> bool:
        """True when *query* matches *full_path* as a full path or short name."""
        if not query:
            return False
        return full_path == query or full_path.rsplit('|', 1)[-1] == query

    def _mark_active(self, active_map: str) -> None:
        """Update ``_ROLE_IS_ACTIVE`` on every item.

        Accepts both a full DAG path and a short joint name (with or without
        namespace) so it works regardless of what ``ctrl.active_map`` returns.

        Uses ``item.setData()`` (QStandardItem method) so ``dataChanged``
        fires (view repaints) but ``JointInfluenceModel.setData()`` is NOT
        called → no ``lock_changed`` → no Maya push.
        """
        for item in _iter_all_items(self._model.invisibleRootItem()):
            path = item.data(_ROLE_FULL_PATH) or ''
            item.setData(self._path_matches(path, active_map), _ROLE_IS_ACTIVE)

    def _restore_selection(self, active_map: str) -> None:
        """Scroll to and highlight the active row in the Qt tree view.

        Signals are blocked during the programmatic selection so
        ``_on_item_clicked`` (and therefore ``use_map`` + ``paint``) is not
        re-triggered.
        """
        if not active_map:
            return
        for item in _iter_all_items(self._model.invisibleRootItem()):
            path = item.data(_ROLE_FULL_PATH) or ''
            if self._path_matches(path, active_map):
                proxy_idx = self._proxy.mapFromSource(item.index())
                if proxy_idx.isValid():
                    self._view.blockSignals(True)
                    self._view.setCurrentIndex(proxy_idx)
                    self._view.blockSignals(False)
                    self._view.scrollTo(proxy_idx)
                break

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot(QtCore.QModelIndex)
    def _on_item_clicked(self, proxy_index: QtCore.QModelIndex) -> None:
        """Activate influence for painting on joint name click.

        Lock-zone clicks are consumed by ``_InfluenceTreeView.mousePressEvent``
        before Qt's selection machinery runs — this slot is never reached for
        lock clicks.

        Sequence
        --------
        1. Mark active row (teal bold).
        2. Emit ``map_selected`` → controller tracks the active map.
        3. Call ``source.use_map(joint_short_name)`` to set artisan influence.
        4. Call ``source.paint()`` → ``_paint_skin_cluster`` in weight_source.py.
        """
        src_index = self._proxy.mapToSource(proxy_index)
        item      = self._model.itemFromIndex(src_index)
        if item is None:
            return

        full_path  = item.data(_ROLE_FULL_PATH)
        joint_name = full_path.rsplit('|', 1)[-1]   # strip DAG prefix, keep ns

        self._mark_active(full_path)

        if self._source is not None:
            try:
                self._source.use_map(joint_name)
                self._source.paint()
            except Exception as e:
                import traceback
                logger.warning(f"SkinPanel paint failed: {e}\n{traceback.format_exc()}")

        logger.debug(f"SkinPanel: activated influence '{joint_name}'")

    @Slot(str, bool)
    def _on_lock_changed(self, full_path: str, locked: bool) -> None:
        """Push a lock state change to Maya.

        Called ONLY via ``JointInfluenceModel.lock_changed`` — explicit user
        interactions (lock click, context menu, Lock All).  Never called by
        ``item.setData()`` (used in populate and refresh).
        """
        try:
            from maya import cmds
            attr = f'{full_path}.lockInfluenceWeights'
            if cmds.objExists(attr):
                cmds.setAttr(attr, locked)
                logger.debug(
                    f"SkinPanel: {'locked' if locked else 'unlocked'} '{full_path}'"
                )
        except Exception as exc:
            logger.warning(f"SkinPanel._on_lock_changed: {exc}")

    @Slot()
    def _on_refresh_locks(self) -> None:
        """Re-read all lock states from Maya without pushing changes back.

        Uses ``item.setData()`` (QStandardItem method) so ``dataChanged``
        fires (view repaints) but ``JointInfluenceModel.setData()`` is NOT
        called → no ``lock_changed`` → no Maya push.
        """
        if not self._node_name:
            return
        try:
            from maya import cmds
        except ImportError:
            return
        for item in _iter_all_items(self._model.invisibleRootItem()):
            full_path = item.data(_ROLE_FULL_PATH)
            try:
                locked = bool(cmds.getAttr(f'{full_path}.lockInfluenceWeights'))
            except Exception:
                locked = False
            item.setData(locked, _ROLE_LOCKED)   # item path — no lock_changed
        logger.debug(f"SkinPanel: refreshed lock states for '{self._node_name}'")

    @Slot(float)
    def _on_prune_changed(self, value: float) -> None:
        """Push the prune threshold to the controller (flood blue-noise guard)."""
        if self._ctrl is not None:
            self._ctrl.set_prune(value)

    def on_enter(self) -> None:
        """Re-read lock states when the user returns to Slimfast."""
        self._on_refresh_locks()

register_deformer_panel(
    mode_key    = 'skinCluster',
    label       = 'SkinCluster',
    panel_class = SkinPanel,
    ctrl_mode   = 'deformer',
    node_types  = ['skinCluster'],
    order       = 100,
)