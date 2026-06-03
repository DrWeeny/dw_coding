"""SkinCluster influence list panel for Slimfast.

Displays influence joints of the active skinCluster in their skeleton
hierarchy (expand / collapse), with per-joint lock toggles, a search
filter and a context menu for bulk lock operations.

Architecture
------------
JointInfluenceModel — QStandardItemModel; emits ``lock_changed(path, bool)``
                      only when ``model.setData(_ROLE_LOCKED)`` is called
                      explicitly.  ``item.setData()`` (QStandardItem method)
                      bypasses this override — used safely during populate
                      and refresh so Maya is never called back.
_LockDelegate       — Custom delegate; draws the lock glyph + joint name.
_InfluenceTreeView  — QTreeView subclass; intercepts lock-column clicks
                      before Qt's selection machinery runs, and owns the
                      right-click context menu.
SkinPanel           — DeformerPanelBase; owns the model / view / delegate
                      and calls ``source.use_map()`` + ``source.paint()``
                      on joint selection.

Key design notes
----------------
blockSignals
    NOT used on the model.  ``blockSignals(True)`` suppresses
    ``rowsInserted`` → the proxy's row map is never built → view is blank.
    Use ``item.setData()`` (bypasses our override) for bulk populate /
    refresh; use ``model.setData()`` only for explicit lock toggles.

Hierarchy
    ``cmds.skinCluster(node, q=True, influence=True)`` returns short names.
    A second ``cmds.ls(..., long=True)`` pass converts them to full DAG
    paths.  ``_build_parent_map`` derives the parent of each influence by
    walking up the DAG path string and checking membership in the
    influence set.

Painting
    ``source.use_map(joint_short_name)`` + ``source.paint()`` are called
    directly on the stored source reference when a joint row is clicked.
    ``map_selected`` is still emitted so the controller can track the
    active map for copy/paste and weight operations.

Artisan clamp warning
    Skin weight painting uses ``artAttrSkinPaintCtx``, not the generic
    ``artAttrContext``.  ``has_artisan_clamp() → False`` tells the widget
    to skip the clamp-sync ``enterEvent`` read.  Guard in ``main_ui.py``::

        if getattr(self._current_panel, 'has_artisan_clamp', lambda: True)():
            self._get_artisan_clamp()

Registration
------------
One import activates the panel::

    from . import wgt_skin_panel   # noqa: F401

Author: DrWeeny
"""

from __future__ import annotations

from typing import Dict, Generator, List, Optional, TYPE_CHECKING

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Signal, Slot, Qt
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Signal, Slot, Qt

from dw_maya.Slimfast.wgt_deformer_panel import (
    DeformerPanelBase,
    register_deformer_panel,
)
from dw_logger import get_logger

if TYPE_CHECKING:
    from dw_maya.dw_paint.protocol import WeightSource
    from dw_maya.Slimfast.cmds import SlimfastController

logger = get_logger()

# ---------------------------------------------------------------------------
# Data roles
# ---------------------------------------------------------------------------
_ROLE_FULL_PATH = Qt.UserRole        # str  : full DAG path (|root|spine|…)
_ROLE_LOCKED    = Qt.UserRole + 1    # bool : .lockInfluenceWeights
_ROLE_IS_ACTIVE = Qt.UserRole + 2    # bool : currently active paint influence

