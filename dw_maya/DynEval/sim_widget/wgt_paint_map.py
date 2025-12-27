"""
Vertex Map Editor Widget with DataHub Integration

Advanced paint/flood controls for vertex maps.
Subscribes to selection changes to update mesh/map combos.
"""

from PySide6 import QtWidgets, QtCore, QtGui
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Tuple
from functools import partial

from maya import cmds

from dw_logger import get_logger

# Local imports
from ..hub_keys import HubKeys, PaintContext
from .wgt_base import DynEvalWidget

logger = get_logger()


class EditMode(Enum):
    REPLACE = "Replace"
    SUBTRACT = "Subtract"
    ADD = "Add"
    MULTIPLY = "Multiply"


class SelectionMode(Enum):
    RANGE = "Range"
    VALUE = "Value"


@dataclass
class EditorConfig:
    """Configuration for the vertex map editor."""
    min_value: float = 0.0
    max_value: float = 1.0
    decimals: int = 3
    default_value: float = 0.0
    smooth_presets: List[int] = None

    def __post_init__(self):
        if self.smooth_presets is None:
            self.smooth_presets = [2, 5, 10, 25, 50]


class RangeSlider(QtWidgets.QSlider):
    """Custom double-handled range slider."""

    rangeChanged = QtCore.Signal(float, float)

    def __init__(self, orientation=QtCore.Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.first_position = 0
        self.second_position = 99
        self.setMinimum(0)
        self.setMaximum(99)

        self.offset = 10
        self.movement = 0
        self.isSliderDown = False

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            pos_x = event.pos().x()
            val = self.minimum() + ((self.maximum() - self.minimum()) * pos_x) / self.width()

            if abs(self.first_position - val) < abs(self.second_position - val):
                self.first_position = val
                self.movement = 1
            else:
                self.second_position = val
                self.movement = 2

            self.isSliderDown = True
            self.update()
            self._emit_range()

    def mouseMoveEvent(self, event):
        if self.isSliderDown:
            pos_x = event.pos().x()
            val = self.minimum() + ((self.maximum() - self.minimum()) * pos_x) / self.width()

            if self.movement == 1:
                self.first_position = max(0, min(val, self.second_position - 1))
            else:
                self.second_position = min(99, max(val, self.first_position + 1))

            self.update()
            self._emit_range()

    def mouseReleaseEvent(self, event):
        self.isSliderDown = False
        self.movement = 0

    def _emit_range(self):
        """Emit the current range as normalized values."""
        min_val = self.first_position / 99.0
        max_val = self.second_position / 99.0
        self.rangeChanged.emit(min_val, max_val)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        # Track
        track_rect = QtCore.QRect(
            self.offset, self.height() // 2 - 2,
                         self.width() - 2 * self.offset, 4
        )
        painter.fillRect(track_rect, QtGui.QColor(80, 80, 80))

        # Selected range
        x1 = int(self.offset + (self.first_position / 99.0) * (self.width() - 2 * self.offset))
        x2 = int(self.offset + (self.second_position / 99.0) * (self.width() - 2 * self.offset))

        range_rect = QtCore.QRect(x1, self.height() // 2 - 2, x2 - x1, 4)
        painter.fillRect(range_rect, QtGui.QColor(100, 180, 100))

        # Handles
        for pos in [self.first_position, self.second_position]:
            x = int(self.offset + (pos / 99.0) * (self.width() - 2 * self.offset))
            handle_rect = QtCore.QRect(x - 5, self.height() // 2 - 8, 10, 16)
            painter.setBrush(QtGui.QColor(200, 200, 200))
            painter.setPen(QtGui.QColor(100, 100, 100))
            painter.drawRoundedRect(handle_rect, 3, 3)

    def setRange(self, min_val: float, max_val: float):
        """Set range from normalized values (0-1)."""
        self.first_position = int(min_val * 99)
        self.second_position = int(max_val * 99)
        self.update()


class VertexMapEditor(DynEvalWidget):
    """
    Advanced editor for vertex map painting and flooding.

    Subscribes to:
        - HubKeys.SELECTED_ITEM: Update combo boxes
        - HubKeys.SELECTED_MESH: Current mesh
        - HubKeys.MAP_SELECTED: Currently selected map

    Publishes:
        - HubKeys.PAINT_ACTIVE: Paint tool state
        - HubKeys.PAINT_CONTEXT: Current paint context
    """

    # Qt Signals
    floodRequested = QtCore.Signal(float, str)  # value, mode
    smoothRequested = QtCore.Signal(int)  # iterations
    selectionRequested = QtCore.Signal(float, float)  # min, max

    def __init__(self, config: EditorConfig = None, parent=None):
        super().__init__(parent)

        self.config = config or EditorConfig()

        # Current state
        self._current_mesh = None
        self._current_map = None
        self._is_painting = False

        # Setup
        self._setup_ui()
        self._connect_signals()
        self._setup_hub_subscriptions()

    def _setup_ui(self):
        """Initialize UI components."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        # Mesh/Map Selection
        selection_group = QtWidgets.QGroupBox("Selection")
        selection_layout = QtWidgets.QFormLayout(selection_group)

        self.mesh_combo = QtWidgets.QComboBox()
        self.mesh_combo.setPlaceholderText("Select mesh...")
        selection_layout.addRow("Mesh:", self.mesh_combo)

        self.map_combo = QtWidgets.QComboBox()
        self.map_combo.setPlaceholderText("Select map...")
        selection_layout.addRow("Map:", self.map_combo)

        layout.addWidget(selection_group)

        # Flood Section
        flood_group = QtWidgets.QGroupBox("Flood")
        flood_layout = QtWidgets.QVBoxLayout(flood_group)

        # Value input
        value_layout = QtWidgets.QHBoxLayout()
        value_layout.addWidget(QtWidgets.QLabel("Value:"))

        self.flood_value = QtWidgets.QDoubleSpinBox()
        self.flood_value.setRange(self.config.min_value, self.config.max_value)
        self.flood_value.setDecimals(self.config.decimals)
        self.flood_value.setValue(self.config.default_value)
        self.flood_value.setSingleStep(0.1)
        value_layout.addWidget(self.flood_value)

        self.flood_btn = QtWidgets.QPushButton("Flood")
        self.flood_btn.setFixedWidth(60)
        value_layout.addWidget(self.flood_btn)

        flood_layout.addLayout(value_layout)

        # Edit mode
        mode_layout = QtWidgets.QHBoxLayout()
        mode_layout.addWidget(QtWidgets.QLabel("Mode:"))

        self.mode_group = QtWidgets.QButtonGroup(self)
        for mode in EditMode:
            rb = QtWidgets.QRadioButton(mode.value)
            rb.setProperty("editMode", mode)
            self.mode_group.addButton(rb)
            mode_layout.addWidget(rb)
            if mode == EditMode.REPLACE:
                rb.setChecked(True)

        flood_layout.addLayout(mode_layout)

        # Clamp controls
        clamp_layout = QtWidgets.QHBoxLayout()
        self.clamp_check = QtWidgets.QCheckBox("Clamp")
        self.clamp_min = QtWidgets.QDoubleSpinBox()
        self.clamp_min.setRange(-10, 10)
        self.clamp_min.setValue(0)
        self.clamp_max = QtWidgets.QDoubleSpinBox()
        self.clamp_max.setRange(-10, 10)
        self.clamp_max.setValue(1)

        clamp_layout.addWidget(self.clamp_check)
        clamp_layout.addWidget(self.clamp_min)
        clamp_layout.addWidget(QtWidgets.QLabel("-"))
        clamp_layout.addWidget(self.clamp_max)
        clamp_layout.addStretch()

        flood_layout.addLayout(clamp_layout)
        layout.addWidget(flood_group)

        # Smooth Section
        smooth_group = QtWidgets.QGroupBox("Smooth")
        smooth_layout = QtWidgets.QHBoxLayout(smooth_group)

        for preset in self.config.smooth_presets:
            btn = QtWidgets.QPushButton(str(preset))
            btn.setFixedWidth(40)
            btn.setProperty("smoothValue", preset)
            btn.clicked.connect(self._on_smooth_preset)
            smooth_layout.addWidget(btn)

        layout.addWidget(smooth_group)

        # Selection by Weight Section
        selection_group = QtWidgets.QGroupBox("Select by Weight")
        selection_layout = QtWidgets.QVBoxLayout(selection_group)

        # Range limits
        limits_layout = QtWidgets.QHBoxLayout()
        limits_layout.addWidget(QtWidgets.QLabel("Limits:"))

        self.range_limit_min = QtWidgets.QDoubleSpinBox()
        self.range_limit_min.setRange(-100, 100)
        self.range_limit_min.setValue(0)
        self.range_limit_min.setDecimals(2)
        limits_layout.addWidget(self.range_limit_min)

        limits_layout.addWidget(QtWidgets.QLabel("-"))

        self.range_limit_max = QtWidgets.QDoubleSpinBox()
        self.range_limit_max.setRange(-100, 100)
        self.range_limit_max.setValue(1)
        self.range_limit_max.setDecimals(2)
        limits_layout.addWidget(self.range_limit_max)

        selection_layout.addLayout(limits_layout)

        # Range slider
        self.range_slider = RangeSlider()
        self.range_slider.setMinimumHeight(30)
        selection_layout.addWidget(self.range_slider)

        # Range values
        range_layout = QtWidgets.QHBoxLayout()

        self.range_min_spin = QtWidgets.QDoubleSpinBox()
        self.range_min_spin.setRange(0, 1)
        self.range_min_spin.setDecimals(3)
        self.range_min_spin.setValue(0)
        range_layout.addWidget(self.range_min_spin)

        range_layout.addStretch()

        self.range_max_spin = QtWidgets.QDoubleSpinBox()
        self.range_max_spin.setRange(0, 1)
        self.range_max_spin.setDecimals(3)
        self.range_max_spin.setValue(1)
        range_layout.addWidget(self.range_max_spin)

        selection_layout.addLayout(range_layout)

        # Selection mode
        mode_sel_layout = QtWidgets.QHBoxLayout()
        self.rb_range = QtWidgets.QRadioButton("Range")
        self.rb_range.setChecked(True)
        self.rb_value = QtWidgets.QRadioButton("≥ Value")
        mode_sel_layout.addWidget(self.rb_range)
        mode_sel_layout.addWidget(self.rb_value)
        mode_sel_layout.addStretch()
        selection_layout.addLayout(mode_sel_layout)

        # Selection buttons
        sel_btn_layout = QtWidgets.QHBoxLayout()

        self.select_btn = QtWidgets.QPushButton("Select")
        self.select_btn.clicked.connect(self._select_by_weight)
        sel_btn_layout.addWidget(self.select_btn)

        self.invert_btn = QtWidgets.QPushButton("Invert")
        self.invert_btn.clicked.connect(self._invert_selection)
        sel_btn_layout.addWidget(self.invert_btn)

        self.clear_btn = QtWidgets.QPushButton("Clear")
        self.clear_btn.clicked.connect(self._clear_selection)
        sel_btn_layout.addWidget(self.clear_btn)

        selection_layout.addLayout(sel_btn_layout)
        layout.addWidget(selection_group)

        # Storage Section
        storage_group = QtWidgets.QGroupBox("Weight Storage")
        storage_layout = QtWidgets.QHBoxLayout(storage_group)

        self.store_btn = QtWidgets.QPushButton("Store")
        self.store_btn.clicked.connect(self._store_weights)
        storage_layout.addWidget(self.store_btn)

        self.recall_btn = QtWidgets.QPushButton("Recall")
        self.recall_btn.clicked.connect(self._recall_weights)
        storage_layout.addWidget(self.recall_btn)

        self.blend_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.blend_slider.setRange(0, 100)
        self.blend_slider.setValue(100)
        storage_layout.addWidget(self.blend_slider)

        self.blend_label = QtWidgets.QLabel("100%")
        storage_layout.addWidget(self.blend_label)

        layout.addWidget(storage_group)

        # Stretch at bottom
        layout.addStretch()

    def _connect_signals(self):
        """Connect internal signals."""
        self.flood_btn.clicked.connect(self._flood)
        self.blend_slider.valueChanged.connect(
            lambda v: self.blend_label.setText(f"{v}%")
        )

        # Range slider
        self.range_slider.rangeChanged.connect(self._on_range_changed)
        self.range_min_spin.valueChanged.connect(
            lambda v: self._on_spin_changed(v, True)
        )
        self.range_max_spin.valueChanged.connect(
            lambda v: self._on_spin_changed(v, False)
        )

        # Limits
        self.range_limit_min.valueChanged.connect(self._update_range_limits)
        self.range_limit_max.valueChanged.connect(self._update_range_limits)

    def _setup_hub_subscriptions(self):
        """Subscribe to hub keys."""
        self.hub_subscribe(HubKeys.SELECTED_ITEM, self._on_selection_changed)
        self.hub_subscribe(HubKeys.SELECTED_MESH, self._on_mesh_changed)
        self.hub_subscribe(HubKeys.MAP_SELECTED, self._on_map_selected)

    # ========================================================================
    # HUB CALLBACKS
    # ========================================================================

    def _on_selection_changed(self, old_value, new_value):
        """Handle selection change from main tree."""
        if new_value is None:
            self.mesh_combo.clear()
            self.map_combo.clear()
            return

        # Get mesh from selection
        mesh = getattr(new_value, 'mesh_transform', None)
        if mesh:
            self._update_mesh_combo(mesh)

    def _on_mesh_changed(self, old_value, new_value):
        """Handle mesh change."""
        if new_value:
            self._update_mesh_combo(new_value)
        self._current_mesh = new_value

    def _on_map_selected(self, old_value, new_value):
        """Handle map selection from map tree."""
        if new_value is None:
            return

        map_name = getattr(new_value, 'name', str(new_value))

        # Update combo if not already selected
        idx = self.map_combo.findText(map_name)
        if idx >= 0:
            self.map_combo.setCurrentIndex(idx)

        self._current_map = map_name

    # ========================================================================
    # COMBO MANAGEMENT
    # ========================================================================

    def _update_mesh_combo(self, mesh: str):
        """Update mesh combo with current mesh."""
        self.mesh_combo.clear()
        self.mesh_combo.addItem(mesh)
        self.mesh_combo.setCurrentText(mesh)
        self._update_map_combo(mesh)

    def _update_map_combo(self, mesh: str):
        """Update map combo based on mesh selection."""
        self.map_combo.clear()

        # Get maps for this mesh (would need nucleus node)
        try:
            from ..sim_cmds.vtx_map_management import get_vtx_maps

            # Find connected simulation node
            history = cmds.listHistory(mesh, pdo=True) or []
            sim_nodes = [n for n in history
                         if cmds.nodeType(n) in ['nCloth', 'nRigid', 'hairSystem']]

            if sim_nodes:
                maps = get_vtx_maps(sim_nodes[0])
                for map_name in maps:
                    self.map_combo.addItem(map_name)
        except Exception as e:
            logger.debug(f"Could not get maps: {e}")

    def get_combo_data(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Get current combo selections."""
        mesh = self.mesh_combo.currentText() or None
        map_name = self.map_combo.currentText() or None

        # Get nucleus node
        nucx = None
        if mesh:
            try:
                history = cmds.listHistory(mesh, pdo=True) or []
                sim_nodes = [n for n in history
                             if cmds.nodeType(n) in ['nCloth', 'nRigid', 'hairSystem']]
                nucx = sim_nodes[0] if sim_nodes else None
            except Exception:
                pass

        return nucx, map_name, mesh

    # ========================================================================
    # FLOOD OPERATIONS
    # ========================================================================

    def _flood(self):
        """Execute flood operation."""
        from ..sim_cmds.vtx_map_management import flood_map

        value = self.flood_value.value()
        mode = self.mode_group.checkedButton().property("editMode")

        nucx, map_name, mesh = self.get_combo_data()
        if not nucx or not map_name:
            cmds.warning("Please select a mesh and map first")
            return

        # Apply clamp if enabled
        if self.clamp_check.isChecked():
            clamp = (self.clamp_min.value(), self.clamp_max.value())
        else:
            clamp = None

        logger.info(f"Flooding {map_name} with {value} ({mode.value})")
        flood_map(nucx, map_name, value, mode.value.lower(), clamp=clamp)

        self.floodRequested.emit(value, mode.value)

    # ========================================================================
    # RANGE OPERATIONS
    # ========================================================================

    def _on_range_changed(self, min_norm: float, max_norm: float):
        """Handle range slider change."""
        limit_min = self.range_limit_min.value()
        limit_max = self.range_limit_max.value()

        actual_min = limit_min + min_norm * (limit_max - limit_min)
        actual_max = limit_min + max_norm * (limit_max - limit_min)

        self.range_min_spin.blockSignals(True)
        self.range_max_spin.blockSignals(True)

        self.range_min_spin.setValue(actual_min)
        self.range_max_spin.setValue(actual_max)

        self.range_min_spin.blockSignals(False)
        self.range_max_spin.blockSignals(False)

    def _on_spin_changed(self, value: float, is_min: bool):
        """Handle range spinbox change."""
        value_range = self.range_limit_max.value() - self.range_limit_min.value()
        if value_range == 0:
            return

        slider_value = ((value - self.range_limit_min.value()) / value_range) * 99.0
        slider_value = max(0, min(99, slider_value))

        if is_min:
            self.range_slider.first_position = slider_value
        else:
            self.range_slider.second_position = slider_value

        self.range_slider.update()

    def _update_range_limits(self):
        """Update spinbox ranges when limits change."""
        new_min = self.range_limit_min.value()
        new_max = self.range_limit_max.value()

        self.range_min_spin.setRange(new_min, new_max)
        self.range_max_spin.setRange(new_min, new_max)

    # ========================================================================
    # SMOOTH OPERATIONS
    # ========================================================================

    def _on_smooth_preset(self):
        """Handle smooth preset button click."""
        iterations = self.sender().property("smoothValue")
        self._smooth_flood(iterations)

    def _smooth_flood(self, iterations: int):
        """Apply smooth operation."""
        from ..sim_cmds.vtx_map_management import smooth_pervtx_map

        logger.debug(f"Smooth flood: {iterations} iterations")
        smooth_pervtx_map(iterations)
        self.smoothRequested.emit(iterations)

    # ========================================================================
    # SELECTION OPERATIONS
    # ========================================================================

    def _select_by_weight(self):
        """Select vertices by weight range."""
        from ..sim_cmds import get_vtx_map_data
        from dw_maya.dw_paint import WeightDataFactory
        from dw_maya.dw_nucleus_utils import artisan_nucx_update

        min_val = self.range_min_spin.value()
        max_val = self.range_max_spin.value()

        nucx, map_name, mesh = self.get_combo_data()
        if not nucx or not map_name:
            cmds.warning("Please select a mesh and map first")
            return

        # Get weights
        weights = get_vtx_map_data(nucx, f"{map_name}PerVertex")
        if not weights:
            cmds.warning("No weight data found")
            return

        # Select by range
        weight_data = WeightDataFactory.create(weights, mesh)

        if self.rb_range.isChecked():
            weight_data.select_indexes_by_weights(min_val, max_val)
        else:
            weight_data.select_indexes_by_weights(min_val)

        # Update artisan
        artisan_nucx_update(nucx, map_name, True)

    def _invert_selection(self):
        """Invert current selection."""
        from dw_maya.dw_maya_utils import invert_selection
        from dw_maya.dw_nucleus_utils import artisan_nucx_update

        invert_selection()

        nucx, map_name, mesh = self.get_combo_data()
        if nucx and map_name:
            artisan_nucx_update(nucx, map_name, True)

    def _clear_selection(self):
        """Clear selection and select mesh."""
        from dw_maya.dw_nucleus_utils import artisan_nucx_update

        nucx, map_name, mesh = self.get_combo_data()

        cmds.select(clear=True)
        if mesh:
            cmds.select(mesh, r=True)

        if nucx and map_name:
            artisan_nucx_update(nucx, map_name, True)

    # ========================================================================
    # STORAGE OPERATIONS
    # ========================================================================

    def _store_weights(self):
        """Store current weights for later recall."""
        from ..sim_cmds import get_vtx_map_data

        nucx, map_name, mesh = self.get_combo_data()
        if not nucx or not map_name:
            cmds.warning("Please select a mesh and map first")
            return

        weights = get_vtx_map_data(nucx, f"{map_name}PerVertex")
        if weights:
            self._stored_weights = weights.copy()
            logger.info(f"Stored {len(weights)} weight values")

    def _recall_weights(self):
        """Recall stored weights with blend."""
        from ..sim_cmds.vtx_map_management import set_vtx_map_data
        from ..sim_cmds import get_vtx_map_data

        if not hasattr(self, '_stored_weights') or not self._stored_weights:
            cmds.warning("No stored weights to recall")
            return

        nucx, map_name, mesh = self.get_combo_data()
        if not nucx or not map_name:
            return

        blend = self.blend_slider.value() / 100.0

        if blend == 1.0:
            # Full recall
            set_vtx_map_data(nucx, f"{map_name}PerVertex", self._stored_weights)
        else:
            # Blend with current
            current = get_vtx_map_data(nucx, f"{map_name}PerVertex")
            if current and len(current) == len(self._stored_weights):
                blended = [
                    c * (1 - blend) + s * blend
                    for c, s in zip(current, self._stored_weights)
                ]
                set_vtx_map_data(nucx, f"{map_name}PerVertex", blended)

        logger.info(f"Recalled weights at {blend * 100}% blend")

    # CLEANUP - handled by DynEvalWidget base class


# ============================================================================
# STANDALONE TEST
# ============================================================================

if __name__ == '__main__':
    app = QtWidgets.QApplication([])

    config = EditorConfig(min_value=0.0, max_value=1.0, decimals=3)
    editor = VertexMapEditor(config)
    editor.show()

    app.exec()