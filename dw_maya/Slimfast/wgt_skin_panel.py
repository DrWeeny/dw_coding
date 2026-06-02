"""SkinCluster influence list panel for Slimfast.

Displays all influence joints of the active skinCluster with per-joint
lock toggles and a search filter.  Selecting a joint emits ``map_selected``
so the controller can activate that influence in the artisan paint context.

Architecture
------------
_InfluenceListView  — QListView subclass; intercepts lock-column mouse
                      presses *before* Qt's selection machinery runs, so
                      toggling a lock never changes the active row.
JointInfluenceModel — QStandardItemModel; emits ``lock_changed(path, bool)``
                      whenever a lock role changes.
_LockDelegate       — Custom delegate; draws the lock glyph + joint name
                      with colour coding for locked / active states.
SkinPanel           — DeformerPanelBase subclass owning the model / view /
                      delegate and routing user actions to Maya via cmds.

Registration
------------
At import time the module registers ``skinCluster`` in the global panel
registry so that ``get_panel_class('skinCluster')`` returns ``SkinPanel``
instead of the default ``DefaultPanel``.

Add one import to ``main_ui.py`` (after the existing ``wgt_deformer_panel``
import) to activate the panel::

    from . import wgt_skin_panel   # noqa: F401  — registers SkinPanel

Author: DrWeeny
"""

from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

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
# Custom data roles
# ---------------------------------------------------------------------------
_ROLE_FULL_PATH = Qt.UserRole        # str  : full DAG path (e.g. |root|spine|arm)
_ROLE_LOCKED    = Qt.UserRole + 1    # bool : current .lockInfluenceWeights value
_ROLE_IS_ACTIVE = Qt.UserRole + 2    # bool : currently active paint influence

