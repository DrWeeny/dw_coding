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

Version: 2.3.0
Author:  DrWeeny
"""

from __future__ import annotations

from typing import Optional
from functools import partial

from maya import cmds
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

from .wgt_signals import SlimfastSignals
from .cmds import SlimfastController
from .wgt_section import CollapsibleSection
from . import wgt_deformer_panel
from dw_utils import data_hub
import dw_maya.dw_paint
import dw_maya.dw_pyqt_utils.dw_btn_storage
from dw_maya.dw_pyqt_utils.wgt_slider import RangeSliderWithSpinbox, SliderWithButton
from dw_maya.dw_paint.protocol import WeightSource

from dw_maya.dw_nucleus_utils import NClothMap
import dw_maya.dw_maya_utils
import dw_maya.dw_nucleus_utils.dw_core
import dw_maya.dw_nucleus_utils.dw_nucleus_paint
from dw_logger import get_logger

from dw_ressources import get_ressource_path

ICON_PIPETTE =  str(get_ressource_path("pipette.png"))

logger = get_logger()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _maya_main_window() -> QtWidgets.QMainWindow:
    """Return Maya's main QMainWindow so we can parent to it."""
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QMainWindow)

# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

class SlimfastWidget(QtWidgets.QWidget):
    """PySide6 replacement for the legacy Slimfast cmds UI."""

    _instance: Optional['SlimfastWidget'] = None
    _HUB_KEY = "slimfast.storage_buttons"

    # Minimum seconds between two automatic clamp-sync reads on mouse-enter.
    _CLAMP_SYNC_INTERVAL: float = 2.0

    # QProperty so external scripts / shelf buttons can read/write smooth iterations
    smooth_iterations_changed = Signal(int)

    # Colour palette per backend type
    _SOURCE_COLORS = {
        'nCloth':             '#4ecdc4',
        'nRigid':             '#4ecdc4',
        'blendShape':         '#e8a838',
        'skinCluster':        '#a0c8ff',
        'cluster':            '#cccccc',
        'softMod':            '#cccccc',
        'wire':               '#cccccc',
        'VertexColorAlpha':   '#cc88dd',
        'vtxColor':           '#cc88dd',
    }

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent or _maya_main_window())
        self.setWindowTitle('Slimfast 2.0')
        self.setWindowFlags(Qt.Window)
        self.setMinimumWidth(280)

        self._org = "DrWeeny"
        self._appname = "SlimfastWidget"

        self._signals = SlimfastSignals(self)
        self._ctrl = SlimfastController(self._signals)

        # Tracks the last active source type key so we can persist smooth mode
        # before switching to a new source type.
        self._src_type_key: str = 'deformer'

        self._build_ui()
        self._connect_signals()

        # Restore persisted preferences
        settings = QtCore.QSettings(self._org, self._appname)
        saved_iter = settings.value('smooth_iterations', 40, type=int)
        self.set_smooth_iterations(saved_iter)
        # Restore smooth mode preference (global — not per source type)
        saved_smooth = settings.value('smooth_mode', 0, type=int)
        self._smooth_mode.blockSignals(True)
        self._smooth_mode.setCurrentIndex(saved_smooth)
        self._smooth_mode.blockSignals(False)
        # Restore selection mode (Value vs Range)
        sel_value_mode = settings.value('sel_value_mode', False, type=bool)
        if sel_value_mode:
            self._sel_mode_check.setChecked(True)  # triggers _on_sel_mode_toggled

        # Restore storage buttons from in-session DataHub cache
        self._restore_storage_from_hub()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # Build content groups first (storage panel must exist before menu bar
        # wires its QAction, because setChecked() fires the toggled signal).
        deformer_grp = self._build_deformer_group()
        weights_grp = self._build_weights_group()
        smooth_grp = self._build_smooth_group()
        select_grp = self._build_select_group()
        self._advanced_section = self._build_advanced_section()
        self._transfer_section = self._build_transfer_section()
        self._remap_section = self._build_remap_section()
        self._storage_panel = self._build_storage_panel()

        # Menu bar — View > Storage expanded (reads QSettings for initial state)
        self._menu_bar = self._build_menu_bar()
        root.addWidget(self._menu_bar)

        # Main horizontal split: left tool groups | right storage column
        main_area = QtWidgets.QHBoxLayout()
        main_area.setSpacing(6)
        main_area.setContentsMargins(0, 0, 0, 0)

        left_col = QtWidgets.QVBoxLayout()
        left_col.setSpacing(4)
        left_col.addWidget(deformer_grp)
        left_col.addWidget(weights_grp)
        left_col.addWidget(smooth_grp)
        left_col.addWidget(select_grp)
        left_col.addWidget(self._advanced_section)
        left_col.addWidget(self._transfer_section)
        left_col.addWidget(self._remap_section)
        left_col.addStretch()
        main_area.addLayout(left_col, stretch=1)
        main_area.addWidget(self._storage_panel)

        root.addLayout(main_area)

    def _build_menu_bar(self) -> QtWidgets.QMenuBar:
        """Build top menu bar with a Pref menu to toggle the storage panel and sections."""
        menu_bar = QtWidgets.QMenuBar(self)
        view_menu = menu_bar.addMenu('Pref')

        settings = QtCore.QSettings('DrWeeny', 'SlimfastWidget')

        # --- Storage panel ---
        self._storage_action = QtWidgets.QAction('Storage expanded', self)
        self._storage_action.setCheckable(True)
        expanded = settings.value('storage_expanded', True, type=bool)
        self._storage_panel.setVisible(bool(expanded))
        self._storage_action.setChecked(bool(expanded))
        self._storage_action.toggled.connect(self._on_storage_toggled)
        view_menu.addAction(self._storage_action)

        view_menu.addSeparator()

        # --- Advanced ops section ---
        self._adv_section_action = QtWidgets.QAction('Show Advanced ops', self)
        self._adv_section_action.setCheckable(True)
        adv_visible = settings.value('adv_section_visible', False, type=bool)
        self._advanced_section.setVisible(bool(adv_visible))
        self._adv_section_action.setChecked(bool(adv_visible))
        self._adv_section_action.toggled.connect(self._advanced_section.setVisible)
        view_menu.addAction(self._adv_section_action)

        # --- Transfer section ---
        self._transfer_section_action = QtWidgets.QAction('Show Transfer', self)
        self._transfer_section_action.setCheckable(True)
        tr_visible = settings.value('transfer_section_visible', False, type=bool)
        self._transfer_section.setVisible(bool(tr_visible))
        self._transfer_section_action.setChecked(bool(tr_visible))
        self._transfer_section_action.toggled.connect(self._transfer_section.setVisible)
        view_menu.addAction(self._transfer_section_action)

        # --- Remap section ---
        self._remap_section_action = QtWidgets.QAction('Show Remap / Fit', self)
        self._remap_section_action.setCheckable(True)
        remap_visible = settings.value('remap_section_visible', False, type=bool)
        self._remap_section.setVisible(bool(remap_visible))
        self._remap_section_action.setChecked(bool(remap_visible))
        self._remap_section_action.toggled.connect(self._remap_section.setVisible)
        view_menu.addAction(self._remap_section_action)

        view_menu.addSeparator()

        # --- Auto paint ---
        self._auto_paint_action = QtWidgets.QAction('Auto > paint', self)
        self._auto_paint_action.setCheckable(True)
        auto_paint = settings.value('auto_paint', False, type=bool)
        self._auto_paint_action.setChecked(bool(auto_paint))
        self._auto_paint_action.toggled.connect(self._on_auto_paint_toggled)
        view_menu.addAction(self._auto_paint_action)

        # --- Auto Select ---
        self._auto_range_select_action = QtWidgets.QAction('Auto > range select', self)
        self._auto_range_select_action.setCheckable(True)
        auto_range_select = settings.value('auto_range_select', False, type=bool)
        self._auto_range_select_action.setChecked(bool(auto_range_select))
        self._auto_range_select_action.toggled.connect(self._on_auto_range_select_toggled)
        view_menu.addAction(self._auto_range_select_action)

        # --- Use Color Ramp ---
        self._use_color_ramp_action = QtWidgets.QAction('Use Color Ramp', self)
        self._use_color_ramp_action.setCheckable(True)
        use_color_ramp = settings.value('use_color_ramp', False, type=bool)
        self._use_color_ramp_action.setChecked(bool(use_color_ramp))
        self._use_color_ramp_action.toggled.connect(self._on_use_ramp_color_toggled)
        view_menu.addAction(self._use_color_ramp_action)

        view_menu.addSeparator()

        # --- Visible modes submenu ---
        modes_menu = view_menu.addMenu('Visible modes')
        self._mode_visibility_actions = {}
        for mode_key, btn in self._mode_btns.items():
            action = QtWidgets.QAction(btn.text(), self)
            action.setCheckable(True)
            visible = settings.value(f'mode_visible_{mode_key}', True, type=bool)
            btn.setVisible(bool(visible))
            action.setChecked(bool(visible))
            action.toggled.connect(partial(self._on_mode_visibility_changed, mode_key))
            modes_menu.addAction(action)
            self._mode_visibility_actions[mode_key] = action

        # --- Create menu ---
        create_menu = menu_bar.addMenu('Create')
        act_new_alpha = QtWidgets.QAction('New vertex alpha map…', self)
        act_new_alpha.triggered.connect(self._on_create_alpha_map)
        create_menu.addAction(act_new_alpha)

        return menu_bar

    def _build_advanced_section(self) -> CollapsibleSection:
        """Build the collapsible 'Advanced ops' section (vector / radial weights)."""
        section = CollapsibleSection('Advanced ops')
        lay = section.content_layout

        # Make the advanced section visually distinct with a QGroupBox
        group_box = QtWidgets.QGroupBox()
        group_box.setStyleSheet("QGroupBox { margin-top: 1ex; border: 1px solid #444; border-radius: 4px; padding: 4px; }")
        grp_lay = QtWidgets.QVBoxLayout(group_box)
        grp_lay.setContentsMargins(4, 8, 4, 4)
        grp_lay.setSpacing(4)
        lay.addWidget(group_box)

        # Build everything inside the group_box
        lay = grp_lay

        # --- Mode selector ---
        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel('Mode'))
        self._adv_mode_combo = QtWidgets.QComboBox()
        self._adv_mode_combo.addItems(['vector', 'radial'])
        mode_row.addWidget(self._adv_mode_combo)
        mode_row.addStretch()
        lay.addLayout(mode_row)

        # --- Falloff ---
        falloff_row = QtWidgets.QHBoxLayout()
        falloff_row.addWidget(QtWidgets.QLabel('Falloff'))
        self._adv_falloff_combo = QtWidgets.QComboBox()
        self._adv_falloff_combo.addItems(['linear', 'quadratic', 'smooth', 'smooth2'])
        falloff_row.addWidget(self._adv_falloff_combo)
        falloff_row.addStretch()
        lay.addLayout(falloff_row)

        # ---- Vector sub-widget ----------------------------------------
        self._adv_vector_widget = QtWidgets.QWidget()
        vec_lay = QtWidgets.QVBoxLayout(self._adv_vector_widget)
        vec_lay.setContentsMargins(0, 0, 0, 0)
        vec_lay.setSpacing(4)

        # Direction mode (vector / projection / distance / normal)
        vmode_row = QtWidgets.QHBoxLayout()
        vmode_row.addWidget(QtWidgets.QLabel('Type'))
        self._adv_vec_mode_combo = QtWidgets.QComboBox()
        self._adv_vec_mode_combo.addItems(['vector', 'projection', 'distance', 'normal'])
        vmode_row.addWidget(self._adv_vec_mode_combo)
        vmode_row.addStretch()
        vec_lay.addLayout(vmode_row)

        # Axis radio buttons (hidden in normal mode)
        self._adv_axis_widget = QtWidgets.QWidget()
        axis_lay = QtWidgets.QVBoxLayout(self._adv_axis_widget)
        axis_lay.setContentsMargins(0, 0, 0, 0)
        axis_lay.setSpacing(2)

        axis_row = QtWidgets.QHBoxLayout()
        axis_row.addWidget(QtWidgets.QLabel('Direction'))
        self._adv_axis_group = QtWidgets.QButtonGroup(self)
        for axis in ('x+', 'x-', 'y+', 'y-', 'z+', 'z-'):
            btn = QtWidgets.QRadioButton(axis)
            btn.setProperty('axis', axis)
            if axis == 'y+':
                btn.setChecked(True)
            self._adv_axis_group.addButton(btn)
            axis_row.addWidget(btn)
        axis_lay.addLayout(axis_row)

        custom_row = QtWidgets.QHBoxLayout()
        self._adv_custom_check = QtWidgets.QCheckBox('Custom')
        self._adv_custom_vec = QtWidgets.QLineEdit('0,1,0')
        self._adv_custom_vec.setPlaceholderText('x, y, z')
        self._adv_custom_vec.setEnabled(False)
        self._adv_custom_check.toggled.connect(self._adv_custom_vec.setEnabled)
        self._adv_custom_check.toggled.connect(
            partial(self._toggle_axis_buttons, enable=False)
        )
        custom_row.addWidget(self._adv_custom_check)
        custom_row.addWidget(self._adv_custom_vec, stretch=1)
        axis_lay.addLayout(custom_row)
        vec_lay.addWidget(self._adv_axis_widget)

        # Hide axis controls in 'normal' mode
        self._adv_vec_mode_combo.currentTextChanged.connect(
            lambda m: self._adv_axis_widget.setVisible(m != 'normal')
        )
        lay.addWidget(self._adv_vector_widget)

        # ---- Radial sub-widget ----------------------------------------
        self._adv_radial_widget = QtWidgets.QWidget()
        rad_lay = QtWidgets.QVBoxLayout(self._adv_radial_widget)
        rad_lay.setContentsMargins(0, 0, 0, 0)
        rad_lay.setSpacing(4)
        self._adv_radial_widget.setVisible(False)

        # Center picker row
        center_row = QtWidgets.QHBoxLayout()
        center_row.addWidget(QtWidgets.QLabel('Center'))
        self._adv_center_x = QtWidgets.QDoubleSpinBox()
        self._adv_center_y = QtWidgets.QDoubleSpinBox()
        self._adv_center_z = QtWidgets.QDoubleSpinBox()
        for sp in (self._adv_center_x, self._adv_center_y, self._adv_center_z):
            sp.setRange(-99999.0, 99999.0)
            sp.setDecimals(3)
            sp.setFixedWidth(68)
            center_row.addWidget(sp)
        pick_btn = QtWidgets.QPushButton('◎')
        pick_btn.setFixedWidth(24)
        pick_btn.setToolTip('Set center from current selection bounding box')
        pick_btn.clicked.connect(self._on_pick_radial_center)
        center_row.addWidget(pick_btn)
        rad_lay.addLayout(center_row)

        # Radius row
        radius_row = QtWidgets.QHBoxLayout()
        radius_row.addWidget(QtWidgets.QLabel('Radius'))
        self._adv_radius_spin = QtWidgets.QDoubleSpinBox()
        self._adv_radius_spin.setRange(0.0, 99999.0)
        self._adv_radius_spin.setDecimals(3)
        self._adv_radius_spin.setValue(0.0)
        self._adv_radius_spin.setSpecialValueText('auto')
        self._adv_radius_spin.setToolTip('0 = auto from soft-selection or bounding box')
        radius_row.addWidget(self._adv_radius_spin)
        ss_btn = QtWidgets.QPushButton('Soft sel')
        ss_btn.setFixedWidth(56)
        ss_btn.setToolTip('Read radius from current soft-selection distance')
        ss_btn.clicked.connect(self._on_read_soft_select_radius)
        radius_row.addWidget(ss_btn)
        radius_row.addStretch()
        rad_lay.addLayout(radius_row)

        lay.addWidget(self._adv_radial_widget)

        # ---- Mask (shared by vector & radial) --------------------------
        mask_row = QtWidgets.QHBoxLayout()
        self._adv_mask_label = QtWidgets.QLabel('Mask: whole mesh')
        mask_row.addWidget(self._adv_mask_label, stretch=1)
        mask_pick_btn = QtWidgets.QPushButton('Pick')
        mask_pick_btn.setFixedWidth(40)
        mask_pick_btn.setToolTip(
            'Restrict Apply to the currently selected vertices, until '
            'cleared. Independent of the radial center pick.'
        )
        mask_pick_btn.clicked.connect(self._on_pick_advanced_mask)
        mask_row.addWidget(mask_pick_btn)
        mask_clear_btn = QtWidgets.QPushButton('Clear')
        mask_clear_btn.setFixedWidth(40)
        mask_clear_btn.setToolTip('Clear the mask — Apply affects the whole mesh.')
        mask_clear_btn.clicked.connect(self._on_clear_advanced_mask)
        mask_row.addWidget(mask_clear_btn)
        lay.addLayout(mask_row)

        # ---- Shared controls ------------------------------------------
        # Operation selector (replace / add / subtract / multiply)
        op_row = QtWidgets.QHBoxLayout()
        op_row.addWidget(QtWidgets.QLabel('Op'))
        self._adv_op_combo = QtWidgets.QComboBox()
        self._adv_op_combo.addItems(['replace', 'add', 'subtract', 'multiply'])
        op_row.addWidget(self._adv_op_combo)
        op_row.addStretch()
        lay.addLayout(op_row)


        # ---- Shared controls ------------------------------------------
        self._adv_invert_check = QtWidgets.QCheckBox('Invert')
        lay.addWidget(self._adv_invert_check)

        self._adv_apply_btn = QtWidgets.QPushButton('Apply')
        self._adv_apply_btn.setStyleSheet(
            'QPushButton { background-color: #505060; color: white; }'
            'QPushButton:hover { background-color: #606070; }'
        )
        self._adv_apply_btn.clicked.connect(self._on_advanced_apply)
        lay.addWidget(self._adv_apply_btn)

        # Show/hide sub-widgets based on mode
        self._adv_mode_combo.currentTextChanged.connect(self._on_adv_mode_changed)

        return section

    def _build_transfer_section(self) -> 'CollapsibleSection':
        """Build the collapsible 'Transfer weights' section.

        The user stores a source mesh's weights in the embedded slot button,
        then switches to a different mesh/deformer as the active target and
        clicks Transfer.  Cross-topology nearest-neighbour interpolation is
        used so source and target may have completely different vertex counts.

        Returns:
            A CollapsibleSection ready to be added to the left column.
        """
        section = CollapsibleSection('Transfer weights')
        lay = section.content_layout

        # -- Source slot (embedded VtxStorageButton) -----------------------
        src_row = QtWidgets.QHBoxLayout()
        src_label = QtWidgets.QLabel('Source')
        src_label.setFixedWidth(48)
        src_row.addWidget(src_label)

        self._transfer_src_btn = dw_maya.dw_pyqt_utils.dw_btn_storage.VtxStorageButton()
        self._transfer_src_btn.setFixedSize(44, 44)
        self._transfer_src_btn.setText('Src')
        self._transfer_src_btn.setToolTip(
            'Right-click -> Store  to capture the source mesh weights.\n'
            'Then switch to the target deformer and click Transfer.'
        )
        src_row.addWidget(self._transfer_src_btn)

        set_src_btn = QtWidgets.QPushButton('<- Active')
        set_src_btn.setFixedWidth(60)
        set_src_btn.setToolTip('Set this slot\'s source from the currently active deformer')
        set_src_btn.clicked.connect(self._on_transfer_set_source)
        src_row.addWidget(set_src_btn)
        src_row.addStretch()
        lay.addLayout(src_row)

        # -- Target label (reflects active source) -------------------------
        tgt_row = QtWidgets.QHBoxLayout()
        tgt_lbl = QtWidgets.QLabel('Target')
        tgt_lbl.setFixedWidth(48)
        tgt_row.addWidget(tgt_lbl)
        self._transfer_tgt_label = QtWidgets.QLabel('— (active source) —')
        self._transfer_tgt_label.setStyleSheet('color: #aaaaaa; font-size: 11px;')
        tgt_row.addWidget(self._transfer_tgt_label, stretch=1)
        lay.addLayout(tgt_row)

        # -- Transfer options: max distance + preserve unmapped ------------
        opts_row = QtWidgets.QHBoxLayout()
        self._transfer_limit_check = QtWidgets.QCheckBox('Limit distance')
        self._transfer_max_distance_spin = QtWidgets.QDoubleSpinBox()
        self._transfer_max_distance_spin.setRange(0.0, 99999.0)
        self._transfer_max_distance_spin.setDecimals(3)
        self._transfer_max_distance_spin.setValue(0.0)
        self._transfer_max_distance_spin.setEnabled(False)
        self._transfer_limit_check.toggled.connect(self._transfer_max_distance_spin.setEnabled)
        opts_row.addWidget(self._transfer_limit_check)
        opts_row.addWidget(self._transfer_max_distance_spin)
        self._transfer_preserve_check = QtWidgets.QCheckBox('Preserve unmapped')
        self._transfer_preserve_check.setChecked(True)
        opts_row.addWidget(self._transfer_preserve_check)
        opts_row.addStretch()
        lay.addLayout(opts_row)

        # -- Transfer button -----------------------------------------------
        transfer_btn = QtWidgets.QPushButton('Transfer ▶')
        transfer_btn.setFixedHeight(28)
        transfer_btn.setStyleSheet(
            'QPushButton { background-color: #405060; color: white; }'
            'QPushButton:hover { background-color: #506070; }'
        )
        transfer_btn.clicked.connect(self._on_transfer_apply)
        lay.addWidget(transfer_btn)

        return section

    def _build_remap_section(self) -> CollapsibleSection:
        """Build the collapsible 'Remap / Fit' section.

        Remaps current weights from [old_min, old_max] to [new_min, new_max].

        Returns:
            A CollapsibleSection ready to be added to the left column.
        """
        section = CollapsibleSection('Remap / Fit')
        lay = section.content_layout

        # Old range row
        old_row = QtWidgets.QHBoxLayout()
        old_row.addWidget(QtWidgets.QLabel('Old'))
        self._remap_old_min = QtWidgets.QDoubleSpinBox()
        self._remap_old_max = QtWidgets.QDoubleSpinBox()
        for sp in (self._remap_old_min, self._remap_old_max):
            sp.setRange(-99.0, 99.0)
            sp.setDecimals(3)
            sp.setFixedWidth(68)
        self._remap_old_min.setValue(0.0)
        self._remap_old_max.setValue(1.0)
        old_row.addWidget(QtWidgets.QLabel('min'))
        old_row.addWidget(self._remap_old_min)
        old_row.addWidget(QtWidgets.QLabel('max'))
        old_row.addWidget(self._remap_old_max)

        self._remap_fit_btn = QtWidgets.QPushButton('-> Fit')
        self._remap_fit_btn.setFixedWidth(40)
        self._remap_fit_btn.setFixedHeight(20)
        self._remap_fit_btn.setToolTip('Auto-fill Old min/max from current weight range')
        self._remap_fit_btn.clicked.connect(self._on_remap_fit)
        old_row.addWidget(self._remap_fit_btn)

        lay.addLayout(old_row)

        # New range row
        new_row = QtWidgets.QHBoxLayout()
        new_row.addWidget(QtWidgets.QLabel('New'))
        self._remap_new_min = QtWidgets.QDoubleSpinBox()
        self._remap_new_max = QtWidgets.QDoubleSpinBox()
        for sp in (self._remap_new_min, self._remap_new_max):
            sp.setRange(-99.0, 99.0)
            sp.setDecimals(3)
            sp.setFixedWidth(68)
        self._remap_new_min.setValue(0.0)
        self._remap_new_max.setValue(1.0)
        new_row.addWidget(QtWidgets.QLabel('min'))
        new_row.addWidget(self._remap_new_min)
        new_row.addWidget(QtWidgets.QLabel('max'))
        new_row.addWidget(self._remap_new_max)

        self._remap_invert_btn = QtWidgets.QPushButton('-> Inv')
        self._remap_invert_btn.setFixedWidth(40)
        self._remap_invert_btn.setFixedHeight(20)
        self._remap_invert_btn.setToolTip('Set Value to the Invert of the Old values')
        self._remap_invert_btn.clicked.connect(self._on_remap_invert)
        new_row.addWidget(self._remap_invert_btn)

        lay.addLayout(new_row)

        remap_btn = QtWidgets.QPushButton('Apply Remap')
        remap_btn.setFixedHeight(26)
        remap_btn.setStyleSheet(
            'QPushButton { background-color: #504040; color: white; }'
            'QPushButton:hover { background-color: #705050; }'
        )
        remap_btn.clicked.connect(self._on_remap_apply)
        lay.addWidget(remap_btn)

        return section

    def _build_storage_panel(self) -> QtWidgets.QWidget:
        """Compact square-button storage column (no title, top-right position)."""
        panel = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setSpacing(4)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setAlignment(QtCore.Qt.AlignTop)

        # Dynamic area — storage buttons are inserted here
        self._storage_layout = QtWidgets.QVBoxLayout()
        self._storage_layout.setSpacing(4)
        self._storage_layout.setContentsMargins(0, 0, 0, 0)
        self._storage_layout.setAlignment(QtCore.Qt.AlignTop)
        layout.addLayout(self._storage_layout)
        self._storage_buttons = []

        # [+] square button — always stays at the top
        self._add_storage_btn = QtWidgets.QPushButton('+')
        self._add_storage_btn.setFixedSize(20, 20)
        self._add_storage_btn.setToolTip(
            'Add a storage slot\n'
            'Left-click a slot to restore  |  Right-click for options'
        )
        self._add_storage_btn.clicked.connect(self._on_add_storage)
        layout.insertWidget(0, self._add_storage_btn)

        layout.addStretch()
        return panel

    def _build_deformer_group(self) -> QtWidgets.QGroupBox:
        grp = QtWidgets.QGroupBox('')
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        # --- Mode radio buttons — built from the panel registry ---
        from dw_maya.dw_pyqt_utils.flow_layout import FlowLayout
        mode_to_sel = self._get_preferred_mode()
        mode_wgt = QtWidgets.QWidget()
        mode_lay = FlowLayout(mode_wgt, margin=0, spacing=4)
        self._mode_group = QtWidgets.QButtonGroup(self)
        self._mode_btns = {}  # mode_key -> QRadioButton (used by Pref menu)
        registry = wgt_deformer_panel.get_mode_registry()
        for mode_key, entry in registry.items():
            btn = QtWidgets.QRadioButton(entry['label'])
            btn.setProperty('mode', mode_key)
            if mode_key == mode_to_sel:
                btn.setChecked(True)
            self._mode_group.addButton(btn)
            mode_lay.addWidget(btn)
            self._mode_btns[mode_key] = btn
        lay.addWidget(mode_wgt)

        # --- Mesh label + refresh button ---
        mesh_row = QtWidgets.QHBoxLayout()
        self._mesh_label = QtWidgets.QLabel('Nothing selected')
        self._mesh_label.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft)
        font = self._mesh_label.font()
        font.setBold(True)
        self._mesh_label.setFont(font)
        mesh_row.addWidget(self._mesh_label, stretch=1)

        refresh_btn = QtWidgets.QPushButton('mesh picker ↺')
        refresh_btn.setFixedSize(24, 24)
        refresh_btn.setToolTip('Update list from selection')
        refresh_btn.clicked.connect(self._on_refresh)
        mesh_row.addWidget(refresh_btn)
        lay.addLayout(mesh_row)

        # --- Flat source combo: one row per (source × map) pair ---
        self._source_combo = QtWidgets.QComboBox()
        self._source_combo.setMinimumWidth(220)
        self._source_combo.setToolTip('Select deformer / map to paint')
        lay.addWidget(self._source_combo)

        # --- Registry-driven sub-panel area ---
        self._panel_container = QtWidgets.QStackedWidget()
        lay.addWidget(self._panel_container)
        self._panel_cache: dict = {}         # Type[DeformerPanelBase] -> instance
        self._current_panel: Optional[wgt_deformer_panel.DeformerPanelBase] = None

        # --- Copy / Paste ---
        cp_row = QtWidgets.QHBoxLayout()
        self._copy_btn = QtWidgets.QPushButton('Copy weights')
        self._paste_btn = QtWidgets.QPushButton('Paste weights')
        cp_row.addWidget(self._copy_btn)
        cp_row.addWidget(self._paste_btn)
        lay.addLayout(cp_row)

        # --- Envelope spinbox — wrapped in a widget for easy show/hide ---
        self._envelope_row_widget = QtWidgets.QWidget()
        env_row = QtWidgets.QHBoxLayout(self._envelope_row_widget)
        env_row.setContentsMargins(0, 0, 0, 0)
        env_row.addWidget(QtWidgets.QLabel('envelope'))
        self._envelope_slider = QtWidgets.QDoubleSpinBox()
        self._envelope_slider.setRange(0.0, 1.0)
        self._envelope_slider.setDecimals(2)
        self._envelope_slider.setSingleStep(0.01)
        self._envelope_slider.setFixedWidth(70)
        env_row.addWidget(self._envelope_slider)
        env_row.addStretch()
        lay.addWidget(self._envelope_row_widget)

        # --- Paint button ---
        self._paint_btn = QtWidgets.QPushButton('▶  Paint')
        self._paint_btn.setFixedHeight(32)
        self._paint_btn.setStyleSheet(
            'QPushButton { background-color: #a8a820; color: #1a1a00; font-weight: bold; }'
            'QPushButton:hover { background-color: #c8c830; }'
        )
        lay.addWidget(self._paint_btn)

        # --- Display range warning (shown only when weights outside 0-1) ---
        self._display_range_widget = QtWidgets.QWidget()
        dr_lay = QtWidgets.QVBoxLayout(self._display_range_widget)
        dr_lay.setContentsMargins(0, 2, 0, 0)
        dr_lay.setSpacing(2)

        dr_header = QtWidgets.QHBoxLayout()
        dr_label = QtWidgets.QLabel('⚠  Display range')
        dr_label.setStyleSheet('color: #e8a020; font-size: 11px;')
        dr_label.setToolTip(
            'Weights outside [0, 1] detected.\n'
            'The artisan color range will be set automatically on Paint.\n'
            'Adjust manually here if needed.'
        )
        dr_header.addWidget(dr_label)
        dr_header.addStretch()
        self._display_range_fit_btn = QtWidgets.QPushButton('Fit')
        self._display_range_fit_btn.setFixedSize(34, 18)
        self._display_range_fit_btn.setStyleSheet(
            'QPushButton { background-color: #3a3a2a; color: #cccc88; font-size: 10px; }'
            'QPushButton:hover { background-color: #4a4a32; }'
        )
        self._display_range_fit_btn.setToolTip('Fit range to actual weight min/max')
        dr_header.addWidget(self._display_range_fit_btn)
        dr_lay.addLayout(dr_header)

        self._display_range_slider = RangeSliderWithSpinbox(limit_min=0.0, limit_max=1.0, decimals=1)
        self._display_range_slider.setToolTip('Artisan colorrangelower / colorrangeupper — pushed on Paint')
        dr_lay.addWidget(self._display_range_slider)
        self._display_range_widget.hide()
        lay.addWidget(self._display_range_widget)

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
        self.set_invert_btn = QtWidgets.QPushButton('Invert')
        self.set_invert_btn.setFixedWidth(50)
        set_row.addWidget(self._set0_btn)
        set_row.addWidget(self._set1_btn)
        set_row.addWidget(self.set_invert_btn)
        lay.addLayout(set_row)

        # --- Operation mode radio buttons ---
        op_row = QtWidgets.QHBoxLayout()
        self._op_group = QtWidgets.QButtonGroup(self)
        for label, op in [('Replace', 'replace'), ('Add', 'add'), ('Multiply', 'multiply')]:
            btn = QtWidgets.QRadioButton(label)
            btn.setProperty('op', op)
            if op == 'replace':
                btn.setChecked(True)
            self._op_group.addButton(btn)
            op_row.addWidget(btn)
        op_row.addStretch()
        lay.addLayout(op_row)

        sub_row = QtWidgets.QHBoxLayout()
        self._weight_slider = SliderWithButton(label='weight',
                                               btn_label='Set',
                                               default=0.5,
                                               decimals=2,
                                               step=0.01,
                                               label_width=48)
        self._pb_picker = QtWidgets.QPushButton()
        self._pb_picker.setFixedSize(25, 25)
        _icon = QtGui.QIcon(str(ICON_PIPETTE))
        self._pb_picker.setIcon(_icon)
        self._pb_picker.setIconSize(QtCore.QSize(25, 25))
        self._pb_picker.setFlat(True)

        sub_row.addWidget(self._weight_slider)
        sub_row.addWidget(self._pb_picker)
        lay.addLayout(sub_row)

        # --- Clamp Widget ---
        clamp_row = QtWidgets.QHBoxLayout()
        clamp_row.setContentsMargins(0, 0, 0, 0)
        clamp_row.setSpacing(4)
        clamp_lbl = QtWidgets.QLabel('Clamp')
        clamp_lbl.setFixedWidth(40)

        self._clamp_min_check = QtWidgets.QCheckBox()
        self._clamp_min_check.setToolTip('Enable Min Clamp')

        self._clamp_slider = RangeSliderWithSpinbox(limit_min=0.0, limit_max=1.0, decimals=3)
        self._clamp_slider.setToolTip('Clamp Range')

        self._clamp_max_check = QtWidgets.QCheckBox()
        self._clamp_max_check.setToolTip('Enable Max Clamp')

        clamp_row.addWidget(clamp_lbl)
        clamp_row.addWidget(self._clamp_min_check)
        clamp_row.addWidget(self._clamp_slider, stretch=1)
        clamp_row.addWidget(self._clamp_max_check)
        lay.addLayout(clamp_row)

        return grp

    def _build_smooth_group(self) -> QtWidgets.QGroupBox:
        grp = QtWidgets.QGroupBox('Smooth  (paint tool must be active)')
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        # Warning label shown only for VertexColorAlpha (slow path)
        self._smooth_warn_label = QtWidgets.QLabel(
            '⚠'
        )
        self._smooth_warn_label.setToolTip("vertex alpha smooth is slow (~8 s per call)")
        self._smooth_warn_label.setStyleSheet('color: #e8a838; font-size: 11px;')
        self._smooth_warn_label.setWordWrap(True)
        self._smooth_warn_label.hide()
        lay.addWidget(self._smooth_warn_label)

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

        flood_btn = QtWidgets.QPushButton('Apply')
        flood_btn.setToolTip('Apply smooth N times to all vertices')
        flood_btn.clicked.connect(self._on_smooth_flood)
        iter_row.addWidget(flood_btn)
        lay.addLayout(iter_row)

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel('via'))
        self._smooth_mode = QtWidgets.QComboBox()
        self._smooth_mode.addItems(['artisan (viewport)', 'numpy (selection-aware)'])
        self._smooth_mode.setToolTip(
            'artisan: flood all vertices via Maya brush (viewport feedback, no selection)\n'
            'numpy: topology smooth, respects vertex selection, applies clamp'
        )
        mode_row.addWidget(self._smooth_mode)
        mode_row.addStretch()
        lay.addLayout(mode_row)

        # Indeterminate busy bar — shown while smooth is computing
        self._smooth_busy_bar = QtWidgets.QProgressBar()
        self._smooth_busy_bar.setRange(0, 0)   # indeterminate
        self._smooth_busy_bar.setFixedHeight(6)
        self._smooth_busy_bar.setTextVisible(False)
        self._smooth_busy_bar.hide()
        lay.addWidget(self._smooth_busy_bar)

        return grp

    def _build_select_group(self) -> QtWidgets.QGroupBox:
        grp = QtWidgets.QGroupBox('Select vertices')
        lay = QtWidgets.QVBoxLayout(grp)
        lay.setSpacing(4)

        # ── Row 1 : All / Invert / Border ────────────────────────────────
        all_row = QtWidgets.QHBoxLayout()
        self._sel_all_btn = QtWidgets.QPushButton('All')
        self._sel_all_btn.setToolTip('Select all vertices of the active mesh')
        self._invert_btn = QtWidgets.QPushButton('Invert')
        self._invert_btn.setToolTip('Invert current vertex selection (always active)')
        self._border_btn = QtWidgets.QPushButton('Border')
        self._border_btn.setToolTip('Select border vertices')
        all_row.addWidget(self._sel_all_btn)
        all_row.addWidget(self._invert_btn)
        all_row.addWidget(self._border_btn)
        lay.addLayout(all_row)

        # ── Mode toggle ───────────────────────────────────────────────────
        mode_row = QtWidgets.QHBoxLayout()
        self._sel_mode_check = QtWidgets.QCheckBox('Value mode')
        self._sel_mode_check.setToolTip(
            'Unchecked = Range [lo, hi]\n'
            'Checked   = single Value ± tolerance'
        )
        mode_row.addWidget(self._sel_mode_check)
        mode_row.addStretch()
        lay.addLayout(mode_row)

        # ── Row 2a : Range mode — RangeSlider + Fit ──────────────────────
        #   [spin_min][══slider══][spin_max]  [⇥]
        self._range_slider_row_widget = QtWidgets.QWidget()
        slider_row = QtWidgets.QHBoxLayout(self._range_slider_row_widget)
        slider_row.setContentsMargins(0, 0, 0, 0)
        slider_row.setSpacing(3)

        self._range_sel = RangeSliderWithSpinbox(limit_min=0.0, limit_max=1.0, decimals=2)
        slider_row.addWidget(self._range_sel, stretch=1)

        self._range_fit_btn = QtWidgets.QPushButton('⇥')
        self._range_fit_btn.setFixedWidth(22)
        self._range_fit_btn.setFixedHeight(22)
        self._range_fit_btn.setToolTip('Fit limits to current min/max weights')
        slider_row.addWidget(self._range_fit_btn)
        lay.addWidget(self._range_slider_row_widget)

        # ── Row 2b : Range mode actions — Select / min / max ─────────────
        self._range_action_row_widget = QtWidgets.QWidget()
        range_action_row = QtWidgets.QHBoxLayout(self._range_action_row_widget)
        range_action_row.setContentsMargins(0, 0, 0, 0)
        range_action_row.setSpacing(3)

        self._sel_range_btn = QtWidgets.QPushButton('Select')
        self._sel_range_btn.setToolTip(
            'Select vertices in range (Shift=add, Ctrl=deselect, Ctrl+Shift=toggle)'
        )
        range_action_row.addWidget(self._sel_range_btn)

        self._sel_snap_min_btn = QtWidgets.QPushButton('min')
        self._sel_snap_min_btn.setFixedWidth(34)
        self._sel_snap_min_btn.setToolTip('Snap both handles to the lower limit')
        self._sel_snap_min_btn.setStyleSheet(
            'background-color: #282828; color: #aaaaaa; font-size: 10px;'
        )
        range_action_row.addWidget(self._sel_snap_min_btn)

        self._sel_snap_max_btn = QtWidgets.QPushButton('max')
        self._sel_snap_max_btn.setFixedWidth(34)
        self._sel_snap_max_btn.setToolTip('Snap both handles to the upper limit')
        self._sel_snap_max_btn.setStyleSheet(
            'background-color: #bbbbbb; color: #111111; font-size: 10px;'
        )
        range_action_row.addWidget(self._sel_snap_max_btn)
        lay.addWidget(self._range_action_row_widget)

        # ── Row 2c : Value mode — Select / value spinbox / ± tol ─────────
        #   [Select]  [0.50 ↕]  ±  [0.00 ↕]
        self._value_row_widget = QtWidgets.QWidget()
        value_row = QtWidgets.QHBoxLayout(self._value_row_widget)
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(3)

        self._sel_value_btn = QtWidgets.QPushButton('Select')
        self._sel_value_btn.setToolTip(
            'Select vertices equal to value ± tolerance\n'
            '(Shift=add, Ctrl=deselect, Ctrl+Shift=toggle)'
        )
        value_row.addWidget(self._sel_value_btn)

        self._sel_value_spin = QtWidgets.QDoubleSpinBox()
        self._sel_value_spin.setRange(-9999.0, 9999.0)
        self._sel_value_spin.setDecimals(2)
        self._sel_value_spin.setSingleStep(0.01)
        self._sel_value_spin.setValue(0.5)
        self._sel_value_spin.setFixedWidth(62)
        self._sel_value_spin.setToolTip('Target value')
        value_row.addWidget(self._sel_value_spin)

        # Tolerance slider + Select button in one composite widget
        self._sel_tol_slider = SliderWithButton(
            label='±',
            min_val=0.0,
            max_val=1.0,
            default=0.0,
            decimals=2,
            step=0.01,
            has_button=False)

        self._sel_tol_slider.setToolTip(
            'Tolerance (0 = exact match)\n'
            'Select vertices equal to value ± tolerance\n'
            '(Shift=add, Ctrl=deselect, Ctrl+Shift=toggle)'
        )
        value_row.addWidget(self._sel_tol_slider, stretch=1)

        lay.addWidget(self._value_row_widget)
        self._value_row_widget.hide()   # Range mode by default

        return grp

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        # Controller -> UI
        self._signals.sources_changed.connect(self._on_sources_changed)
        self._signals.mesh_changed.connect(self._mesh_label.setText)
        self._signals.active_changed.connect(self._on_active_changed)

        # Mode toggle
        self._mode_group.buttonClicked.connect(self._on_mode_changed)

        # Flat source combo
        self._source_combo.currentIndexChanged.connect(self._on_source_combo_changed)

        # Deformer group
        self._copy_btn.clicked.connect(self._ctrl.copy_weights)
        self._paste_btn.clicked.connect(self._ctrl.paste_weights)
        self._paint_btn.clicked.connect(self._on_paint_clicked)
        self._envelope_slider.valueChanged.connect(self._on_envelope_changed)

        # Display range slider — live-push to artisan color range
        self._display_range_slider.range_changed.connect(
            lambda lo, hi: self._ctrl.set_artisan_color_range(lo, hi)
        )
        self._display_range_fit_btn.clicked.connect(self._refresh_display_range)

        # Weights group — Set 0/1 share the same op mode as the slider
        self._set0_btn.clicked.connect(partial(self._on_set_weight, 0.0))
        self._set1_btn.clicked.connect(partial(self._on_set_weight, 1.0))
        self.set_invert_btn.clicked.connect(self._on_weight_invert)
        self._op_group.buttonClicked.connect(self._on_op_mode_changed)

        self._weight_slider.button_clicked.connect(self._on_set_weight)
        self._weight_slider.sliderReleased.connect(
            lambda: self._ctrl.set_artisan_value(self._weight_slider.value)
        )
        self._weight_slider.value_changed.connect(self._on_weight_slider_changed)
        self._pb_picker.clicked.connect(self._on_pb_picker_clicked)


        # Clamp section
        self._clamp_slider.range_changed.connect(self._set_artisan_clamp)
        self._clamp_min_check.stateChanged.connect(self._set_artisan_clamp)
        self._clamp_max_check.stateChanged.connect(self._set_artisan_clamp)

        # Select group
        self._sel_all_btn.clicked.connect(self._on_select_all)
        self._invert_btn.clicked.connect(self._on_invert_selection)
        self._border_btn.clicked.connect(self._on_border_sel)
        self._sel_range_btn.clicked.connect(self._on_select_by_range)
        self._sel_value_btn.clicked.connect(self._on_select_by_value)
        self._sel_snap_min_btn.clicked.connect(partial(self._on_select_by_limit, False))
        self._sel_snap_max_btn.clicked.connect(partial(self._on_select_by_limit, True))
        self._range_fit_btn.clicked.connect(self._on_range_fit)
        self._sel_mode_check.toggled.connect(self._on_sel_mode_toggled)

        ## select dynamically with slider
        self._range_sel.slider_moved.connect(self._on_selection_range_moved)
        self._range_sel.slider_pressed.connect(self._on_range_selection_pressed)
        self._range_sel.slider_released.connect(self._on_range_selection_released)

    # ------------------------------------------------------------------
    # QMENU - auto functions
    # ------------------------------------------------------------------
    @Slot(bool)
    def _on_auto_paint_toggled(self, checked: bool) -> None:
        """Persist auto-paint preference."""
        settings = QtCore.QSettings(self._org, self._appname)
        settings.setValue('auto_paint', checked)

    @Slot(bool)
    def _on_auto_range_select_toggled(self, checked: bool) -> None:
        """Persist auto-paint preference."""
        settings = QtCore.QSettings(self._org, self._appname)
        settings.setValue('auto_range_select', checked)

    @Slot(bool)
    def _on_use_ramp_color_toggled(self, checked: bool) -> None:
        """Persist and apply color-ramp preference to Maya's paint UI."""
        settings = QtCore.QSettings(self._org, self._appname)
        settings.setValue('use_color_ramp', checked)

    def _get_preferred_mode(self)->str:
        settings = QtCore.QSettings(self._org, self._appname)
        mode_name = settings.value('mode_selected', "all", type=str)
        return str(mode_name)

    def _save_preferred_mode(self):
        settings = QtCore.QSettings(self._org, self._appname)
        for mode, btn in self._mode_btns.items():
            if btn.isChecked():
                settings.setValue('mode_selected', mode)
                break

    # ------------------------------------------------------------------
    # QProperty — smooth iterations
    # ------------------------------------------------------------------

    def get_smooth_iterations(self) -> int:
        """Return the current smooth iteration count."""
        return self._iter_spinbox.value()

    def set_smooth_iterations(self, value: int) -> None:
        """Set the smooth iteration count (clamped to 1–200).

        Args:
            value: Number of smooth iterations.

        Example::

            widget.smooth_iterations = 10
        """
        self._iter_spinbox.setValue(max(1, min(200, value)))

    smooth_iterations = QtCore.Property(
        int,
        get_smooth_iterations,
        set_smooth_iterations,
        notify=smooth_iterations_changed,
    )

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_transfer_set_source(self) -> None:
        """Pre-fill the transfer source slot from the currently active deformer."""
        source = self._ctrl.active_source
        active_map = self._ctrl.active_map
        if source and active_map:
            self._transfer_src_btn.current_weight_node = f'{source.node_name}.{active_map}'
            self._transfer_src_btn.weight_source = source
            self._transfer_src_btn.store_current_data()
            logger.debug(f"Transfer source set to {source.node_name}.{active_map}")
        else:
            logger.warning("No active source to set as transfer source.")

    @Slot()
    def _on_transfer_apply(self) -> None:
        """Execute the cross-topology weight transfer."""
        src_weights = self._transfer_src_btn.stored_weights
        if isinstance(src_weights, (list, tuple)):
            if isinstance(src_weights[0],  (list, tuple)):
                src_weights = src_weights[0]


        if not src_weights:
            QtWidgets.QMessageBox.warning(
                self, 'Transfer',
                'Source slot is empty.\n'
                'Right-click the Src button and choose "Store weights", '
                'then come back and click Transfer.'
            )
            return

        src_mesh_name = None
        try:
            src_ws = self._transfer_src_btn.weight_source
            src_mesh_name = src_ws.mesh_name
            src_mesh_exists = True
        except:
            src_mesh_name = self._ctrl.active_source.mesh_name
            src_mesh_exists = False
        if src_mesh_name is None:
            QtWidgets.QMessageBox.warning(
                self, 'Transfer',
                'Source slot has no associated deformer.\n'
                'Use "← Active" to capture the source first.'
            )
            return

        src_vtx_transform = self._transfer_src_btn.storage.get("vtx_transform")
        src_mesh_exists = cmds.objExists(src_mesh_name) if src_mesh_name else False

        # Check if the live mesh topology still matches what was stored at capture time.
        live_vtx_count = 0
        if src_mesh_exists:
            try:
                live_vtx_count = cmds.polyEvaluate(src_mesh_name, vertex=True)
            except Exception:
                live_vtx_count = 0
        mesh_topology_changed = src_mesh_exists and (live_vtx_count != len(src_weights))

        stored_positions_valid = bool(src_vtx_transform) and len(src_vtx_transform) == len(src_weights)

        if src_mesh_exists and not mesh_topology_changed:
            # Mesh is intact — live positions are the most accurate, use them directly.
            logger.debug(
                f"transfer: '{src_mesh_name}' exists with matching vtx count ({live_vtx_count}), "
                f"using live positions"
            )
            src_vtx_transform = None
        elif stored_positions_valid:
            # Mesh deleted OR topology changed — rely on positions captured at store time.
            reason = "deleted" if not src_mesh_exists else f"topology changed ({live_vtx_count} vs {len(src_weights)} vtx)"
            logger.warning(
                f"transfer: source mesh '{src_mesh_name}' {reason} — "
                f"using {len(src_vtx_transform)} stored vertex positions for KDTree"
            )
            # src_vtx_transform already holds the correct data, nothing to do
        else:
            # No valid fallback — log and let the controller attempt with live mesh.
            missing_reason = "not found in scene" if not src_mesh_exists else f"topology changed ({live_vtx_count} vs {len(src_weights)} vtx)"
            logger.error(
                f"transfer: source mesh '{src_mesh_name}' {missing_reason} and stored positions "
                f"are missing or mismatched (stored={len(src_vtx_transform) if src_vtx_transform else 0}, "
                f"weights={len(src_weights)}) — transfer may be incorrect"
            )
            src_vtx_transform = None

        tgt_ws = self._ctrl.active_source
        if tgt_ws is None:
            QtWidgets.QMessageBox.warning(
                self, 'Transfer',
                'No active target deformer.\n'
                'Select the target mesh, refresh, and pick a deformer.'
            )
            return
        max_dist = None
        if getattr(self, '_transfer_limit_check', None) and self._transfer_limit_check.isChecked():
            max_dist = float(self._transfer_max_distance_spin.value())
        preserve = True
        if getattr(self, '_transfer_preserve_check', None):
            preserve = bool(self._transfer_preserve_check.isChecked())

        self._ctrl.transfer_weights(src_weights,
                                    src_mesh_name,
                                    tgt_ws,
                                    max_distance=max_dist,
                                    preserve_unmapped=preserve,
                                    src_vtx_transform=src_vtx_transform)

    @Slot()
    def _on_border_sel(self):
        mods = QtWidgets.QApplication.keyboardModifiers()
        if mods & QtCore.Qt.ShiftModifier:
            self._ctrl.border_selection(key_mod=1)
        else:
            self._ctrl.border_selection(key_mod=0)

    @Slot()
    def _on_remap_apply(self) -> None:
        """Apply remap/fit weight operation using the spinbox ranges."""
        self._ctrl.remap_weights(
            old_min=self._remap_old_min.value(),
            old_max=self._remap_old_max.value(),
            new_min=self._remap_new_min.value(),
            new_max=self._remap_new_max.value(),
        )

    @Slot()
    def _on_weight_invert(self) -> None:
        if self._ctrl.active_source:
            weight_range = self._ctrl.get_weight_range()
            self._ctrl.remap_weights(old_min=weight_range[0],
                                     old_max=weight_range[1],
                                     new_min=weight_range[1],
                                     new_max=weight_range[0])
    @Slot()
    def _on_remap_fit(self) -> None:
        """Fill Old min/max from the actual weight range of the active source."""
        w_min, w_max = self._ctrl.get_weight_range()
        self._remap_old_min.setValue(w_min)
        self._remap_old_max.setValue(w_max)

    @Slot()
    def _on_remap_invert(self) -> None:
        """Fill Old min/max from the actual weight range of the active source."""
        w_min, w_max = self._remap_old_min.value(), self._remap_old_max.value()
        self._remap_new_min.setValue(w_max)
        self._remap_new_max.setValue(w_min)

    @Slot(bool)
    def _on_storage_toggled(self, checked: bool) -> None:
        """Show or hide the storage panel and persist the user preference."""
        self._storage_panel.setVisible(checked)
        settings = QtCore.QSettings('DrWeeny', 'SlimfastWidget')
        settings.setValue('storage_expanded', checked)

    # ------------------------------------------------------------------
    # Session persistence for storage buttons  (DataHub — lives in-process)
    # ------------------------------------------------------------------
    def _save_storage_to_hub(self):
        """Serialise all storage button states into DataHubPub."""
        hub = data_hub.DataHubPub.Get()
        snapshot = [btn.to_dict() for btn in self._storage_buttons]
        hub.publish(self._HUB_KEY, snapshot, overwrite=True, notify=False)
        logger.debug(f"_save_storage_to_hub: saved {len(snapshot)} buttons")

    def _restore_storage_from_hub(self):
        """Re-create storage buttons from a previously saved DataHub snapshot."""
        hub = data_hub.DataHubPub.Get()
        snapshot = hub.retrieve(self._HUB_KEY)
        if not snapshot:
            return
        logger.debug(f"_restore_storage_from_hub: restoring {len(snapshot)} buttons")
        for data in snapshot:
            self._on_add_storage()                   # creates + appends a fresh button
            btn = self._storage_buttons[-1]
            btn.from_dict(data)                       # restores storage + label

    @Slot()
    def _on_add_storage(self) -> None:
        """Create a new VtxStorageButton slot below the existing ones."""
        btn = dw_maya.dw_pyqt_utils.dw_btn_storage.VtxStorageButton()
        slot_num = len(self._storage_buttons) + 1
        btn.setText(str(slot_num))
        btn.setFixedSize(40, 40)
        btn.setToolTip(f'Slot {slot_num}\nRight-click for options')

        # Pre-link to the currently active source so Store works immediately
        source = self._ctrl.active_source
        active_map = self._ctrl.active_map
        if source and active_map:
            btn.current_weight_node = f'{source.node_name}.{active_map}'
            btn.weight_source = source

        btn.remove_requested.connect(partial(self._on_remove_storage, btn))
        self._storage_layout.addWidget(btn)
        self._storage_buttons.append(btn)

    @Slot()
    def _on_remove_storage(self, btn: 'dw_maya.dw_pyqt_utils.dw_btn_storage.VtxStorageButton') -> None:
        """Remove a storage slot from the panel."""
        if btn in self._storage_buttons:
            self._storage_buttons.remove(btn)
            self._storage_layout.removeWidget(btn)
            btn.deleteLater()

    @Slot()
    def _on_refresh(self) -> None:
        self._ctrl.refresh()

    @Slot()
    def _on_pick_mesh(self) -> None:
        """Select the active mesh transform in the viewport."""
        source = self._ctrl.active_source
        if source:
            try:
                cmds.select(source.mesh_name, replace=True)
            except Exception as e:
                logger.warning(f"Could not select mesh: {e}")
        else:
            logger.warning("No active source — refresh first.")

    def _on_create_alpha_map(self) -> None:
        """Open a dialog to create a new vertex color alpha map on the selected mesh."""
        sel = cmds.ls(selection=True, transforms=True) or []
        if not sel:
            QtWidgets.QMessageBox.warning(
                self, 'Create alpha map',
                'Please select a mesh transform first.'
            )
            return

        mesh = sel[0]

        # Ask for the colorSet name
        name, ok = QtWidgets.QInputDialog.getText(
            self, 'New vertex alpha map',
            f'ColorSet name on "{mesh}":',
            QtWidgets.QLineEdit.Normal,
            'alphaMap',
        )
        if not ok or not name.strip():
            return

        # Ask for default fill value (0 = black, 1 = white)
        items = ['0.0  (black / empty)', '1.0  (white / full)']
        item, ok2 = QtWidgets.QInputDialog.getItem(
            self, 'Default value', 'Initial fill:', items, 0, False
        )
        if not ok2:
            return
        default_val = 0.0 if item.startswith('0') else 1.0

        try:
            from dw_maya.dw_paint.vertex_color_alpha import create_alpha_map
            create_alpha_map(mesh, color_set=name.strip(), default_value=default_val)
            logger.info(f"Alpha map '{name}' created on '{mesh}'.")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, 'Create alpha map', str(e))
            return

        # Refresh so the new map appears in the source list
        self._on_refresh()

    def _on_mode_visibility_changed(self, mode_key: str, visible: bool) -> None:
        """Show/hide a mode radio button and fall back to 'All' if needed.

        If the currently checked button is being hidden, we automatically
        switch to the 'All' button so the tool stays functional.

        Args:
            mode_key: Mode identifier string (e.g. ``'nucleus'``).
            visible:  Whether the button should be visible.
        """
        btn = self._mode_btns.get(mode_key)
        if btn is None:
            return
        btn.setVisible(visible)
        # Persist immediately so reloads don't lose the setting
        settings = QtCore.QSettings(self._org, self._appname)
        settings.setValue(f'mode_visible_{mode_key}', visible)
        # If the active button is hidden, fall back to first visible button
        if not visible and btn.isChecked():
            for fallback_key in ('deformer', 'all', 'nucleus', 'vtxColor'):
                fallback_btn = self._mode_btns.get(fallback_key)
                if fallback_btn and fallback_btn.isVisible():
                    fallback_btn.setChecked(True)
                    self._ctrl.set_mode(fallback_key)
                    break


    # ------------------------------------------------------------------
    # Source-type helpers
    # ------------------------------------------------------------------

    def _current_source_type_key(self) -> str:
        """Return a stable key for the currently active source type.

        Returns:
            ``'vtxColor'``, ``'nucleus'`` or ``'deformer'``.
        """
        src = self._ctrl.active_source
        from dw_maya.dw_paint.vertex_color_alpha import VertexColorAlpha as _VCA
        if isinstance(src, _VCA):
            return 'vtxColor'
        if isinstance(src, NClothMap):
            return 'nucleus'
        return 'deformer'

    def _current_op(self) -> str:
        """Return the currently selected weight operation mode."""
        checked = self._op_group.checkedButton()
        if checked:
            return checked.property('op') or 'replace'
        return 'replace'

    def _get_artisan_clamp(self) -> None:
        """Read standard Maya Paint context limits and update UI.

        Signals are blocked while the widgets are updated so that
        ``_set_artisan_clamp`` is NOT re-triggered (which would push the values
        back to the context creating a feedback loop).  After the widgets are
        set we explicitly call ``set_clamp_state`` on the controller so that
        subsequent numpy operations (flood, smooth) see the same values.
        """
        result = self._ctrl.get_artisan_clamp()
        if not result:
            return

        clamp_mode, lower_v, upper_v = result

        self._clamp_min_check.blockSignals(True)
        self._clamp_max_check.blockSignals(True)
        self._clamp_slider.blockSignals(True)

        self._clamp_min_check.setChecked(clamp_mode in ('lower', 'both'))
        self._clamp_max_check.setChecked(clamp_mode in ('upper', 'both'))
        self._clamp_slider.set_range(lower_v, upper_v)

        self._clamp_min_check.blockSignals(False)
        self._clamp_max_check.blockSignals(False)
        self._clamp_slider.blockSignals(False)

        # Sync controller stored state so numpy ops use the same limits
        self._ctrl.set_clamp_state(clamp_mode, lower_v, upper_v)


    def _set_artisan_clamp(self, *args) -> None:
        """Push UI limits down to Maya current Paint Context via controller."""
        if self._clamp_min_check.isChecked() and self._clamp_max_check.isChecked():
            clamp_mode = 'both'
        elif self._clamp_min_check.isChecked():
            clamp_mode = 'lower'
        elif self._clamp_max_check.isChecked():
            clamp_mode = 'upper'
        else:
            clamp_mode = 'none'

        cl = self._clamp_slider.low
        cu = self._clamp_slider.high

        self._ctrl.set_artisan_clamp(clamp_mode, cl, cu)

    @Slot(float)
    def _on_weight_slider_changed(self, value: float) -> None:
        """Sync artisan brush value live as the slider / spinbox moves.

        Called on every ``value_changed`` emission from the weight slider
        (both handle drag and spinbox edit).  We only push to the artisan
        context — the numpy flood is intentionally deferred to button click
        so we don't flood on every tick.
        """
        self._ctrl.set_artisan_value(value)

    @Slot()
    def _on_pb_picker_clicked(self) -> None:
        """Activate the one-shot viewport weight picker (eyedropper)."""
        self._pb_picker.setEnabled(False)
        self._ctrl.start_weight_picker(
            on_picked=self._on_weight_picked,
            on_cancel=self._on_weight_pick_done,
        )

    def _on_weight_picked(self, vtx_index: int, value: float) -> None:
        """Apply the picked vertex's weight to the slider (and artisan brush)."""
        self._set_weight_value_on_slider(value)
        self._on_weight_pick_done()

    def _on_weight_pick_done(self) -> None:
        self._pb_picker.setEnabled(True)

    def _set_weight_value_on_slider(self, value:float):
        self._weight_slider.value = value

    @Slot()
    def _on_set_weight(self, value: float = None) -> None:
        """Relay value and op mode to the controller.

        Also syncs the artisan brush value so that the live paint tool and the
        UI buttons stay coherent — clicking "Set 0.3" makes the artisan brush
        also paint at 0.3 on the next stroke.

        Args:
            value: Explicit value (used by Set 0 / Set 1).
                   Falls back to the slider value when omitted.
        """
        if value is None:
            value = self._weight_slider.value
        self._ctrl.set_weight(value, self._current_op())
        # Keep artisan brush in sync with the last-used value — the UI drives
        # the artisan one-way, and only on an explicit Set (not on every edit).
        self._ctrl.set_artisan_value(value)

    @Slot(int)
    def _on_tol_slider_changed(self, int_val: int) -> None:
        self._tol_spinbox.blockSignals(True)
        self._tol_spinbox.setValue(int_val / 100.0)
        self._tol_spinbox.blockSignals(False)

    @Slot(float)
    def _on_tol_spinbox_changed(self, float_val: float) -> None:
        self._tol_slider.blockSignals(True)
        self._tol_slider.setValue(int(float_val * 100))
        self._tol_slider.blockSignals(False)


    @Slot()
    def _on_invert_selection(self) -> None:
        self._ctrl.invert_selection()

    @Slot(QtWidgets.QAbstractButton)
    def _on_mode_changed(self, btn: QtWidgets.QAbstractButton) -> None:
        mode_key = btn.property('mode')
        ctrl_mode = wgt_deformer_panel.get_ctrl_mode(mode_key)
        self._ctrl.set_mode(ctrl_mode)

    @Slot(QtWidgets.QAbstractButton)
    def _on_op_mode_changed(self, btn: QtWidgets.QAbstractButton) -> None:
        """Push the Replace/Add/Multiply selection to the artisan brush operation."""
        op = btn.property('op')
        if op:
            self._ctrl.set_artisan_operation(op)

    def _switch_to_panel(
        self,
        panel_class: type) -> None:
        """Show the sub-panel for *panel_class*. Uses a QStackedWidget
        to manage the panels natively and preserve internal state.

        Args:
            panel_class: A ``DeformerPanelBase`` subclass from the registry.
        """
        if (self._current_panel is not None
                and type(self._current_panel) is panel_class):
            return

        # Get or lazily create the requested panel.
        panel = self._panel_cache.get(panel_class)
        if panel is None:
            panel = panel_class(parent=self._panel_container)
            panel.map_selected.connect(self._ctrl.select_map)
            self._panel_container.addWidget(panel)
            self._panel_cache[panel_class] = panel

        self._panel_container.setCurrentWidget(panel)
        self._current_panel = panel
        _size = self._current_panel._max_size
        self._panel_container.setFixedHeight(_size)
        self._panel_container.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.adjustSize()

        # Envelope row visibility is driven by the panel type.
        self._update_envelope_row()

    def _update_envelope_row(self) -> None:
        """Show/hide the envelope row based on the active panel and source."""
        has_env = (self._current_panel.has_envelope()
                   if self._current_panel else True)
        source = self._ctrl.active_source
        if source is None or not has_env:
            self._envelope_row_widget.hide()
            return
        env_attr = f'{source.node_name}.envelope'
        try:
            from maya import cmds as _cmds
            attr_exists = _cmds.objExists(env_attr)
        except Exception:
            attr_exists = False
        self._envelope_row_widget.setVisible(attr_exists)

    @Slot(list, list)
    def _on_sources_changed(self, node_labels: list, map_lists: list) -> None:
        """Rebuild the flat source combo from (node_labels, map_lists).

        Layout rules:
        - Single-map deformers (cluster, softMod, wire, …) -> one row.
        - BlendShape -> one row; panel switches to BlendShapePanel automatically.
        - NClothMap -> one row per map (nucleus maps are numerous).
        - A disabled separator row separates deformer and nucleus groups.

        UserRole  stores (source_idx, default_map_name).
        UserRole+1 stores (node_type, all_maps_list) for downstream logic.
        """
        self._source_model = QtGui.QStandardItemModel()

        if not node_labels:
            empty = QtGui.QStandardItem('— no sources —')
            empty.setEnabled(False)
            self._source_model.appendRow(empty)
            self._source_combo.blockSignals(True)
            self._source_combo.setModel(self._source_model)
            self._source_combo.blockSignals(False)
            return

        nucleus_types = {'nCloth', 'nRigid'}

        def _type_from_label(lbl: str) -> str:
            if lbl.startswith('['):
                return lbl[1:lbl.index(']')]
            return ''

        types = [_type_from_label(lbl) for lbl in node_labels]
        has_deformer = any(t not in nucleus_types for t in types)
        separator_inserted = False
        first_selectable_row = None

        for source_idx, (label, maps, node_type) in enumerate(
                zip(node_labels, map_lists, types)):

            node_name = label.split('] ', 1)[-1] if '] ' in label else label
            node_name = node_name.split(":")[-1]
            color = self._SOURCE_COLORS.get(node_type, '#cccccc')

            # Separator before first nucleus entry
            if node_type in nucleus_types and not separator_inserted and has_deformer:
                sep = QtGui.QStandardItem('─── nCloth / nRigid ───')
                sep.setEnabled(False)
                sep.setForeground(QtGui.QBrush(QtGui.QColor('#555555')))
                self._source_model.appendRow(sep)
                separator_inserted = True

            if node_type == 'blendShape':
                # One row — target maps are forwarded to BlendShapePanel via on_combo_changed.
                item = QtGui.QStandardItem(node_name)
                item.setData((source_idx, maps[0] if maps else 'weightList'), QtCore.Qt.UserRole)
                item.setData((node_type, maps), QtCore.Qt.UserRole + 1)
                item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
                self._source_model.appendRow(item)
                if first_selectable_row is None:
                    first_selectable_row = self._source_model.rowCount() - 1

            elif node_type in nucleus_types:
                # Nucleus: one row per map (many maps, no secondary combo)
                for map_name in maps:
                    display = f'{node_name}  › {map_name}'
                    item = QtGui.QStandardItem(display)
                    item.setData((source_idx, map_name), QtCore.Qt.UserRole)
                    item.setData((node_type, maps), QtCore.Qt.UserRole + 1)
                    item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
                    self._source_model.appendRow(item)
                    if first_selectable_row is None:
                        first_selectable_row = self._source_model.rowCount() - 1

            else:
                # Single-map deformer: one row, just the node name
                map_name = maps[0] if maps else 'weightList'
                item = QtGui.QStandardItem(node_name)
                item.setData((source_idx, map_name), QtCore.Qt.UserRole)
                item.setData((node_type, maps), QtCore.Qt.UserRole + 1)
                item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
                self._source_model.appendRow(item)
                if first_selectable_row is None:
                    first_selectable_row = self._source_model.rowCount() - 1

        self._source_combo.blockSignals(True)
        self._source_combo.setModel(self._source_model)
        if first_selectable_row is not None:
            self._source_combo.setCurrentIndex(first_selectable_row)
        self._source_combo.blockSignals(False)

        # Activate first entry — also triggers panel switching
        if first_selectable_row is not None:
            self._on_source_combo_changed(first_selectable_row)


    def _refresh_display_range(self) -> None:
        """Read weight range from the active source and update the display range widget.

        - If weights are strictly inside [0, 1]: hide the banner and pre-set the
          slider to [0, 1] so Paint will reset Maya's color range to defaults.
        - If any weight falls outside [0, 1]: show the banner pre-filled with
          the detected ``(min, max)`` rounded to 1 decimal.
        """
        result = self._ctrl.get_weight_range()
        if result is None:
            self._display_range_widget.hide()
            return

        lo, hi = result
        is_normal = (lo >= 0.0 and hi <= 1.0)

        # Always keep the slider calibrated so _on_paint_clicked can read it
        self._display_range_slider.blockSignals(True)
        if is_normal:
            self._display_range_slider.set_limits(0.0, 1.0)
            self._display_range_slider.set_range(0.0, 1.0)
        else:
            # No padding — padding causes integer-precision drift in the slider
            # when the limits shift: int(to_norm(0.0) * 99) can round away from 0
            # producing a spurious -0.1 offset when the max handle is dragged.
            # The spinboxes already accept any typed value via auto-extend.
            self._display_range_slider.set_limits(
                min(lo, 0.0), max(hi, 1.0)
            )
            self._display_range_slider.set_range(lo, hi)
        self._display_range_slider.blockSignals(False)

        self._display_range_widget.setVisible(not is_normal)

    @Slot()
    def _on_paint_clicked(self) -> None:
        """Open the paint tool then apply the display colour range.

        ``paint()`` must run first so that the artisan context exists before
        we try to edit its ``colorrangelower`` / ``colorrangeupper`` flags.
        The display range slider is always read, even when the banner is
        hidden (it is pre-seeded to ``[0, 1]`` for normal-range maps so that
        stale Maya values left over from a previous session are reset).
        """
        self._ctrl.paint()

        # inject color ramp if checked :
        # Re-apply ramp state after paint opens/refreshes artisan UI.
        use_ramp = bool(getattr(self, '_use_color_ramp_action', None)
                        and self._use_color_ramp_action.isChecked())
        try:
            from dw_maya.dw_paint.artisan_maya import inject_ramp_into_artattr
            inject_ramp_into_artattr(use_ramp=use_ramp)
        except Exception as e:
            logger.warning(f'Color ramp injection failed: {e}')

        lo = self._display_range_slider.low
        hi = self._display_range_slider.high
        self._ctrl.set_artisan_color_range(lo, hi)
        self._refresh_display_range()

    @Slot(int)
    def _on_source_combo_changed(self, combo_index: int) -> None:
        """Decode (source_idx, map_name) from the selected row and activate both."""
        if combo_index < 0:
            return
        model = self._source_combo.model()
        if model is None:
            return
        item = model.item(combo_index)
        if item is None or not item.isEnabled():
            return
        data = item.data(QtCore.Qt.UserRole)
        if data is None:
            return
        source_idx, map_name = data
        self._ctrl.select_source(source_idx)
        active_maps = self._ctrl.active_source.available_maps() if self._ctrl.active_source else []
        if active_maps and map_name != active_maps[0]:
            self._ctrl.select_map(map_name)

        extra = item.data(QtCore.Qt.UserRole + 1)
        node_type = extra[0] if extra else ''
        maps = extra[1] if extra else []

        panel_class = wgt_deformer_panel.get_panel_class(node_type)
        old_panel = self._current_panel  # capture BEFORE switch
        self._switch_to_panel(panel_class)

        if self._current_panel is not None:
            self._current_panel.on_combo_changed(node_type, maps)

            # active_changed already fired on old_panel inside select_source().
            # If the panel class changed, the new panel never received
            # on_source_changed — re-sync it explicitly.
            if self._current_panel is not old_panel:
                self._current_panel.on_source_changed(
                    self._ctrl.active_source,
                    self._ctrl.active_map or '',
                    self._ctrl,
                )

        # Auto-paint when enabled from the View menu preference.
        if getattr(self, '_auto_paint_action', None) and self._auto_paint_action.isChecked():
            if self._ctrl.active_source is not None:
                self._on_paint_clicked()

    @Slot(object)
    def _on_active_changed(self, source: Optional[WeightSource]) -> None:
        has_source = source is not None
        for w in (self._paint_btn, self._copy_btn, self._paste_btn,
                  self._set0_btn, self._set1_btn, self._weight_slider):
            w.setEnabled(has_source)

        # Keep storage buttons in sync with the currently active source/map.
        # Only update current_weight_node (the "restore target").
        # Do NOT overwrite weight_source — it belongs to stored data.
        active_map = self._ctrl.active_map
        for btn in self._storage_buttons:
            if source and active_map:
                btn.current_weight_node = f'{source.node_name}.{active_map}'
            else:
                btn.current_weight_node = None

        # Update transfer section target label.
        if source and active_map:
            self._transfer_tgt_label.setText(f'{source.node_name} › {active_map}')
        else:
            self._transfer_tgt_label.setText('— (active source) —')

        # --- Delegate type-specific UI to the active panel ---
        if self._current_panel is not None:
            self._current_panel.on_source_changed(source, active_map or '', self._ctrl)

        # --- Envelope row — visibility driven by panel + attribute presence ---
        has_env = (self._current_panel.has_envelope()
                   if self._current_panel else True)
        if has_source and has_env:
            env_attr = f'{source.node_name}.envelope'
            if cmds.objExists(env_attr):
                try:
                    val = cmds.getAttr(env_attr)
                    self._envelope_slider.blockSignals(True)
                    self._envelope_slider.setValue(val)
                    self._envelope_slider.blockSignals(False)
                    self._envelope_slider.setEnabled(True)
                    self._envelope_row_widget.show()
                except Exception:
                    self._envelope_slider.setEnabled(False)
                    self._envelope_row_widget.hide()
            else:
                self._envelope_row_widget.hide()
        else:
            self._envelope_row_widget.hide()

        # --- Smooth mode: save previous type pref, restore for new type ---
        settings = QtCore.QSettings('DrWeeny', 'SlimfastWidget')
        settings.setValue(f'smooth_mode_{self._src_type_key}',
                          self._smooth_mode.currentIndex())

        new_key = self._current_source_type_key()
        self._src_type_key = new_key
        default_mode = 1 if new_key == 'vtxColor' else 0
        saved_mode = settings.value(f'smooth_mode_{new_key}', default_mode, type=int)
        self._smooth_mode.blockSignals(True)
        self._smooth_mode.setCurrentIndex(saved_mode)
        self._smooth_mode.blockSignals(False)

        self._smooth_warn_label.setVisible(new_key == 'vtxColor')

        # --- Display range banner ---
        self._refresh_display_range()

    @Slot(float)
    def _on_envelope_changed(self, value: float) -> None:
        source = self._ctrl.active_source
        if source and not isinstance(source, NClothMap):
            env_attr = f'{source.node_name}.envelope'
            if cmds.objExists(env_attr):
                try:
                    cmds.setAttr(env_attr, value)
                except Exception as e:
                    logger.warning(f"Could not set envelope: {e}")

    def _on_smooth(self, iterations: int) -> None:
        self._smooth_busy_bar.show()
        QtWidgets.QApplication.processEvents()
        try:
            if self._smooth_mode.currentIndex() == 0:
                try:
                    self._ctrl.smooth_artisan(iterations)
                except RuntimeError as e:
                    QtWidgets.QMessageBox.warning(self, 'Smooth', str(e))
            else:
                self._ctrl.smooth(iterations)
        finally:
            self._smooth_busy_bar.hide()

    def _on_smooth_flood(self) -> None:
        self._on_smooth(self._iter_spinbox.value())

    @Slot()
    def _on_advanced_apply(self) -> None:
        """Apply the selected advanced weight distribution operation."""
        mode = self._adv_mode_combo.currentText()
        falloff = self._adv_falloff_combo.currentText()
        invert = self._adv_invert_check.isChecked()
        op = self._adv_op_combo.currentText()

        if mode == 'vector':
            vec_mode = self._adv_vec_mode_combo.currentText()
            if vec_mode == 'normal':
                direction = 'y+'  # unused but required
            elif self._adv_custom_check.isChecked():
                direction = self._adv_custom_vec.text().strip()
            else:
                checked = self._adv_axis_group.checkedButton()
                direction = checked.property('axis') if checked else 'y+'
            self._ctrl.apply_vector_weights(direction, falloff=falloff,
                                            invert=invert, mode=vec_mode, op=op)
        elif mode == 'radial':
            cx = self._adv_center_x.value()
            cy = self._adv_center_y.value()
            cz = self._adv_center_z.value()
            center = (cx, cy, cz) if any((cx, cy, cz)) else None
            radius = self._adv_radius_spin.value() or None
            self._ctrl.apply_radial_weights(falloff=falloff, invert=invert,
                                            center=center, radius=radius, op=op)

    @Slot(str)
    def _on_adv_mode_changed(self, mode: str) -> None:
        """Show the relevant sub-widget for the selected advanced mode."""
        self._adv_vector_widget.setVisible(mode == 'vector')
        self._adv_radial_widget.setVisible(mode == 'radial')

    def _toggle_axis_buttons(self, checked: bool, enable: bool = False) -> None:
        """Enable or disable axis radio buttons (used when custom vector is active)."""
        for btn in self._adv_axis_group.buttons():
            btn.setEnabled(not checked)

    @Slot()
    def _on_pick_radial_center(self) -> None:
        """Fill center spinboxes from the current selection bounding box."""
        cx, cy, cz = self._ctrl.get_selection_center()
        self._adv_center_x.setValue(cx)
        self._adv_center_y.setValue(cy)
        self._adv_center_z.setValue(cz)

    @Slot()
    def _on_pick_advanced_mask(self) -> None:
        """Restrict Advanced ops Apply to the current vertex selection."""
        count = self._ctrl.set_advanced_mask_from_selection()
        if count:
            self._adv_mask_label.setText(f'Mask: {count} verts')
        else:
            self._adv_mask_label.setText('Mask: whole mesh')
            logger.warning("No vertex selection to use as mask — Apply will affect the whole mesh.")

    @Slot()
    def _on_clear_advanced_mask(self) -> None:
        """Clear the Advanced ops vertex mask."""
        self._ctrl.clear_advanced_mask()
        self._adv_mask_label.setText('Mask: whole mesh')

    @Slot()
    def _on_read_soft_select_radius(self) -> None:
        """Read the soft-selection distance and put it in the radius spinbox."""
        r = self._ctrl.get_soft_select_radius()
        if r > 0.0:
            self._adv_radius_spin.setValue(r)
        else:
            logger.warning("Soft selection is disabled or radius is 0.")

    def _on_select_all(self) -> None:
        self._ctrl.select_all(0)

    def _on_select_by_range(self) -> None:
        """Select vertices within [low, high] of the range slider."""
        mods = QtWidgets.QApplication.keyboardModifiers()
        self._ctrl.select_vertices_by_range(
            self._range_sel.low, self._range_sel.high,
            self._qt_mods_to_maya(mods)
        )

    def _on_selection_range_moved(self, low, high):
        if self._auto_range_select_action.isChecked():
            self._ctrl.select_vertices_by_range(low, high, use_cache=True)

    def _on_range_selection_pressed(self):
        if self._auto_range_select_action.isChecked():
            self._ctrl._on_range_selection_pressed()

    def _on_range_selection_released(self):
        if self._auto_range_select_action.isChecked():
            self._ctrl._on_range_selection_released()

    def _on_select_by_limit(self, max_limit:bool=True):
        """
        When on clicking on min and max for selection of points
        Args:
            max_limit (bool): if False it takes the lowest value
        """
        # check if something is selected
        source = self._ctrl.active_source
        if source:
            weight_range = self._ctrl.get_weight_range()
            # for updating slider widget if visible
            gui_min_limit = self._range_sel.limit_min
            gui_max_limit = self._range_sel.limit_max

            if max_limit:
                value = weight_range[1]
                # updating slider
                if self._range_sel.isVisible():
                    if value > 1 and value != gui_max_limit:
                        self._range_sel.set_range(gui_min_limit, value)
                    self._range_sel.snap_to_max()

            else:
                value = weight_range[0]
                # updating slider
                if self._range_sel.isVisible():
                    if value > 0 and value != gui_min_limit:
                        self._range_sel.set_range(value, gui_max_limit)
                    self._range_sel.snap_to_min()
            # updating combobox
            if self._sel_value_spin.isVisible():
                # update single value selected
                self._sel_value_spin.setValue(value)
                # update tolerance
                self._sel_tol_slider.value = 0
            self._on_select_by_value(value, 0)

    def _on_select_by_value(self, value=None, tolerance=None) -> None:
        """Select vertices equal to value ± tolerance."""
        mods = QtWidgets.QApplication.keyboardModifiers()
        if value is None and tolerance is None:
            val = self._sel_value_spin.value()
            tol = self._sel_tol_slider.value
            self._ctrl.select_vertices_by_range(val - tol, val + tol,
                                                self._qt_mods_to_maya(mods))
        else:
            if not isinstance(tolerance, (float, int)):
                tolerance = 0
            if isinstance(value, (float, int)):
                self._ctrl.select_vertices_by_range(value - tolerance,
                                                    value + tolerance,
                                                    self._qt_mods_to_maya(mods))

    def _on_range_fit(self) -> None:
        """Fit the range slider limits to the actual min/max of current weights."""
        w_min, w_max = self._ctrl.get_weight_range()
        if w_max <= w_min:
            w_max = w_min + 0.001
        self._range_sel.set_limits(w_min, w_max)
        self._range_sel.set_range(w_min, w_max)

    def _on_sel_mode_toggled(self, value_mode: bool) -> None:
        """Switch between Range and Value selection mode, persist to QSettings."""
        self._range_slider_row_widget.setVisible(not value_mode)
        self._range_action_row_widget.setVisible(not value_mode)
        self._value_row_widget.setVisible(value_mode)
        settings = QtCore.QSettings(self._org, self._appname)
        settings.setValue('sel_value_mode', value_mode)

    @staticmethod
    def _qt_mods_to_maya(mods: QtCore.Qt.KeyboardModifiers) -> int:
        shift = bool(mods & QtCore.Qt.ShiftModifier)
        ctrl = bool(mods & QtCore.Qt.ControlModifier)
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

    def enterEvent(self, event) -> None:
        """Throttled artisan-clamp sync on mouse enter.

        Skipped when the active panel opts out via has_artisan_clamp() -> False
        (e.g. SkinPanel, which uses artAttrSkinPaintCtx instead of the
        generic artAttrContext).
        """
        super().enterEvent(event)

        import time
        now = time.monotonic()
        if now - getattr(self, '_last_clamp_sync', 0.0) >= self._CLAMP_SYNC_INTERVAL:
            self._last_clamp_sync = now
            if (self._current_panel is None or self._current_panel.has_artisan_clamp()):
                self._get_artisan_clamp()
            if self._current_panel is not None:
                self._current_panel.on_enter()  # ← panel-specific re-sync hook

    def closeEvent(self, event) -> None:
        """Persist smooth iteration count and section/mode visibilities on close."""
        settings = QtCore.QSettings(self._org, self._appname)
        settings.setValue('smooth_iterations', self.get_smooth_iterations())
        # Global smooth mode preference (artisan vs numpy)
        settings.setValue('smooth_mode', self._smooth_mode.currentIndex())
        settings.setValue('adv_section_visible', self._advanced_section.isVisible())
        settings.setValue('transfer_section_visible', self._transfer_section.isVisible())
        settings.setValue('remap_section_visible', self._remap_section.isVisible())
        for mode_key, btn in self._mode_btns.items():
            settings.setValue(f'mode_visible_{mode_key}', btn.isVisible())
        self._save_preferred_mode()
        self._save_storage_to_hub()
        super().closeEvent(event)

    def _show_help(self) -> None:
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle('Slimfast — help')
        msg.setText(
            "<b>Slimfast 2.0</b> — weight painting tool<br><br>"
            "<b>Mode toggle:</b> switch between deformer, nCloth, or both<br>"
            "<b>↺ Refresh:</b> re-scan selection for weight sources<br>"
            "<b>BlendShape:</b> a second combo appears for target maps<br>"
            "<b>Copy / Paste:</b> transfer weights between sources<br>"
            "<b>Paint:</b> open Maya artisan for the active source<br>"
            "<b>Set 0 / 1:</b> flood all vertices<br>"
            "<b>Weight slider -> Set:</b> flood current selection<br>"
            "<b>Smooth:</b> artisan path needs paint tool active;<br>"
            "&nbsp;&nbsp;&nbsp;&nbsp;numpy path works any time<br>"
            "<b>Select ALL:</b> select all vertices of the active mesh<br>"
            "<b>Invert:</b> invert current component selection (always active)<br>"
            "<b>Weight = 0/1:</b><br>"
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
    def _instance_alive(cls) -> bool:
        """Check if the singleton widget is still a valid C++ object."""
        if cls._instance is None:
            return False
        try:
            cls._instance.isVisible()
            return True
        except RuntimeError:
            cls._instance = None
            return False

    @classmethod
    def show_window(cls) -> 'SlimfastWidget':
        """Show as a floating window, reusing an existing instance."""
        if not cls._instance_alive():
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


