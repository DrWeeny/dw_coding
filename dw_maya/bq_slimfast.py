"""PySide6 UI for the Slimfast weight painting tool.

Replaces the legacy Maya cmds UI (bq_slimfast_py3.py) with a proper
PySide6 QWidget.  All Maya logic is delegated to the controller so the
UI itself contains zero cmds calls and is testable without a Maya session.

Usage (run inside Maya):
    from dw_maya.dw_paint.slimfast_widget import SlimfastWidget
    SlimfastWidget.show_docked()   # dock to Maya's right panel
    # or
    SlimfastWidget.show_window()   # floating window

Classes:
    SliderWithButton   — QSlider + QDoubleSpinBox + QPushButton composite
    SlimfastController — all Maya logic, no PySide6 imports
    SlimfastWidget     — PySide6 QWidget, signals connect to controller

Version: 2.0.0
Author:  DrWeeny
"""

from __future__ import annotations

from typing import List, Optional
from functools import partial

from maya import cmds, mel
import maya.OpenMayaUI as omui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt, Signal, Slot
    from shiboken6 import wrapInstance
except ImportError:
    # Fallback for older Maya versions shipping PySide2
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Qt, Signal, Slot
    from shiboken2 import wrapInstance
import dw_maya.dw_paint
from dw_maya.dw_paint.protocol import WeightSource
from dw_maya.dw_paint.weight_source import (
    resolve_weight_sources,
    paint_weight_source,
    apply_operation,
)
from dw_maya.dw_nucleus_utils import NClothMap
import dw_maya.dw_maya_utils
from dw_maya.dw_maya_utils.dw_maya_components import selectBorder
import dw_maya.dw_nucleus_utils.dw_core
import dw_maya.dw_nucleus_utils.dw_nucleus_paint
from dw_logger import get_logger

logger = get_logger()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _maya_main_window() -> QtWidgets.QMainWindow:
    """Return Maya's main QMainWindow so we can parent to it."""
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QMainWindow)


# ---------------------------------------------------------------------------
# Reusable composite widget: slider + spinbox + button
# ---------------------------------------------------------------------------