# Width (px) reserved on the left of every row for the lock glyph.
_LOCK_COL_W = 26


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class JointInfluenceModel(QtGui.QStandardItemModel):
    """One row per influence joint.

    Emits ``lock_changed`` whenever ``_ROLE_LOCKED`` is written through
    ``setData``, so the panel can push the new state to Maya without polling.

    Signals:
        lock_changed(full_path, locked):
            ``full_path`` is the DAG path stored in ``_ROLE_FULL_PATH``;
            ``locked`` is the new bool value.
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
    """Renders each row as:   [🔒|🔓]  │  JointShortName

    Visual states
    -------------
    locked    — greyed-out name (#555555), dark background tint
    active    — teal bold name (#4ecdc4)
    selected  — palette highlight background, inverted text
    normal    — palette text / base colours
    """

    _LOCKED_GLYPH   = '🔒'
    _UNLOCKED_GLYPH = '🔓'
    _ROW_HEIGHT     = 22

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

        # ── Background ─────────────────────────────────────────────────────
        if selected:
            bg = option.palette.highlight().color()
        elif locked:
            bg = QtGui.QColor('#1c1c1c')
        else:
            bg = option.palette.base().color()
        painter.fillRect(rect, bg)

        # ── Lock glyph ─────────────────────────────────────────────────────
        lock_rect = QtCore.QRect(
            rect.left(), rect.top(), _LOCK_COL_W, rect.height()
        )
        glyph = self._LOCKED_GLYPH if locked else self._UNLOCKED_GLYPH
        glyph_color = QtGui.QColor('#666666') if locked else QtGui.QColor('#aaaaaa')
        painter.setPen(glyph_color)
        painter.drawText(lock_rect, Qt.AlignCenter, glyph)

        # ── Thin separator line ────────────────────────────────────────────
        painter.setPen(QtGui.QColor('#2e2e2e'))
        sep_x = rect.left() + _LOCK_COL_W
        painter.drawLine(sep_x, rect.top(), sep_x, rect.bottom())

        # ── Joint name ─────────────────────────────────────────────────────
        name_rect = QtCore.QRect(
            rect.left() + _LOCK_COL_W + 4,
            rect.top(),
            rect.width() - _LOCK_COL_W - 6,
            rect.height(),
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
        return QtCore.QSize(option.rect.width(), self._ROW_HEIGHT)


# ---------------------------------------------------------------------------
# Custom list view — intercepts lock-column clicks before selection changes
# ---------------------------------------------------------------------------

class _InfluenceListView(QtWidgets.QListView):
    """QListView that routes lock-zone clicks to the model without affecting
    the active row selection.

    Qt's selection machinery fires *after* ``mousePressEvent``.  By checking
    whether the cursor is inside the left ``_LOCK_COL_W`` pixels of the
    clicked row and consuming the event early (returning without calling
    ``super()``), we guarantee the row selection never changes when the user
    toggles a lock.
    """

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
                    # --- resolve proxy → source if needed ---
                    proxy = self.model()
                    if hasattr(proxy, 'mapToSource'):
                        src_index  = proxy.mapToSource(index)
                        src_model  = proxy.sourceModel()
                    else:
                        src_index  = index
                        src_model  = proxy

                    locked = bool(src_index.data(_ROLE_LOCKED))
                    src_model.setData(src_index, not locked, _ROLE_LOCKED)
                    return          # consume — no selection change

        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class SkinPanel(DeformerPanelBase):
    """Influence list sub-panel for skinCluster deformers.

    Layout::

        ┌──────────────────────────────────────┐
        │ [ Filter influences…              ✕ ]│
        ├──────────────────────────────────────┤
        │ 🔓 │ joint_A                          │
        │ 🔒 │ joint_B   ← locked (grey)        │
        │ 🔓 │ joint_C   ← active (teal bold)   │
        │ …                                    │
        ├──────────────────────────────────────┤
        │ [🔒 All]   [🔓 All]              [ ↺ ]│
        └──────────────────────────────────────┘

    Selecting a joint emits ``map_selected(full_dag_path)`` so the
    controller can call ``cmds.skinCluster(node, e=True, influence=joint)``
    before opening the artisan paint context.
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)

        self._node_name: str = ''
        self._influences: List[str] = []   # cached full DAG paths

        # Model + proxy filter
        self._model = JointInfluenceModel()
        self._proxy = QtCore.QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy.setFilterRole(Qt.DisplayRole)

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(3)

        # ── Search / filter ────────────────────────────────────────────
        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText('Filter influences…')
        self._search.setClearButtonEnabled(True)
        self._search.setFixedHeight(22)
        lay.addWidget(self._search)

        # ── Influence list ─────────────────────────────────────────────
        self._view = _InfluenceListView()
        self._view.setModel(self._proxy)
        self._view.setItemDelegate(_LockDelegate(self._view))
        self._view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._view.setAlternatingRowColors(False)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setUniformItemSizes(True)
        # Show 5 rows minimum, cap at 12 rows (scrollbar for larger rigs)
        self._view.setMinimumHeight(5 * _LockDelegate._ROW_HEIGHT)
        self._view.setMaximumHeight(12 * _LockDelegate._ROW_HEIGHT)
        lay.addWidget(self._view)

        # ── Bottom action row ──────────────────────────────────────────
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(3)
        btn_row.setContentsMargins(0, 0, 0, 0)

        _btn_style_lock = (
            'QPushButton { background: #252525; color: #777777; font-size: 11px; }'
            'QPushButton:hover { background: #303030; color: #aaaaaa; }'
        )
        _btn_style_unlock = (
            'QPushButton { background: #252525; color: #999999; font-size: 11px; }'
            'QPushButton:hover { background: #303030; color: #cccccc; }'
        )

        self._lock_all_btn = QtWidgets.QPushButton('🔒 All')
        self._lock_all_btn.setFixedHeight(20)
        self._lock_all_btn.setStyleSheet(_btn_style_lock)
        self._lock_all_btn.setToolTip('Lock all influences')
        btn_row.addWidget(self._lock_all_btn)

        self._unlock_all_btn = QtWidgets.QPushButton('🔓 All')
        self._unlock_all_btn.setFixedHeight(20)
        self._unlock_all_btn.setStyleSheet(_btn_style_unlock)
        self._unlock_all_btn.setToolTip('Unlock all influences')
        btn_row.addWidget(self._unlock_all_btn)

        self._refresh_btn = QtWidgets.QPushButton('↺')
        self._refresh_btn.setFixedSize(22, 20)
        self._refresh_btn.setToolTip('Re-read lock states from Maya')
        btn_row.addWidget(self._refresh_btn)

        lay.addLayout(btn_row)

    def _connect_signals(self) -> None:
        self._search.textChanged.connect(self._proxy.setFilterFixedString)
        self._view.clicked.connect(self._on_item_clicked)
        self._model.lock_changed.connect(self._on_lock_changed)
        self._lock_all_btn.clicked.connect(self._on_lock_all)
        self._unlock_all_btn.clicked.connect(self._on_unlock_all)
        self._refresh_btn.clicked.connect(self._on_refresh_locks)

    # ------------------------------------------------------------------
    # DeformerPanelBase interface
    # ------------------------------------------------------------------

    def on_source_changed(self,
                          source: Optional['WeightSource'],
                          active_map: str,
                          ctrl: 'SlimfastController') -> None:
        """Repopulate the influence list from the newly active skinCluster.

        Args:
            source:     Active WeightSource wrapping the skinCluster node.
            active_map: Currently active map attribute (used to pre-highlight
                        a joint if it matches a known influence path).
            ctrl:       Unused by this panel.
        """
        if source is None:
            self._clear()
            return
        self._node_name = source.node_name
        self._populate(self._node_name, active_influence=active_map or '')

    def has_envelope(self) -> bool:
        """skinCluster nodes have an ``envelope`` attribute."""
        return True

    def has_paint(self) -> bool:
        """skinCluster weights are paintable via artisan."""
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clear(self) -> None:
        self._model.clear()
        self._influences = []
        self._node_name  = ''

    def _populate(self, node_name: str, active_influence: str = '') -> None:
        """Query Maya for influences + lock states and rebuild the model.

        Blocks model signals during bulk load so that ``lock_changed`` is
        not emitted for every row and Maya is not called unnecessarily.

        Args:
            node_name:        Name of the skinCluster node.
            active_influence: Full DAG path of the joint to highlight as
                              active (teal bold).  Empty = none.
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
            influences = cmds.skinCluster(node_name, q=True, influence=True) or []
        except Exception as exc:
            logger.warning(f"SkinPanel._populate: failed to query influences: {exc}")
            self._clear()
            return

        self._influences = list(influences)

        self._model.blockSignals(True)
        self._model.clear()

        for jnt in influences:
            short = jnt.rsplit('|', 1)[-1]          # last DAG token as display name

            try:
                locked = bool(cmds.getAttr(f'{jnt}.lockInfluenceWeights'))
            except Exception:
                locked = False

            item = QtGui.QStandardItem(short)
            item.setData(jnt,                  _ROLE_FULL_PATH)
            item.setData(locked,               _ROLE_LOCKED)
            item.setData(jnt == active_influence, _ROLE_IS_ACTIVE)
            item.setEditable(False)
            self._model.appendRow(item)

        self._model.blockSignals(False)
        self._view.viewport().update()

        logger.debug(
            f"SkinPanel: populated {len(influences)} influences "
            f"for '{node_name}'"
        )

    def _mark_active(self, full_path: str) -> None:
        """Set ``_ROLE_IS_ACTIVE`` True on one row and False on all others.

        Does NOT emit ``lock_changed`` (different role).

        Args:
            full_path: DAG path of the influence to mark active.
        """
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            if item is not None:
                item.setData(item.data(_ROLE_FULL_PATH) == full_path,
                             _ROLE_IS_ACTIVE)

    def _set_all_locks(self, locked: bool) -> None:
        """Set every influence in the *source* model to ``locked``.

        Signals are intentionally NOT blocked so that ``lock_changed`` fires
        per row and pushes each change to Maya.

        Args:
            locked: Target lock state.
        """
        for row in range(self._model.rowCount()):
            self._model.setData(self._model.index(row, 0), locked, _ROLE_LOCKED)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot(QtCore.QModelIndex)
    def _on_item_clicked(self, proxy_index: QtCore.QModelIndex) -> None:
        """Activate the clicked influence for painting.

        Lock-zone clicks are consumed upstream in
        ``_InfluenceListView.mousePressEvent`` and never reach this slot.
        """
        src_index = self._proxy.mapToSource(proxy_index)
        item      = self._model.itemFromIndex(src_index)
        if item is None:
            return
        full_path = item.data(_ROLE_FULL_PATH)
        self._mark_active(full_path)
        self.map_selected.emit(full_path)
        logger.debug(f"SkinPanel: selected influence '{full_path}'")

    @Slot(str, bool)
    def _on_lock_changed(self, full_path: str, locked: bool) -> None:
        """Push a lock state change to the Maya joint attribute.

        Called by ``JointInfluenceModel.lock_changed`` after any
        ``setData(_ROLE_LOCKED)`` call — including those triggered by
        ``_set_all_locks``.

        Args:
            full_path: DAG path of the influence joint.
            locked:    New lock state.
        """
        try:
            from maya import cmds
            attr = f'{full_path}.lockInfluenceWeights'
            if cmds.objExists(attr):
                cmds.setAttr(attr, locked)
                logger.debug(
                    f"SkinPanel: {'locked' if locked else 'unlocked'} "
                    f"'{full_path}'"
                )
        except Exception as exc:
            logger.warning(f"SkinPanel._on_lock_changed: {exc}")

    @Slot()
    def _on_lock_all(self) -> None:
        """Lock every influence (respects filter — operates on full model)."""
        self._set_all_locks(True)

    @Slot()
    def _on_unlock_all(self) -> None:
        """Unlock every influence."""
        self._set_all_locks(False)

    @Slot()
    def _on_refresh_locks(self) -> None:
        """Re-read all lock states from Maya without touching the selection.

        Model signals are blocked during the read so that ``lock_changed``
        is NOT emitted (no round-trip push back to Maya).
        """
        if not self._node_name:
            return
        try:
            from maya import cmds
        except ImportError:
            return

        self._model.blockSignals(True)
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            if item is None:
                continue
            full_path = item.data(_ROLE_FULL_PATH)
            try:
                locked = bool(cmds.getAttr(f'{full_path}.lockInfluenceWeights'))
            except Exception:
                locked = False
            self._model.setData(self._model.index(row, 0), locked, _ROLE_LOCKED)
        self._model.blockSignals(False)

        self._view.viewport().update()
        logger.debug(f"SkinPanel: refreshed lock states for '{self._node_name}'")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
# Importing this module is enough to override the default DefaultPanel entry
# for skinCluster.  The 'deformer' radio button registration in
# wgt_deformer_panel.py still maps cluster/softMod/wire → DefaultPanel;
# only _PANEL_BY_NODE_TYPE['skinCluster'] is updated here.

register_deformer_panel(
    mode_key   = 'skinCluster',
    label      = 'SkinCluster',
    panel_class= SkinPanel,
    ctrl_mode  = 'deformer',
    node_types = ['skinCluster'],
    order      = 11,     # just after 'deformer' (order=10) in the radio row
)