_LOCK_COL_W = 26   # px reserved on the left of each row for the lock glyph
_ROW_HEIGHT = 22   # px per row


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class JointInfluenceModel(QtGui.QStandardItemModel):
    """One row (possibly with children) per influence joint.

    ``lock_changed`` fires ONLY via ``model.setData(_ROLE_LOCKED)`` —
    explicit user interactions (lock click, context menu, Lock All).
    ``item.setData()`` on a ``QStandardItem`` never calls this override.
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
# Delegate
# ---------------------------------------------------------------------------

class _LockDelegate(QtWidgets.QStyledItemDelegate):
    """Renders each row:   [🔒|🔓]  │  JointShortName

    Visual states
    -------------
    locked    → greyed-out name (#505050), dark background tint
    active    → teal bold name (#4ecdc4)
    selected  → palette highlight
    normal    → palette defaults
    """

    _LOCKED_GLYPH   = '🔒'
    _UNLOCKED_GLYPH = '🔓'

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

        # Lock glyph — left _LOCK_COL_W px of the content rect
        lock_rect = QtCore.QRect(rect.left(), rect.top(), _LOCK_COL_W, rect.height())
        glyph       = self._LOCKED_GLYPH if locked else self._UNLOCKED_GLYPH
        glyph_color = QtGui.QColor('#555555') if locked else QtGui.QColor('#999999')
        painter.setPen(glyph_color)
        painter.drawText(lock_rect, Qt.AlignCenter, glyph)

        # Thin separator after lock column
        painter.setPen(QtGui.QColor('#2e2e2e'))
        painter.drawLine(
            rect.left() + _LOCK_COL_W, rect.top(),
            rect.left() + _LOCK_COL_W, rect.bottom(),
        )

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
# Tree view
# ---------------------------------------------------------------------------

class _InfluenceTreeView(QtWidgets.QTreeView):
    """QTreeView with lock-column click interception and context menu.

    Lock-zone interception
    ----------------------
    ``mousePressEvent`` checks whether the click lands inside the left
    ``_LOCK_COL_W`` pixels of the item's content rect (i.e. after the tree's
    branch-indicator area).  If so it toggles the lock via the model and
    returns early — Qt's selection machinery never fires.

    Clicking the branch expand/collapse indicator returns an *invalid* index
    from ``indexAt``, so it falls through to ``super()`` correctly.
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
                    src_index, src_model = self._resolve_source(index)
                    locked = bool(src_index.data(_ROLE_LOCKED))
                    src_model.setData(src_index, not locked, _ROLE_LOCKED)
                    return   # consume — no expand/collapse, no selection change
        super().mousePressEvent(event)

    def _resolve_source(self, index: QtCore.QModelIndex):
        """Unwrap proxy → (source_index, source_model)."""
        proxy = self.model()
        if hasattr(proxy, 'mapToSource'):
            return proxy.mapToSource(index), proxy.sourceModel()
        return index, proxy

    @Slot(QtCore.QPoint)
    def _show_context_menu(self, pos: QtCore.QPoint) -> None:
        _, src_model = self._resolve_source(self.rootIndex())
        # Re-resolve because rootIndex is the invisible root, not useful here
        proxy = self.model()
        if hasattr(proxy, 'sourceModel'):
            src_model = proxy.sourceModel()

        menu = QtWidgets.QMenu(self)

        act_lock_all   = menu.addAction('🔒  Lock All')
        act_unlock_all = menu.addAction('🔓  Unlock All')

        act_lock_sel = act_unlock_sel = None
        index = self.indexAt(pos)
        if index.isValid():
            menu.addSeparator()
            act_lock_sel   = menu.addAction('🔒  Lock Selected')
            act_unlock_sel = menu.addAction('🔓  Unlock Selected')

        action = menu.exec_(self.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action is act_lock_all:
            _set_all_locks_recursive(src_model, src_model.invisibleRootItem(), True)
        elif action is act_unlock_all:
            _set_all_locks_recursive(src_model, src_model.invisibleRootItem(), False)
        elif action is act_lock_sel and index.isValid():
            src_index, sm = self._resolve_source(index)
            sm.setData(src_index, True, _ROLE_LOCKED)
        elif action is act_unlock_sel and index.isValid():
            src_index, sm = self._resolve_source(index)
            sm.setData(src_index, False, _ROLE_LOCKED)


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
        locked: bool,
) -> None:
    """Call ``model.setData(_ROLE_LOCKED)`` on every descendant of *root*.

    Using ``model.setData()`` (not ``item.setData()``) ensures
    ``lock_changed`` fires per joint so Maya is updated.
    """
    for item in _iter_all_items(root):
        model.setData(item.index(), locked, _ROLE_LOCKED)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class SkinPanel(DeformerPanelBase):
    """Influence tree panel for skinCluster deformers.

    Layout::

        ┌──────────────────────────────────────┐
        │ [ Filter influences…              ✕ ]│
        ├──────────────────────────────────────┤
        │  ▼ 🔓 │ pelvis                        │
        │    ▼ 🔓 │ L_thigh                     │
        │       🔒 │ L_knee   ← locked (grey)   │
        │    🔓 │ spine_01                       │
        │    🔓 │ spine_02  ← active (teal)      │
        │ …                                    │
        ├──────────────────────────────────────┤
        │ Right-click: Lock / Unlock     [ ↺ ] │
        └──────────────────────────────────────┘

    Joint row click
    ---------------
    1. Marks the row as active (teal bold).
    2. Emits ``map_selected(full_dag_path)`` → controller.
    3. Calls ``source.use_map(joint_short_name)`` + ``source.paint()``
       directly on the stored source so artisan opens immediately.
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)

        self._node_name:  str           = ''
        self._influences: List[str]     = []   # full DAG paths
        self._source                    = None  # WeightSource, stored for paint

        self._model = JointInfluenceModel()
        self._proxy = QtCore.QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy.setFilterRole(Qt.DisplayRole)
        # Keep parent rows visible when a child matches the filter
        try:
            self._proxy.setRecursiveFilteringEnabled(True)
        except AttributeError:
            pass   # Qt < 5.10 — graceful degradation

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(3)

        # Filter
        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText('Filter influences…')
        self._search.setClearButtonEnabled(True)
        self._search.setFixedHeight(22)
        lay.addWidget(self._search)

        # Tree view
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

        # Bottom row
        bot = QtWidgets.QHBoxLayout()
        bot.setSpacing(3)
        bot.setContentsMargins(0, 0, 0, 0)
        hint = QtWidgets.QLabel('Right-click to lock / unlock')
        hint.setStyleSheet('color: #555555; font-size: 10px;')
        bot.addWidget(hint, stretch=1)
        self._refresh_btn = QtWidgets.QPushButton('↺')
        self._refresh_btn.setFixedSize(22, 20)
        self._refresh_btn.setToolTip('Re-read lock states from Maya')
        bot.addWidget(self._refresh_btn)
        lay.addLayout(bot)

    def _connect_signals(self) -> None:
        self._search.textChanged.connect(self._proxy.setFilterFixedString)
        self._view.clicked.connect(self._on_item_clicked)
        self._model.lock_changed.connect(self._on_lock_changed)
        self._refresh_btn.clicked.connect(self._on_refresh_locks)

    # ------------------------------------------------------------------
    # DeformerPanelBase interface
    # ------------------------------------------------------------------

    def on_source_changed(self,
                          source: Optional['WeightSource'],
                          active_map: str,
                          ctrl: 'SlimfastController') -> None:
        """Repopulate from the active skinCluster and store source for paint."""
        self._source = source
        if source is None:
            self._clear()
            return
        self._node_name = source.node_name
        self._populate(self._node_name, active_influence=active_map or '')

    def has_envelope(self)      -> bool: return True
    def has_paint(self)         -> bool: return True

    def has_artisan_clamp(self) -> bool:
        """Opt out of the generic artisan clamp read.

        Skin painting uses ``artAttrSkinPaintCtx``; the generic
        ``artAttrContext`` read always fails with a warning.  Guard in
        ``main_ui.py`` ``enterEvent``::

            if getattr(self._current_panel, 'has_artisan_clamp', lambda: True)():
                self._get_artisan_clamp()
        """
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clear(self) -> None:
        self._model.clear()
        self._influences = []
        self._node_name  = ''

    # ------------------------------------------------------------------

    @staticmethod
    def _build_parent_map(full_paths: List[str]) -> Dict[str, Optional[str]]:
        """Derive parent–child relationships purely from DAG path strings.

        For each influence, walks up the ``|``-delimited path and returns
        the deepest ancestor that is also in the influence list.

        Example::
            ["|root|spine|hip", "|root|spine|shoulder", "|root|spine"]
            → {
                "|root|spine":           None,         # root of the subtree
                "|root|spine|hip":       "|root|spine",
                "|root|spine|shoulder":  "|root|spine",
              }

        Args:
            full_paths: Influence full DAG paths as returned by
                        ``cmds.ls(..., long=True)``.

        Returns:
            Dict mapping each path to its closest influence ancestor, or
            ``None`` when no ancestor is also an influence.
        """
        inf_set = set(full_paths)
        parent_map: Dict[str, Optional[str]] = {}

        for path in full_paths:
            parts  = path.split('|')   # ['', 'root', 'spine', 'hip']
            parent = None
            # Walk from direct parent upward; first match wins
            for depth in range(len(parts) - 1, 0, -1):
                candidate = '|'.join(parts[:depth])
                if candidate in inf_set:
                    parent = candidate
                    break
            parent_map[path] = parent

        return parent_map

    # ------------------------------------------------------------------

    def _populate(self, node_name: str, active_influence: str = '') -> None:
        """Rebuild the tree from scratch.

        Steps
        -----
        1. Query Maya for influence short names.
        2. Convert to full DAG paths via ``cmds.ls(..., long=True)``.
        3. Derive hierarchy with ``_build_parent_map``.
        4. Create ``QStandardItem`` objects (detached — ``item.setData()``
           safe, no ``lock_changed`` emitted).
        5. Assign parents; add roots to model (``rowsInserted`` fires →
           proxy updates → view shows items).
        6. Expand all nodes, restore any active highlight.
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

        # Full DAG paths for hierarchy derivation
        full_paths: List[str] = (
            cmds.ls(short_names, long=True) if short_names else []
        ) or short_names   # fallback if ls returns empty

        self._influences = list(full_paths)
        parent_map       = self._build_parent_map(full_paths)

        # --- Create items (detached, no model signals yet) -------------
        item_by_path: Dict[str, QtGui.QStandardItem] = {}

        for path in full_paths:
            short = path.rsplit('|', 1)[-1]   # keep namespace, strip DAG prefix
            try:
                locked = bool(cmds.getAttr(f'{path}.lockInfluenceWeights'))
            except Exception:
                locked = False

            item = QtGui.QStandardItem(short)
            # item.setData() on a detached item never calls model.setData(),
            # so lock_changed cannot fire and Maya is not called.
            item.setData(path,                  _ROLE_FULL_PATH)
            item.setData(locked,                _ROLE_LOCKED)
            item.setData(path == active_influence, _ROLE_IS_ACTIVE)
            item.setEditable(False)
            item_by_path[path] = item

        # --- Wire parent → child relationships ------------------------
        # Sort shallowest-first so parents exist before children are appended.
        self._model.clear()
        root_item = self._model.invisibleRootItem()

        for path in sorted(full_paths, key=lambda p: p.count('|')):
            parent_path  = parent_map[path]
            parent_item  = item_by_path.get(parent_path, root_item)
            parent_item.appendRow(item_by_path[path])   # rowsInserted → proxy

        self._view.expandAll()
        logger.debug(
            f"SkinPanel: populated {len(full_paths)} influences "
            f"for '{node_name}'"
        )

    # ------------------------------------------------------------------

    def _mark_active(self, full_path: str) -> None:
        """Set ``_ROLE_IS_ACTIVE`` on one item, clear all others.

        Uses ``item.setData()`` so ``dataChanged`` propagates (repaint) but
        ``lock_changed`` is never emitted.
        """
        for item in _iter_all_items(self._model.invisibleRootItem()):
            is_active = item.data(_ROLE_FULL_PATH) == full_path
            item.setData(is_active, _ROLE_IS_ACTIVE)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot(QtCore.QModelIndex)
    def _on_item_clicked(self, proxy_index: QtCore.QModelIndex) -> None:
        """Activate influence for painting on joint row click.

        Sequence:
        1. Mark row as active (teal bold).
        2. Emit ``map_selected`` → controller tracks active map.
        3. Call ``source.use_map(joint_name)`` to set artisan influence.
        4. Call ``source.paint()`` to open the artisan paint context.

        Joint name passed to ``use_map`` is the short name with namespace
        (strips only the leading ``|path|`` DAG prefix) — matching the
        format expected by ``SkinCluster.use_map()``.

        Lock-zone clicks are consumed by ``_InfluenceTreeView.mousePressEvent``
        and never reach this slot.
        """
        proxy = self._proxy
        src_index = proxy.mapToSource(proxy_index)
        item      = self._model.itemFromIndex(src_index)
        if item is None:
            return

        full_path  = item.data(_ROLE_FULL_PATH)
        joint_name = full_path.rsplit('|', 1)[-1]   # 'namespace:JointName'

        self._mark_active(full_path)
        self.map_selected.emit(joint_name)

        if self._source is not None:
            if hasattr(self._source, 'use_map'):
                try:
                    self._source.use_map(joint_name)
                except Exception as exc:
                    logger.warning(f"SkinPanel: use_map('{joint_name}') failed: {exc}")
            if hasattr(self._source, 'paint'):
                try:
                    self._source.paint()
                except Exception as exc:
                    logger.warning(f"SkinPanel: paint() failed: {exc}")

        logger.debug(f"SkinPanel: activated influence '{joint_name}'")

    @Slot(str, bool)
    def _on_lock_changed(self, full_path: str, locked: bool) -> None:
        """Push a lock state change to the Maya joint attribute.

        Only called via ``model.setData(_ROLE_LOCKED)`` — explicit user
        interactions.  Never called by ``item.setData()`` (populate/refresh).
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
        """Re-read all lock states from Maya without pushing any changes back.

        Uses ``item.setData()`` → ``dataChanged`` fires (repaint) but
        ``JointInfluenceModel.setData()`` is NOT called → no ``lock_changed``
        → no Maya push.
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


# ---------------------------------------------------------------------------
# Registration — overrides DefaultPanel for skinCluster node type
# ---------------------------------------------------------------------------

register_deformer_panel(
    mode_key    = 'skinCluster',
    label       = 'SkinCluster',
    panel_class = SkinPanel,
    ctrl_mode   = 'deformer',
    node_types  = ['skinCluster'],
    order       = 11,   # just after generic 'deformer' (order=10)
)