"""SkinCluster influence list panel for Slimfast.

Displays all influence joints of the active skinCluster with per-joint
lock toggles, a search filter, and a context menu for bulk lock operations.

Architecture
------------
_InfluenceListView  — QListView subclass; intercepts lock-column mouse
                      presses *before* Qt's selection machinery runs, so
                      toggling a lock never changes the active row.
                      Also owns the right-click context menu.
JointInfluenceModel — QStandardItemModel; emits ``lock_changed(path, bool)``
                      when ``model.setData(_ROLE_LOCKED)`` is called.
                      Crucially, ``item.setData()`` (QStandardItem method)
                      bypasses this override → used during populate/refresh.
_LockDelegate       — Custom delegate; draws the lock glyph + joint name
                      with colour coding for locked / active states.
SkinPanel           — DeformerPanelBase subclass.

Key design notes
----------------
* ``blockSignals`` is NOT used on the model during ``_populate``.
  ``blockSignals(True)`` suppresses ``rowsInserted``, which breaks the proxy
  model's internal row map → the view shows nothing.  Since we call
  ``item.setData()`` on a detached item (before ``appendRow``), the model's
  ``setData()`` override is never reached and ``lock_changed`` cannot fire.

* ``_on_refresh_locks`` also uses ``item.setData()`` (not ``model.setData()``)
  so the override is bypassed, ``dataChanged`` still propagates (view repaints),
  and no ``blockSignals`` is needed.

* ``has_artisan_clamp() → False`` tells ``SlimfastWidget.enterEvent`` to skip
  the clamp sync for skinCluster sources.  Skin weight painting uses
  ``artAttrSkinPaintCtx``, not the generic ``artAttrContext``, so the generic
  read always fails with a warning.

Registration
------------
Importing this module is enough::

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
_ROLE_FULL_PATH = Qt.UserRole        # str  : full DAG path
_ROLE_LOCKED    = Qt.UserRole + 1    # bool : .lockInfluenceWeights
_ROLE_IS_ACTIVE = Qt.UserRole + 2    # bool : currently active paint influence

# Width (px) reserved on the left of each row for the lock glyph.
_LOCK_COL_W  = 26
_ROW_HEIGHT  = 22


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class JointInfluenceModel(QtGui.QStandardItemModel):
    """One row per influence joint.

    ``lock_changed`` fires ONLY when ``model.setData(_ROLE_LOCKED)`` is called
    explicitly (e.g. from the lock-column click or context menu).
    ``item.setData()`` on a ``QStandardItem`` does NOT call this override, so
    bulk populate / refresh operations can use that path safely.
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
    locked    — greyed-out name, dark background
    active    — teal bold name (#4ecdc4)
    selected  — palette highlight background
    normal    — palette defaults
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

        # Lock glyph
        lock_rect = QtCore.QRect(rect.left(), rect.top(), _LOCK_COL_W, rect.height())
        glyph       = self._LOCKED_GLYPH if locked else self._UNLOCKED_GLYPH
        glyph_color = QtGui.QColor('#555555') if locked else QtGui.QColor('#999999')
        painter.setPen(glyph_color)
        painter.drawText(lock_rect, Qt.AlignCenter, glyph)

        # Thin separator line
        painter.setPen(QtGui.QColor('#2e2e2e'))
        sep_x = rect.left() + _LOCK_COL_W
        painter.drawLine(sep_x, rect.top(), sep_x, rect.bottom())

        # Joint name
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
        # Fixed height; width is managed by the view's layout.
        return QtCore.QSize(100, _ROW_HEIGHT)


# ---------------------------------------------------------------------------
# Custom list view
# ---------------------------------------------------------------------------

class _InfluenceListView(QtWidgets.QListView):
    """QListView that routes lock-zone clicks to the model without changing
    the active row selection, and shows a context menu for bulk lock ops.

    Lock column interception
    ------------------------
    Qt's selection machinery fires *after* ``mousePressEvent``.  By checking
    whether the cursor is inside the left ``_LOCK_COL_W`` pixels and returning
    early (without calling ``super()``), we guarantee the row selection never
    changes when the user clicks the lock glyph.
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.pos())
            if index.isValid():
                item_rect  = self.visualRect(index)
                lock_rect  = QtCore.QRect(
                    item_rect.left(), item_rect.top(),
                    _LOCK_COL_W, item_rect.height(),
                )
                if lock_rect.contains(event.pos()):
                    # Resolve proxy → source
                    proxy = self.model()
                    if hasattr(proxy, 'mapToSource'):
                        src_index = proxy.mapToSource(index)
                        src_model = proxy.sourceModel()
                    else:
                        src_index = index
                        src_model = proxy
                    locked = bool(src_index.data(_ROLE_LOCKED))
                    src_model.setData(src_index, not locked, _ROLE_LOCKED)
                    return   # consume — no selection change

        super().mousePressEvent(event)

    @Slot(QtCore.QPoint)
    def _show_context_menu(self, pos: QtCore.QPoint) -> None:
        proxy = self.model()
        src_model = proxy.sourceModel() if hasattr(proxy, 'sourceModel') else proxy

        menu = QtWidgets.QMenu(self)

        # --- Lock / Unlock All ---
        act_lock_all = menu.addAction('🔒  Lock All')
        act_unlock_all = menu.addAction('🔓  Unlock All')

        # --- Per-row actions for the clicked / selected row ---
        index = self.indexAt(pos)
        act_lock_sel = act_unlock_sel = None
        if index.isValid():
            menu.addSeparator()
            act_lock_sel   = menu.addAction('🔒  Lock Selected')
            act_unlock_sel = menu.addAction('🔓  Unlock Selected')

        action = menu.exec_(self.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action is act_lock_all:
            self._set_all_locks(src_model, True)
        elif action is act_unlock_all:
            self._set_all_locks(src_model, False)
        elif action is act_lock_sel and index.isValid():
            src_index = proxy.mapToSource(index) if hasattr(proxy, 'mapToSource') else index
            src_model.setData(src_index, True, _ROLE_LOCKED)
        elif action is act_unlock_sel and index.isValid():
            src_index = proxy.mapToSource(index) if hasattr(proxy, 'mapToSource') else index
            src_model.setData(src_index, False, _ROLE_LOCKED)

    @staticmethod
    def _set_all_locks(src_model: QtGui.QStandardItemModel, locked: bool) -> None:
        """Call ``model.setData`` on every row so ``lock_changed`` fires per row."""
        for row in range(src_model.rowCount()):
            src_model.setData(src_model.index(row, 0), locked, _ROLE_LOCKED)


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
        │ Right-click for Lock/Unlock  │  [ ↺ ]│
        └──────────────────────────────────────┘

    Selecting a joint emits ``map_selected(full_dag_path)`` so the
    controller can activate that influence in the artisan paint context.
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)

        self._node_name: str  = ''
        self._influences: List[str] = []

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

        # Search / filter
        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText('Filter influences…')
        self._search.setClearButtonEnabled(True)
        self._search.setFixedHeight(22)
        lay.addWidget(self._search)

        # Influence list
        self._view = _InfluenceListView()
        self._view.setModel(self._proxy)
        self._view.setItemDelegate(_LockDelegate(self._view))
        self._view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._view.setAlternatingRowColors(False)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setUniformItemSizes(True)
        # Show 5 rows minimum, cap at 12 rows (scrollbar for larger rigs)
        self._view.setMinimumHeight(5 * _ROW_HEIGHT)
        self._view.setMaximumHeight(12 * _ROW_HEIGHT)
        lay.addWidget(self._view)

        # Bottom row — hint label + refresh button
        bottom_row = QtWidgets.QHBoxLayout()
        bottom_row.setSpacing(3)
        bottom_row.setContentsMargins(0, 0, 0, 0)

        hint = QtWidgets.QLabel('Right-click to lock / unlock')
        hint.setStyleSheet('color: #555555; font-size: 10px;')
        bottom_row.addWidget(hint, stretch=1)

        self._refresh_btn = QtWidgets.QPushButton('↺')
        self._refresh_btn.setFixedSize(22, 20)
        self._refresh_btn.setToolTip('Re-read lock states from Maya')
        bottom_row.addWidget(self._refresh_btn)

        lay.addLayout(bottom_row)

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
        """Repopulate the influence list from the newly active skinCluster."""
        if source is None:
            self._clear()
            return
        self._node_name = source.node_name
        self._populate(self._node_name, active_influence=active_map or '')

    def has_envelope(self) -> bool:
        return True

    def has_paint(self) -> bool:
        return True

    def has_artisan_clamp(self) -> bool:
        """Opt out of the generic artisan clamp sync.

        Skin weight painting uses ``artAttrSkinPaintCtx``, not the generic
        ``artAttrContext``.  Returning ``False`` prevents ``SlimfastWidget
        .enterEvent`` from attempting (and failing) to read clamp limits from
        the wrong context.

        To activate this, add one check in ``main_ui.py`` ``enterEvent``::

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

    def _populate(self, node_name: str, active_influence: str = '') -> None:
        """Query Maya for influences + lock states and rebuild the model.

        We do NOT call ``model.blockSignals(True)`` here.  Blocking signals
        suppresses ``rowsInserted``, which breaks the proxy model's internal
        row map so the view shows nothing.

        ``item.setData()`` (called on a detached QStandardItem before
        ``appendRow``) does NOT go through ``JointInfluenceModel.setData()``,
        so ``lock_changed`` cannot fire during populate.
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
        self._model.clear()

        for jnt in influences:
            short = jnt.rsplit('|', 1)[-1]
            try:
                locked = bool(cmds.getAttr(f'{jnt}.lockInfluenceWeights'))
            except Exception:
                locked = False

            item = QtGui.QStandardItem(short)
            # item.setData() on a detached item → no model.setData() override,
            # no lock_changed, no Maya push.
            item.setData(jnt,                       _ROLE_FULL_PATH)
            item.setData(locked,                    _ROLE_LOCKED)
            item.setData(jnt == active_influence,   _ROLE_IS_ACTIVE)
            item.setEditable(False)
            self._model.appendRow(item)   # rowsInserted fires → proxy updates

        logger.debug(
            f"SkinPanel: populated {len(influences)} influences "
            f"for '{node_name}'"
        )

    def _mark_active(self, full_path: str) -> None:
        """Highlight one row as the active paint influence.

        Uses ``item.setData()`` (QStandardItem method) so ``dataChanged``
        fires (the view repaints) but ``JointInfluenceModel.setData()`` is
        NOT called, meaning ``lock_changed`` is not emitted.
        """
        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            if item is not None:
                is_active = item.data(_ROLE_FULL_PATH) == full_path
                item.setData(is_active, _ROLE_IS_ACTIVE)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot(QtCore.QModelIndex)
    def _on_item_clicked(self, proxy_index: QtCore.QModelIndex) -> None:
        """Activate the clicked influence for painting.

        Lock-zone clicks are consumed by ``_InfluenceListView.mousePressEvent``
        before Qt's selection machinery runs and never reach this slot.
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

        Triggered by ``JointInfluenceModel.lock_changed`` after any explicit
        ``model.setData(_ROLE_LOCKED)`` call (lock column click, context menu).
        NOT triggered by ``item.setData()`` (used in populate / refresh).
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

        Uses ``item.setData()`` (QStandardItem method) instead of
        ``model.setData()`` so our override is bypassed and ``lock_changed``
        is NOT emitted.  ``dataChanged`` is still emitted internally so the
        view repaints correctly.
        """
        if not self._node_name:
            return
        try:
            from maya import cmds
        except ImportError:
            return

        for row in range(self._model.rowCount()):
            item = self._model.item(row)
            if item is None:
                continue
            full_path = item.data(_ROLE_FULL_PATH)
            try:
                locked = bool(cmds.getAttr(f'{full_path}.lockInfluenceWeights'))
            except Exception:
                locked = False
            # QStandardItem.setData → dataChanged (view repaints) but does NOT
            # call JointInfluenceModel.setData → no lock_changed → no Maya push.
            item.setData(locked, _ROLE_LOCKED)

        logger.debug(f"SkinPanel: refreshed lock states for '{self._node_name}'")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_deformer_panel(
    mode_key    = 'skinCluster',
    label       = 'SkinCluster',
    panel_class = SkinPanel,
    ctrl_mode   = 'deformer',
    node_types  = ['skinCluster'],
    order       = 11,    # just after generic 'deformer' (order=10)
)