class SliderWithButton(QtWidgets.QWidget):
    """Horizontal slider bidirectionally synced with a spinbox, plus a button.

    Replaces Maya's ``floatSliderButtonGrp`` which has no PySide6 equivalent.

    Signals:
        value_changed(float): Emitted whenever the slider or spinbox changes.
        button_clicked():     Emitted when the action button is pressed.

    Args:
        label:       Label shown to the left.
        btn_label:   Text on the action button.
        min_val:     Slider minimum.
        max_val:     Slider maximum.
        default:     Initial value.
        decimals:    Number of decimal places in the spinbox.
        step:        Single step size for the spinbox.
        parent:      Optional parent widget.

    Example:
        slider = SliderWithButton('weight', 'Set', 0.0, 1.0, 0.5)
        slider.value_changed.connect(on_weight_changed)
        slider.button_clicked.connect(on_set_clicked)
    """

    value_changed = Signal(float)
    button_clicked = Signal()

    def __init__(self,
                 label: str = '',
                 btn_label: str = 'Set',
                 min_val: float = 0.0,
                 max_val: float = 1.0,
                 default: float = 0.5,
                 decimals: int = 2,
                 step: float = 0.01,
                 parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        self._min = min_val
        self._max = max_val
        self._scale = 10 ** decimals  # int slider resolution

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if label:
            lbl = QtWidgets.QLabel(label)
            lbl.setFixedWidth(48)
            layout.addWidget(lbl)

        self._spinbox = QtWidgets.QDoubleSpinBox()
        self._spinbox.setRange(min_val, max_val)
        self._spinbox.setDecimals(decimals)
        self._spinbox.setSingleStep(step)
        self._spinbox.setValue(default)
        self._spinbox.setFixedWidth(58)
        layout.addWidget(self._spinbox)

        self._slider = QtWidgets.QSlider(Qt.Horizontal)
        self._slider.setRange(
            int(min_val * self._scale),
            int(max_val * self._scale)
        )
        self._slider.setValue(int(default * self._scale))
        layout.addWidget(self._slider, stretch=1)

        self._button = QtWidgets.QPushButton(btn_label)
        self._button.setFixedWidth(44)
        layout.addWidget(self._button)

        # Bidirectional sync
        self._slider.valueChanged.connect(self._on_slider_changed)
        self._spinbox.valueChanged.connect(self._on_spinbox_changed)
        self._button.clicked.connect(self.button_clicked)

        self._syncing = False  # prevent feedback loops

    # ------------------------------------------------------------------

    def _on_slider_changed(self, int_val: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        float_val = int_val / self._scale
        self._spinbox.setValue(float_val)
        self._syncing = False
        self.value_changed.emit(float_val)

    def _on_spinbox_changed(self, float_val: float) -> None:
        if self._syncing:
            return
        self._syncing = True
        self._slider.setValue(int(float_val * self._scale))
        self._syncing = False
        self.value_changed.emit(float_val)

    @property
    def value(self) -> float:
        return self._spinbox.value()

    @value.setter
    def value(self, v: float) -> None:
        self._spinbox.setValue(v)


# ---------------------------------------------------------------------------
# Controller — all Maya logic, zero PySide6
# ---------------------------------------------------------------------------

class SlimfastController:
    """Encapsulates all Maya logic for the Slimfast tool.

    The UI only calls methods on this controller and connects to its
    signals — it never imports cmds or calls Maya directly.

    Args:
        signals: A QObject subclass that carries Qt signals (injected by
                 SlimfastWidget so we stay decoupled from PySide6 here).
    """

    def __init__(self, signals: 'SlimfastSignals'):
        self._signals = signals
        self._sources: List[WeightSource] = []
        self._active: Optional[WeightSource] = None
        self._active_map: Optional[str] = None
        self._clipboard: Optional[List[float]] = None
        self._mesh: Optional[str] = None
        self._mode: str = 'all'

    # ------------------------------------------------------------------
    # Source / map management
    # ------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        """Switch between 'deformer', 'nucleus', and 'all' backends."""
        self._mode = mode
        self.refresh()

    def refresh(self) -> None:
        """Re-resolve weight sources from the current Maya selection."""
        sel = cmds.filterExpand(selectionMask=[12, 31, 32, 34]) or []
        if not sel:
            self._sources = []
            self._active = None
            self._active_map = None
            self._mesh = None
            self._signals.sources_changed.emit([], [])
            logger.warning("Select a polyMesh and refresh.")
            return

        mesh = sel[0].split('.')[0]
        self._mesh = mesh

        try:
            self._sources = resolve_weight_sources(mesh, mode=self._mode)
        except Exception as e:
            logger.error(f"Failed to resolve weight sources for '{mesh}': {e}")
            self._sources = []

        node_labels = [self._source_label(s) for s in self._sources]
        map_lists = [s.available_maps() for s in self._sources]
        self._signals.sources_changed.emit(node_labels, map_lists)
        self._signals.mesh_changed.emit(mesh)

        if self._sources:
            self.select_source(0)
        else:
            self._active = None
            self._active_map = None
            self._signals.active_changed.emit(None)

    def select_source(self, index: int) -> None:
        """Set the active WeightSource by list index and auto-select its first map."""
        if 0 <= index < len(self._sources):
            self._active = self._sources[index]
            maps = self._active.available_maps()
            self._signals.maps_changed.emit(maps)
            if maps:
                self.select_map(maps[0])
            else:
                self._active_map = None
                self._signals.active_changed.emit(self._active)
        else:
            self._active = None
            self._active_map = None
            self._signals.active_changed.emit(None)

    def select_map(self, map_name: str) -> None:
        """Activate a map on the current source node."""
        if self._active is None:
            return
        try:
            self._active.use_map(map_name)
            self._active_map = map_name
            self._signals.active_changed.emit(self._active)
        except ValueError as e:
            logger.warning(str(e))

    def _source_label(self, source: WeightSource) -> str:
        """Human-readable label for a WeightSource node."""
        try:
            node_type = cmds.nodeType(source.node_name)
        except Exception:
            node_type = '?'
        return f"[{node_type}] {source.node_name}"

    def _require_active(self) -> bool:
        if self._active is None or self._active_map is None:
            logger.warning("No weight source / map selected — refresh the list.")
            return False
        return True

    # ------------------------------------------------------------------
    # Weight operations — all uniform, no type branching
    # ------------------------------------------------------------------

    def paint(self) -> None:
        """Open artisan for the active source and map."""
        if not self._require_active():
            return
        try:
            # use_map already called by select_map; paint() dispatches correctly
            self._active.paint()
        except Exception as e:
            logger.error(f"Paint failed: {e}")

    def set_weight(self, value: float) -> None:
        """Flood-replace a scalar weight on the current vertex selection."""
        if not self._require_active():
            return
        sel = cmds.filterExpand(selectionMask=[31, 32, 34]) or []
        if sel:
            cmds.ConvertSelectionToVertices()
            vtx = cmds.filterExpand(selectionMask=31) or []
            if vtx:
                indices = dw_maya.dw_maya_utils.extract_id(vtx)
                mask = [[i, i + 1] for i in indices]
                apply_operation(self._active, 'flood', value=value, mask=mask)
                return
        apply_operation(self._active, 'flood', value=value)

    def set_weight_all(self, value: float) -> None:
        """Flood-replace all vertices regardless of selection."""
        if not self._require_active():
            return
        apply_operation(self._active, 'flood', value=value)

    def smooth(self, iterations: int = 1) -> None:
        """Topology-based smooth via numpy path."""
        if not self._require_active():
            return
        try:
            apply_operation(self._active, 'smooth', iterations=iterations, factor=0.5)
        except Exception as e:
            logger.error(f"Smooth failed: {e}")

    def smooth_artisan(self, iterations: int = 1) -> None:
        """Smooth via Maya artisan (requires paint tool to be active).

        The correct artisan context is determined by the node type stored on
        the active source, so no manual isinstance check is needed — the MEL
        command is routed through the source's own paint context.
        """
        from dw_maya.dw_nucleus_utils.dw_ncloth_class import NClothMap
        if isinstance(self._active, NClothMap):
            try:
                for _ in range(iterations):
                    dw_maya.dw_nucleus_utils.dw_nucleus_paint.flood_smooth_vtx_map()
                logger.info(f"Nucleus artisan smooth x{iterations}.")
            except Exception as e:
                raise RuntimeError(
                    f"Click \"Paint\" before using artisan smooth. Detail: {e}"
                )
        else:
            try:
                mel.eval('artAttrPaintOperation artAttrCtx Smooth')
            except RuntimeError:
                raise RuntimeError('Click "Paint" before using artisan smooth.')
            for _ in range(iterations):
                cmds.artAttrCtx(cmds.currentCtx(), edit=True, clear=True)
            mel.eval('artAttrPaintOperation artAttrCtx Replace')
            logger.info(f"Artisan smooth x{iterations}.")

    def copy_weights(self) -> None:
        """Store the active source's weights in the clipboard."""
        if not self._require_active():
            return
        self._clipboard = self._active.get_weights()
        if self._clipboard:
            logger.info(
                f"Copied {len(self._clipboard)} weights from "
                f"'{self._active.node_name}' map='{self._active_map}'"
            )

    def paste_weights(self) -> None:
        """Paste clipboard weights to the active source."""
        if not self._require_active():
            return
        if not self._clipboard:
            logger.warning("Clipboard is empty — copy weights first.")
            return
        if len(self._clipboard) != self._active.vtx_count:
            logger.warning(
                f"Clipboard has {len(self._clipboard)} values but active "
                f"source has {self._active.vtx_count} vertices."
            )
            return
        self._active.set_weights(self._clipboard)
        logger.info(f"Pasted weights to '{self._active.node_name}'.")

    def select_vertices_by_weight(self,
                                  from_zero: bool = True,
                                  tolerance: float = 0.0,
                                  key_mod: int = 0) -> None:
        """Select vertices near 0 (from_zero=True) or near 1 (False)."""
        if not self._require_active():
            return
        weights = self._active.get_weights()
        if not weights:
            return
        if from_zero:
            indices = [i for i, w in enumerate(weights) if w <= tolerance]
        else:
            indices = [i for i, w in enumerate(weights) if w >= 1.0 - tolerance]

        mesh = self._active.mesh_name
        if not indices:
            cmds.select(clear=True)
            logger.info("No vertices match the weight criteria.")
            return

        mel.eval(f'doMenuComponentSelection("{mesh}", "vertex")')
        ranges = dw_maya.dw_maya_utils.create_maya_ranges(indices)
        vtx_list = [f'{mesh}.vtx[{r}]' for r in ranges]

        if key_mod == 1:
            cmds.select(vtx_list, toggle=True)
        elif key_mod == 4:
            cmds.select(vtx_list, deselect=True)
        elif key_mod == 5:
            cmds.select(vtx_list, add=True)
        else:
            cmds.select(vtx_list, replace=True)

    def select_all(self, key_mod: int = 0) -> None:
        """Select all vertices of the active mesh."""
        if not self._require_active():
            return
        mesh = self._active.mesh_name
        n = self._active.vtx_count
        mel.eval(f'doMenuComponentSelection("{mesh}", "vertex")')
        vertices = f'{mesh}.vtx[0:{n - 1}]'
        if key_mod == 1:
            cmds.select(vertices, toggle=True)
        else:
            cmds.select(vertices, replace=True)

    def border_selection(self) -> None:
        """Select border vertices of the current component selection."""
        selectBorder()

    def set_artisan_value(self, value: float) -> None:
        """Push value to artisan context (absolute/replace mode).

        Routes to the correct artisan context based on the active source's
        node type — no manual isinstance check needed in the UI layer.
        """
        if not self._require_active():
            return
        from dw_maya.dw_nucleus_utils.dw_ncloth_class import NClothMap
        if isinstance(self._active, NClothMap):
            try:
                dw_maya.dw_nucleus_utils.dw_nucleus_paint.set_cfx_brush_val(
                    value, mod='absolute'
                )
            except Exception as e:
                logger.debug(f"set_cfx_brush_val failed (paint tool not active?): {e}")
            return
        for ctx in ('artAttrContext', 'artAttrBlendShapeContext'):
            try:
                cmds.artAttrCtx(ctx, edit=True, value=value)
                cmds.artAttrCtx(ctx, edit=True, selectedattroper='absolute')
                return
            except Exception:
                continue


# ---------------------------------------------------------------------------
# Qt signals relay (needed because controller has no QObject parent)
# ---------------------------------------------------------------------------

class SlimfastSignals(QtCore.QObject):
    """Qt signals emitted by SlimfastController."""

    #: Emitted when the source list changes.
    #: Payload: (labels: list[str], is_nucleus: list[bool])
    sources_changed = Signal(list, list)
    #: Emitted when the active mesh changes. Payload: mesh name string.
    mesh_changed = Signal(str)
    #: Emitted when the active WeightSource changes. Payload: WeightSource or None.
    active_changed = Signal(object)
    #: maps available on the currently selected node
    maps_changed = Signal(list)



# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class SlimfastWidget(QtWidgets.QWidget):
    """PySide6 replacement for the legacy Slimfast cmds UI."""

    _instance: Optional['SlimfastWidget'] = None

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent or _maya_main_window())
        self.setWindowTitle('Slim fast 2.0')
        self.setWindowFlags(Qt.Window)
        self.setMinimumWidth(260)
        self.setMaximumWidth(320)

        self._signals = SlimfastSignals(self)
        self._ctrl = SlimfastController(self._signals)

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)
        root.addWidget(self._build_deformer_group())
        root.addWidget(self._build_weights_group())
        root.addWidget(self._build_smooth_group())
        root.addWidget(self._build_select_group())
        root.addStretch()

    def _build_deformer_group(self) -> QtWidgets.QGroupBox:
        grp = QtWidgets.QGroupBox('Deformer')
        grp.setCheckable(True)
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        # --- Mode toggle + Refresh + Help ---
        top_row = QtWidgets.QHBoxLayout()
        self._mode_group = QtWidgets.QButtonGroup(self)
        for label, mode in [('All', 'all'), ('Deformer', 'deformer'), ('nCloth', 'nucleus')]:
            btn = QtWidgets.QRadioButton(label)
            btn.setProperty('mode', mode)
            if mode == 'all':
                btn.setChecked(True)
            self._mode_group.addButton(btn)
            top_row.addWidget(btn)
        top_row.addStretch()

        refresh_btn = QtWidgets.QPushButton('↺')
        refresh_btn.setFixedWidth(28)
        refresh_btn.setToolTip('Update list from selection')
        refresh_btn.clicked.connect(self._on_refresh)
        top_row.addWidget(refresh_btn)

        help_btn = QtWidgets.QPushButton('?')
        help_btn.setFixedWidth(24)
        help_btn.clicked.connect(self._show_help)
        top_row.addWidget(help_btn)
        lay.addLayout(top_row)

        # --- Mesh label ---
        self._mesh_label = QtWidgets.QLabel('Nothing selected')
        self._mesh_label.setAlignment(Qt.AlignCenter)
        font = self._mesh_label.font()
        font.setBold(True)
        self._mesh_label.setFont(font)
        lay.addWidget(self._mesh_label)

        # --- Node combo (one entry per WeightMap node) ---
        self._source_combo = QtWidgets.QComboBox()
        self._source_combo.setMinimumWidth(220)
        self._source_combo.setToolTip('Select deformer / nucleus node')
        lay.addWidget(self._source_combo)

        # --- Map combo (one entry per available_maps() on the selected node) ---
        self._map_combo = QtWidgets.QComboBox()
        self._map_combo.setMinimumWidth(220)
        self._map_combo.setToolTip('Select weight map')
        lay.addWidget(self._map_combo)

        # --- Map type badge (nucleus only) ---
        self._map_type_label = QtWidgets.QLabel()
        self._map_type_label.setAlignment(Qt.AlignCenter)
        self._map_type_label.setStyleSheet('font-size: 11px;')
        self._map_type_label.hide()
        lay.addWidget(self._map_type_label)

        # --- Copy / Paste ---
        cp_row = QtWidgets.QHBoxLayout()
        self._copy_btn = QtWidgets.QPushButton('Copy weights')
        self._paste_btn = QtWidgets.QPushButton('Paste weights')
        cp_row.addWidget(self._copy_btn)
        cp_row.addWidget(self._paste_btn)
        lay.addLayout(cp_row)

        # --- Envelope spinbox ---
        env_row = QtWidgets.QHBoxLayout()
        env_row.addWidget(QtWidgets.QLabel('envelope'))
        self._envelope_slider = QtWidgets.QDoubleSpinBox()
        self._envelope_slider.setRange(0.0, 1.0)
        self._envelope_slider.setDecimals(2)
        self._envelope_slider.setSingleStep(0.01)
        self._envelope_slider.setFixedWidth(70)
        env_row.addWidget(self._envelope_slider)
        env_row.addStretch()
        lay.addLayout(env_row)

        # --- Paint button ---
        self._paint_btn = QtWidgets.QPushButton('▶  Paint')
        self._paint_btn.setFixedHeight(32)
        self._paint_btn.setStyleSheet(
            'QPushButton { background-color: #a8a820; color: #1a1a00; font-weight: bold; }'
            'QPushButton:hover { background-color: #c8c830; }'
        )
        lay.addWidget(self._paint_btn)

        return grp

    def _build_weights_group(self) -> QtWidgets.QGroupBox:
        grp = QtWidgets.QGroupBox('Weights')
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        set_row = QtWidgets.QHBoxLayout()
        self._set0_btn = QtWidgets.QPushButton('Set to 0')
        self._set0_btn.setStyleSheet('background-color: #282828; color: #aaaaaa;')
        self._set1_btn = QtWidgets.QPushButton('Set to 1')
        self._set1_btn.setStyleSheet('background-color: #bbbbbb; color: #111111;')
        set_row.addWidget(self._set0_btn)
        set_row.addWidget(self._set1_btn)
        lay.addLayout(set_row)

        self._weight_slider = SliderWithButton(
            label='weight', btn_label='Set',
            min_val=0.0, max_val=1.0, default=0.5,
            decimals=2, step=0.01
        )
        lay.addWidget(self._weight_slider)
        return grp

    def _build_smooth_group(self) -> QtWidgets.QGroupBox:
        grp = QtWidgets.QGroupBox('Smooth  (paint tool must be active)')
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        quick_row = QtWidgets.QHBoxLayout()
        for n in (2, 5, 10, 20):
            btn = QtWidgets.QPushButton(str(n))
            btn.setFixedWidth(44)
            btn.clicked.connect(partial(self._on_smooth, n))
            quick_row.addWidget(btn)
        quick_row.addStretch()
        lay.addLayout(quick_row)

        iter_row = QtWidgets.QHBoxLayout()
        iter_row.addWidget(QtWidgets.QLabel('iterations'))
        self._iter_spinbox = QtWidgets.QSpinBox()
        self._iter_spinbox.setRange(1, 200)
        self._iter_spinbox.setValue(25)
        self._iter_spinbox.setFixedWidth(52)
        iter_row.addWidget(self._iter_spinbox)

        self._iter_slider = QtWidgets.QSlider(Qt.Horizontal)
        self._iter_slider.setRange(1, 200)
        self._iter_slider.setValue(25)
        iter_row.addWidget(self._iter_slider, stretch=1)

        self._iter_slider.valueChanged.connect(self._iter_spinbox.setValue)
        self._iter_spinbox.valueChanged.connect(self._iter_slider.setValue)

        flood_btn = QtWidgets.QPushButton('Flood')
        flood_btn.setFixedWidth(48)
        flood_btn.clicked.connect(self._on_smooth_flood)
        iter_row.addWidget(flood_btn)
        lay.addLayout(iter_row)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel('via'))
        self._smooth_mode = QtWidgets.QComboBox()
        self._smooth_mode.addItems(['artisan (viewport)', 'numpy (no viewport)'])
        mode_row.addWidget(self._smooth_mode)
        mode_row.addStretch()
        lay.addLayout(mode_row)
        return grp

    def _build_select_group(self) -> QtWidgets.QGroupBox:
        grp = QtWidgets.QGroupBox('Select vertices')
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        self._sel_all_btn = QtWidgets.QPushButton('ALL  (shift = invert)')
        lay.addWidget(self._sel_all_btn)

        sel_row = QtWidgets.QHBoxLayout()
        self._sel0_btn = QtWidgets.QPushButton('Weight = 0')
        self._sel0_btn.setStyleSheet('background-color: #282828; color: #aaaaaa;')
        self._sel1_btn = QtWidgets.QPushButton('Weight = 1')
        self._sel1_btn.setStyleSheet('background-color: #bbbbbb; color: #111111;')
        sel_row.addWidget(self._sel0_btn)
        sel_row.addWidget(self._sel1_btn)
        lay.addLayout(sel_row)

        tol_row = QtWidgets.QHBoxLayout()
        tol_row.addWidget(QtWidgets.QLabel('tolerance'))
        self._tol_spinbox = QtWidgets.QDoubleSpinBox()
        self._tol_spinbox.setRange(0.0, 1.0)
        self._tol_spinbox.setDecimals(2)
        self._tol_spinbox.setSingleStep(0.01)
        self._tol_spinbox.setFixedWidth(60)
        tol_row.addWidget(self._tol_spinbox)

        self._tol_slider = QtWidgets.QSlider(Qt.Horizontal)
        self._tol_slider.setRange(0, 100)
        self._tol_slider.setValue(0)
        tol_row.addWidget(self._tol_slider, stretch=1)

        self._tol_slider.valueChanged.connect(lambda v: self._tol_spinbox.setValue(v / 100.0))
        self._tol_spinbox.valueChanged.connect(lambda v: self._tol_slider.setValue(int(v * 100)))
        lay.addLayout(tol_row)

        self._border_btn = QtWidgets.QPushButton('Border selection')
        lay.addWidget(self._border_btn)
        return grp

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        # Controller → UI
        self._signals.sources_changed.connect(self._on_sources_changed)
        self._signals.maps_changed.connect(self._on_maps_changed)  # NEW
        self._signals.mesh_changed.connect(self._mesh_label.setText)
        self._signals.active_changed.connect(self._on_active_changed)

        # Mode toggle
        self._mode_group.buttonClicked.connect(self._on_mode_changed)

        # Node combo — calls select_source
        self._source_combo.currentIndexChanged.connect(self._on_source_combo_changed)
        # Map combo — calls select_map                                    # NEW
        self._map_combo.currentTextChanged.connect(self._on_map_combo_changed)

        # Deformer group
        self._copy_btn.clicked.connect(self._ctrl.copy_weights)
        self._paste_btn.clicked.connect(self._ctrl.paste_weights)
        self._paint_btn.clicked.connect(self._ctrl.paint)
        self._envelope_slider.valueChanged.connect(self._on_envelope_changed)

        # Weights group
        self._set0_btn.clicked.connect(partial(self._ctrl.set_weight_all, 0.0))
        self._set1_btn.clicked.connect(partial(self._ctrl.set_weight_all, 1.0))
        self._weight_slider.button_clicked.connect(
            partial(self._ctrl.set_weight, self._weight_slider.value)
        )
        self._weight_slider.value_changed.connect(self._ctrl.set_artisan_value)

        # Select group
        self._sel_all_btn.clicked.connect(self._on_select_all)
        self._sel0_btn.clicked.connect(self._on_select_zero)
        self._sel1_btn.clicked.connect(self._on_select_one)
        self._border_btn.clicked.connect(self._ctrl.border_selection)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_refresh(self) -> None:
        self._ctrl.refresh()

    @Slot(QtWidgets.QAbstractButton)
    def _on_mode_changed(self, btn: QtWidgets.QAbstractButton) -> None:
        self._ctrl.set_mode(btn.property('mode'))

    @Slot(list, list)
    def _on_sources_changed(self, node_labels: list, map_lists: list) -> None:
        """Rebuild the node combo.

        Each item stores its real source index in Qt.UserRole so
        _on_source_combo_changed can resolve it correctly.
        The map combo is filled separately via _on_maps_changed once
        the controller auto-selects the first source.
        """
        self._source_model = QtGui.QStandardItemModel()

        if not node_labels:
            empty = QtGui.QStandardItem('— no sources —')
            empty.setEnabled(False)
            self._source_model.appendRow(empty)
            self._source_combo.blockSignals(True)
            self._source_combo.setModel(self._source_model)
            self._source_combo.blockSignals(False)
            self._map_combo.clear()
            return

        for source_idx, label in enumerate(node_labels):
            item = QtGui.QStandardItem(label)
            item.setData(source_idx, Qt.UserRole)
            # Teal for nucleus nodes so they remain visually distinct
            if '[nCloth]' in label or '[nRigid]' in label:
                item.setForeground(QtGui.QBrush(QtGui.QColor('#4ecdc4')))
            self._source_model.appendRow(item)

        self._source_combo.blockSignals(True)
        self._source_combo.setModel(self._source_model)
        self._source_combo.blockSignals(False)

        # Controller already called select_source(0) in refresh(),
        # which emits maps_changed — no need to call it again here.

    @Slot(list)
    def _on_maps_changed(self, maps: list) -> None:
        """Rebuild the map combo when the active node changes."""
        self._map_combo.blockSignals(True)
        self._map_combo.clear()
        for map_name in maps:
            self._map_combo.addItem(map_name)
        self._map_combo.blockSignals(False)
        # Auto-activate the first map — controller also does this, but
        # keeping it here ensures the combo and controller stay in sync
        # even when maps_changed fires before the combo is connected.
        if maps:
            self._ctrl.select_map(maps[0])

    @Slot(int)
    def _on_source_combo_changed(self, combo_index: int) -> None:
        """Resolve combo_index → real source index, skipping disabled rows."""
        if combo_index < 0:
            return
        model = self._source_combo.model()
        if model is None:
            return
        item = model.item(combo_index)
        if item is None or not item.isEnabled():
            return
        source_idx = item.data(Qt.UserRole)
        if source_idx is not None:
            self._ctrl.select_source(source_idx)
            # maps_changed will fire from the controller, filling _map_combo

    @Slot(str)
    def _on_map_combo_changed(self, map_name: str) -> None:
        """Forward map selection to the controller."""
        if map_name:
            self._ctrl.select_map(map_name)

    @Slot(object)
    def _on_active_changed(self, source: Optional[WeightSource]) -> None:
        has_source = source is not None
        for w in (self._paint_btn, self._copy_btn, self._paste_btn,
                  self._set0_btn, self._set1_btn, self._weight_slider):
            w.setEnabled(has_source)

        # --- Map type badge (nucleus only) ---
        if isinstance(source, NClothMap):
            _MAP_TYPE_INFO = {
                0: ('● None  (map disabled)', '#888888'),
                1: ('● PerVertex', '#4ecdc4'),
                2: ('● Texture', '#ddcc44'),
            }
            try:
                active_map = self._ctrl._active_map
                mt = source.map_type(active_map) if active_map else 0
                text, color = _MAP_TYPE_INFO.get(mt, (f'● type={mt}', '#aaaaaa'))
                self._map_type_label.setText(text)
                self._map_type_label.setStyleSheet(f'color: {color}; font-size: 11px;')
                self._map_type_label.show()
            except Exception:
                self._map_type_label.hide()
        else:
            self._map_type_label.hide()

        # --- Envelope spinbox ---
        if has_source and not isinstance(source, NClothMap):
            env_attr = f'{source.node_name}.envelope'
            if cmds.objExists(env_attr):
                try:
                    val = cmds.getAttr(env_attr)
                    self._envelope_slider.blockSignals(True)
                    self._envelope_slider.setValue(val)
                    self._envelope_slider.blockSignals(False)
                    self._envelope_slider.setEnabled(True)
                except Exception:
                    self._envelope_slider.setEnabled(False)
            else:
                self._envelope_slider.setEnabled(False)
        else:
            self._envelope_slider.setEnabled(False)

    @Slot(float)
    def _on_envelope_changed(self, value: float) -> None:
        if self._ctrl._active and not isinstance(self._ctrl._active, NClothMap):
            env_attr = f'{self._ctrl._active.node_name}.envelope'
            if cmds.objExists(env_attr):
                try:
                    cmds.setAttr(env_attr, value)
                except Exception as e:
                    logger.warning(f"Could not set envelope: {e}")

    def _on_smooth(self, iterations: int) -> None:
        if self._smooth_mode.currentIndex() == 0:
            try:
                self._ctrl.smooth_artisan(iterations)
            except RuntimeError as e:
                QtWidgets.QMessageBox.warning(self, 'Smooth', str(e))
        else:
            self._ctrl.smooth(iterations)

    def _on_smooth_flood(self) -> None:
        self._on_smooth(self._iter_spinbox.value())

    def _on_select_all(self) -> None:
        mods = QtWidgets.QApplication.keyboardModifiers()
        self._ctrl.select_all(1 if (mods & Qt.ShiftModifier) else 0)

    def _on_select_zero(self) -> None:
        mods = QtWidgets.QApplication.keyboardModifiers()
        self._ctrl.select_vertices_by_weight(
            from_zero=True,
            tolerance=self._tol_spinbox.value(),
            key_mod=self._qt_mods_to_maya(mods)
        )

    def _on_select_one(self) -> None:
        mods = QtWidgets.QApplication.keyboardModifiers()
        self._ctrl.select_vertices_by_weight(
            from_zero=False,
            tolerance=self._tol_spinbox.value(),
            key_mod=self._qt_mods_to_maya(mods)
        )

    @staticmethod
    def _qt_mods_to_maya(mods: Qt.KeyboardModifiers) -> int:
        shift = bool(mods & Qt.ShiftModifier)
        ctrl = bool(mods & Qt.ControlModifier)
        if ctrl and shift:
            return 5
        if ctrl:
            return 4
        if shift:
            return 1
        return 0

    # ------------------------------------------------------------------
    # Help dialog
    # ------------------------------------------------------------------

    def _show_help(self) -> None:
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle('Slimfast — help')
        msg.setText(
            "<b>Slimfast 2.0</b> — weight painting tool<br><br>"
            "<b>Mode toggle:</b> switch between deformer, nCloth, or both<br>"
            "<b>↺ Refresh:</b> re-scan selection for weight sources<br>"
            "<b>Copy / Paste:</b> transfer weights between sources<br>"
            "<b>Paint:</b> open Maya artisan for the active source<br>"
            "<b>Set 0 / 1:</b> flood all vertices<br>"
            "<b>Weight slider → Set:</b> flood current selection<br>"
            "<b>Smooth:</b> artisan path needs paint tool active;<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;numpy path works any time<br>"
            "<b>Select vertices:</b><br>"
            "&nbsp;&nbsp;click = select<br>"
            "&nbsp;&nbsp;Ctrl+click = deselect<br>"
            "&nbsp;&nbsp;Shift+click = toggle<br>"
            "&nbsp;&nbsp;Ctrl+Shift+click = add<br>"
        )
        msg.exec()

    # ------------------------------------------------------------------
    # Class-level show helpers
    # ------------------------------------------------------------------

    @classmethod
    def show_window(cls) -> 'SlimfastWidget':
        """Show as a floating window, reusing an existing instance."""
        if cls._instance is None or not cls._instance.isVisible():
            cls._instance = cls()
        cls._instance.show()
        cls._instance.raise_()
        cls._instance.activateWindow()
        return cls._instance

    @classmethod
    def show_docked(cls) -> 'SlimfastWidget':
        """Dock into Maya's right-side panel area."""
        widget = cls.show_window()
        # Maya's docking API wraps the widget in a workspaceControl
        try:
            ctrl_name = 'SlimfastWorkspaceControl'
            if cmds.workspaceControl(ctrl_name, exists=True):
                cmds.deleteUI(ctrl_name)
            cmds.workspaceControl(
                ctrl_name,
                label='Slimfast 2.0',
                retain=False,
                floating=False,
                dockToMainWindow=('right', False),
            )
            # Reparent our widget inside the workspace control
            workspace_ptr = omui.MQtUtil.findControl(ctrl_name)
            workspace_widget = wrapInstance(int(workspace_ptr), QtWidgets.QWidget)
            workspace_layout = workspace_widget.layout()
            if workspace_layout is None:
                workspace_layout = QtWidgets.QVBoxLayout(workspace_widget)
            workspace_layout.setContentsMargins(0, 0, 0, 0)
            workspace_layout.addWidget(widget)
        except Exception as e:
            logger.warning(f"Could not dock Slimfast: {e}. Showing as floating window.")
        return widget

if __name__ == '__main__':
    _instance = SlimfastWidget.show_window()