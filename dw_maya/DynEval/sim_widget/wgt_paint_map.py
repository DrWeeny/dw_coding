from PySide6 import QtWidgets, QtCore, QtGui
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable, List, Tuple

from dw_maya.dw_nucleus_utils.dw_core import get_nucx_map_type
from dw_maya.dw_nucleus_utils import get_nucleus_solver
from .wgt_combotree import TreeComboBox
from .wgt_combobox_maps import ColoredMapComboBox
from ..sim_cmds.vtx_map_management import smooth_pervtx_map

from dw_logger import get_logger

logger = get_logger()

class EditMode(Enum):
    REPLACE = "Replace"
    SUBTRACT = "Subtract"
    ADD = "Add"
    MULTIPLY = "Multiply"

class SelectionMode(Enum):
    RANGE = "Range"
    VALUE = "Value"

class SolverType(Enum):
    """Types of solvers supported by the editor"""
    NUCLEUS = "Nucleus"
    DEFORMER = "Deformers"
    ZIVA = "Ziva"  # Will be disabled for now

@dataclass
class EditorConfig:
    """Configuration for the vertex map editor"""
    min_value: float = 0.0
    max_value: float = 1.0
    decimals: int = 4
    default_value: float = 0.0
    smooth_presets: List[int] = None

    def __post_init__(self):
        if self.smooth_presets is None:
            self.smooth_presets = [2, 5, 10, 25, 50]

class RangeSlider(QtWidgets.QSlider):
    """Custom double-handled range slider"""

    rangeChanged = QtCore.Signal(float, float)

    def __init__(self, orientation=QtCore.Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.first_position = 0
        self.second_position = 99
        self.setMinimum(0)
        self.setMaximum(99)

        # Visual settings
        self.offset = 10
        self.movement = 0
        self.isSliderDown = False

        # Style
        self.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #999999;
                height: 4px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #B1B1B1, stop:1 #c4c4c4);
                margin: 2px 0;
            }

            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #b4b4b4, stop:1 #8f8f8f);
                border: 1px solid #5c5c5c;
                width: 10px;
                margin: -8px 0;
                border-radius: 3px;
            }
        """)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            but = event.pos().x()
            val = self.minimum() + ((self.maximum() - self.minimum()) * but) / self.width()

            if abs(self.first_position - val) < abs(self.second_position - val):
                self.first_position = val
                self.isSliderDown = True
                self.movement = 1
            else:
                self.second_position = val
                self.isSliderDown = True
                self.movement = 2

            self.update()
            self.rangeChanged.emit(min(self.first_position, self.second_position),
                                   max(self.first_position, self.second_position))

    def mouseMoveEvent(self, event):
        if self.isSliderDown:
            but = event.pos().x()
            val = self.minimum() + ((self.maximum() - self.minimum()) * but) / self.width()
            if self.movement == 1:
                self.first_position = val
            else:
                self.second_position = val
            self.update()
            self.rangeChanged.emit(min(self.first_position, self.second_position),
                                   max(self.first_position, self.second_position))

    def mouseReleaseEvent(self, event):
        self.isSliderDown = False

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        # Draw the range
        rect = self.rect()
        x_left = (rect.width() - 2 * self.offset) * (self.first_position / self.maximum()) + self.offset
        x_right = (rect.width() - 2 * self.offset) * (self.second_position / self.maximum()) + self.offset

        # Background track
        track_rect = QtCore.QRectF(self.offset, rect.height() / 2 - 2, rect.width() - 2 * self.offset, 4)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(200, 200, 200))
        painter.drawRoundedRect(track_rect, 2, 2)

        # Selected range
        range_rect = QtCore.QRectF(x_left, rect.height() / 2 - 2, x_right - x_left, 4)
        painter.setBrush(QtGui.QColor(100, 150, 255))
        painter.drawRoundedRect(range_rect, 2, 2)

        # Handles
        handle_rect = QtCore.QRectF(-5, -10, 10, 20)
        painter.setBrush(QtGui.QColor(255, 255, 255))
        painter.setPen(QtGui.QPen(QtGui.QColor(100, 100, 100), 1))

        handle_rect.moveCenter(QtCore.QPointF(x_left, rect.height() / 2))
        painter.drawRoundedRect(handle_rect, 3, 3)

        handle_rect.moveCenter(QtCore.QPointF(x_right, rect.height() / 2))
        painter.drawRoundedRect(handle_rect, 3, 3)

class VertexMapEditor(QtWidgets.QWidget):
    """
    Modern vertex map editor widget with flood controls and clamping
    """

    valueChanged = QtCore.Signal(float)  # Emitted when the main value changes
    floodRequested = QtCore.Signal(float, EditMode)  # Emitted when flood is requested
    selectionModeChanged = QtCore.Signal(SelectionMode)  # Emitted when selection mode changes
    selectionRangeChanged = QtCore.Signal(float, float)  # Emitted when range values change
    smoothRequested = QtCore.Signal(int)  # Emitted when smoothing is requested

    solverChanged = QtCore.Signal(SolverType)  # Emitted when solver type changes
    meshChanged = QtCore.Signal(str)  # Emitted when mesh selection changes
    mapChanged = QtCore.Signal(str)  # Emitted when map selection changes
    paintRequested = QtCore.Signal()  # Emitted when paint button is clicked

    def __init__(self, config: EditorConfig = None, parent=None):
        super().__init__(parent)
        self.mesh_selected = None
        self.map_selected = None
        self.config = config or EditorConfig()
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setSpacing(4)

        # Add solver type selection at the top
        self._setup_solver_selection(main_layout)

        # Add mesh and map selection
        self._setup_map_selection(main_layout)

        # Value Editor Group (from previous implementation)
        self._setup_value_editor(main_layout)

        # Selection Range Group
        selection_group = QtWidgets.QGroupBox("Vertex Selection")
        selection_layout = QtWidgets.QVBoxLayout(selection_group)

        # Selection Mode
        mode_layout = QtWidgets.QHBoxLayout()
        self.selection_mode_group = QtWidgets.QButtonGroup(self)
        self.rb_range = QtWidgets.QRadioButton("Range")
        self.rb_value = QtWidgets.QRadioButton("Value")
        self.selection_mode_group.addButton(self.rb_range)
        self.selection_mode_group.addButton(self.rb_value)
        self.rb_range.setChecked(True)

        mode_layout.addWidget(self.rb_range)
        mode_layout.addWidget(self.rb_value)
        mode_layout.addStretch()

        # Selection Actions
        action_layout = QtWidgets.QHBoxLayout()
        self.btn_select = QtWidgets.QPushButton("Select")
        self.btn_invert = QtWidgets.QPushButton("Invert")
        self.btn_clear = QtWidgets.QPushButton("Clear")

        for btn in [self.btn_select, self.btn_invert, self.btn_clear]:
            btn.setFixedHeight(24)
            action_layout.addWidget(btn)

        # Range Controls
        range_layout = QtWidgets.QHBoxLayout()

        self.range_min_spin = QtWidgets.QDoubleSpinBox()
        self.range_min_spin.setRange(self.config.min_value, self.config.max_value)
        self.range_min_spin.setDecimals(self.config.decimals)
        self.range_min_spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)

        self.range_slider = RangeSlider(QtCore.Qt.Horizontal)

        self.range_max_spin = QtWidgets.QDoubleSpinBox()
        self.range_max_spin.setRange(self.config.min_value, self.config.max_value)
        self.range_max_spin.setDecimals(self.config.decimals)
        self.range_max_spin.setValue(self.config.max_value)
        self.range_max_spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)

        range_layout.addWidget(self.range_min_spin)
        range_layout.addWidget(self.range_slider)
        range_layout.addWidget(self.range_max_spin)

        selection_layout.addLayout(mode_layout)
        selection_layout.addLayout(action_layout)
        selection_layout.addLayout(range_layout)

        # Smoothing Group
        smooth_group = QtWidgets.QGroupBox("Smooth Values")
        smooth_layout = QtWidgets.QVBoxLayout(smooth_group)

        # Preset Buttons
        preset_layout = QtWidgets.QHBoxLayout()
        self.smooth_buttons = {}

        for preset in self.config.smooth_presets:
            btn = QtWidgets.QPushButton(str(preset))
            btn.setFixedSize(40, 20)
            btn.setProperty("smoothValue", preset)
            self.smooth_buttons[preset] = btn
            preset_layout.addWidget(btn)

        preset_layout.addStretch()

        # Custom Iterations
        iter_layout = QtWidgets.QHBoxLayout()
        iter_layout.addWidget(QtWidgets.QLabel("Iterations:"))

        self.iter_spin = QtWidgets.QSpinBox()
        self.iter_spin.setRange(1, 500)
        self.iter_spin.setValue(100)
        self.iter_spin.setFixedWidth(60)

        self.iter_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.iter_slider.setRange(1, 500)
        self.iter_slider.setValue(100)

        self.btn_smooth = QtWidgets.QPushButton("Smooth")
        self.btn_smooth.setFixedWidth(60)

        iter_layout.addWidget(self.iter_spin)
        iter_layout.addWidget(self.iter_slider)
        iter_layout.addWidget(self.btn_smooth)

        smooth_layout.addLayout(preset_layout)
        smooth_layout.addLayout(iter_layout)

        # Add all groups to main layout
        main_layout.addWidget(selection_group)
        main_layout.addWidget(smooth_group)
        main_layout.addStretch()

    def _setup_value_editor(self, main_layout):
        """Setup the value editor section with flood controls and edit modes"""
        # Value Editor Group
        value_group = QtWidgets.QGroupBox("Vertex Value Editor")
        value_layout = QtWidgets.QVBoxLayout(value_group)

        # Flood Controls with 0/1 shortcuts
        flood_layout = QtWidgets.QHBoxLayout()

        # Set 0 button
        self.btn_zero = QtWidgets.QPushButton("0")
        self.btn_zero.setFixedWidth(40)
        self.btn_zero.setStyleSheet("""
            QPushButton {
                background-color: rgb(42, 42, 42);
                color: white;
                font-weight: bold;
                padding: 4px;
                border-radius: 2px;
            }
            QPushButton:hover {
                background-color: rgb(60, 60, 60);
            }
        """)

        # Value Editor Control
        self.value_spinbox = QtWidgets.QDoubleSpinBox()
        self.value_spinbox.setRange(self.config.min_value, self.config.max_value)
        self.value_spinbox.setDecimals(self.config.decimals)
        self.value_spinbox.setValue(self.config.default_value)
        self.value_spinbox.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.value_spinbox.setFixedWidth(80)

        # Main Flood Button
        self.flood_button = QtWidgets.QPushButton("Flood")
        self.flood_button.setStyleSheet("""
            QPushButton {
                background-color: rgb(42, 42, 42);
                color: white;
                font-weight: bold;
                padding: 4px;
                border-radius: 2px;
            }
            QPushButton:hover {
                background-color: rgb(60, 60, 60);
            }
        """)

        # Set 1 button
        self.btn_one = QtWidgets.QPushButton("1")
        self.btn_one.setFixedWidth(40)
        self.btn_one.setStyleSheet("""
            QPushButton {
                background-color: rgb(242, 242, 242);
                color: black;
                font-weight: bold;
                padding: 4px;
                border-radius: 2px;
            }
            QPushButton:hover {
                background-color: rgb(220, 220, 220);
            }
        """)

        # Add buttons to flood layout
        flood_layout.addWidget(self.value_spinbox)
        flood_layout.addWidget(self.btn_zero)
        flood_layout.addWidget(self.flood_button)
        flood_layout.addWidget(self.btn_one)

        # Edit Mode Section
        mode_layout = QtWidgets.QHBoxLayout()
        mode_layout.setSpacing(8)
        mode_label = QtWidgets.QLabel("Edit Mode:")
        mode_layout.addWidget(mode_label)

        # Create radio buttons for edit modes
        self.mode_group = QtWidgets.QButtonGroup(self)
        self.mode_buttons = {}

        for mode in EditMode:
            btn = QtWidgets.QRadioButton(mode.value)
            self.mode_buttons[mode] = btn
            self.mode_group.addButton(btn)
            mode_layout.addWidget(btn)

        self.mode_buttons[EditMode.REPLACE].setChecked(True)
        mode_layout.addStretch()

        # Clamp Controls
        clamp_layout = QtWidgets.QHBoxLayout()
        clamp_label = QtWidgets.QLabel("Clamp Values:")
        clamp_layout.addWidget(clamp_label)

        # Min Clamp
        self.clamp_min_check = QtWidgets.QCheckBox("Min")
        self.clamp_min_check.setChecked(True)
        self.clamp_min_spin = QtWidgets.QDoubleSpinBox()
        self.clamp_min_spin.setRange(self.config.min_value, self.config.max_value)
        self.clamp_min_spin.setDecimals(self.config.decimals)
        self.clamp_min_spin.setValue(self.config.min_value)
        self.clamp_min_spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)

        # Max Clamp
        self.clamp_max_check = QtWidgets.QCheckBox("Max")
        self.clamp_max_check.setChecked(True)
        self.clamp_max_spin = QtWidgets.QDoubleSpinBox()
        self.clamp_max_spin.setRange(self.config.min_value, self.config.max_value)
        self.clamp_max_spin.setDecimals(self.config.decimals)
        self.clamp_max_spin.setValue(self.config.max_value)
        self.clamp_max_spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)

        # Add clamp controls to layout
        clamp_layout.addWidget(self.clamp_min_check)
        clamp_layout.addWidget(self.clamp_min_spin)
        clamp_layout.addStretch()
        clamp_layout.addWidget(self.clamp_max_check)
        clamp_layout.addWidget(self.clamp_max_spin)
        clamp_layout.addStretch()

        # Add layouts to group
        value_layout.addLayout(flood_layout)
        value_layout.addLayout(mode_layout)
        value_layout.addLayout(clamp_layout)

        # Add value editor group to main layout
        main_layout.addWidget(value_group)

        # Connect value editor signals
        self.value_spinbox.valueChanged.connect(self.valueChanged.emit)
        self.btn_zero.clicked.connect(lambda: self._handle_flood(0.0))
        self.btn_one.clicked.connect(lambda: self._handle_flood(1.0))
        self.flood_button.clicked.connect(lambda: self._handle_flood(self.value_spinbox.value()))

        # Connect clamp value changes
        self.clamp_min_spin.valueChanged.connect(self._validate_clamp_ranges)
        self.clamp_max_spin.valueChanged.connect(self._validate_clamp_ranges)

    def _setup_solver_selection(self, main_layout):
        """Setup the solver type selection section"""
        solver_group = QtWidgets.QGroupBox("Solver Type")
        solver_layout = QtWidgets.QHBoxLayout(solver_group)

        # Create radio buttons for solver types
        self.solver_group = QtWidgets.QButtonGroup(self)
        self.solver_buttons = {}

        # Create and style each radio button
        for solver_type in SolverType:
            btn = QtWidgets.QRadioButton(solver_type.value)
            self.solver_buttons[solver_type] = btn
            self.solver_group.addButton(btn)
            solver_layout.addWidget(btn)

            # Disable Ziva button
            if solver_type == SolverType.ZIVA:
                btn.setEnabled(False)
                btn.setStyleSheet("color: gray;")

            # Set Nucleus as default
            if solver_type == SolverType.NUCLEUS:
                btn.setChecked(True)

        solver_layout.addStretch()
        main_layout.addWidget(solver_group)

    def _setup_map_selection(self, main_layout):
        """Setup the mesh and map selection section"""
        selection_group = QtWidgets.QGroupBox("Map Selection")
        selection_layout = QtWidgets.QHBoxLayout(selection_group)

        # Mesh selection combo
        mesh_layout = QtWidgets.QHBoxLayout()
        mesh_label = QtWidgets.QLabel("Mesh:")
        self.mesh_combo = TreeComboBox()
        self.mesh_combo.setMinimumWidth(150)
        mesh_layout.addWidget(mesh_label)
        mesh_layout.addWidget(self.mesh_combo)

        # Map selection combo
        map_layout = QtWidgets.QHBoxLayout()
        map_label = QtWidgets.QLabel("Map:")
        self.map_combo = ColoredMapComboBox()
        self.map_combo.setMinimumWidth(150)
        map_layout.addWidget(map_label)
        map_layout.addWidget(self.map_combo)

        # Paint button
        self.paint_button = QtWidgets.QPushButton("Paint")
        self.paint_button.setStyleSheet("""
            QPushButton {
                background-color: rgb(42, 42, 42);
                color: white;
                font-weight: bold;
                padding: 6px 15px;
                border-radius: 2px;
            }
            QPushButton:hover {
                background-color: rgb(60, 60, 60);
            }
            QPushButton:disabled {
                background-color: rgb(100, 100, 100);
                color: rgb(180, 180, 180);
            }
        """)

        # populate painting combobox
        self.populate_treecombobox()
        self.populate_map_combobox()

        # Add all elements to selection layout
        selection_layout.addLayout(mesh_layout)
        selection_layout.addLayout(map_layout)
        selection_layout.addWidget(self.paint_button)

        main_layout.addWidget(selection_group)

    def _connect_signals(self):
        """Connect all widget signals"""

        # Selection mode signals
        self.selection_mode_group.buttonClicked.connect(self._handle_selection_mode)

        # Range control signals
        self.range_slider.rangeChanged.connect(self._handle_range_change)
        self.range_min_spin.valueChanged.connect(lambda v: self._handle_spin_change(v, True))
        self.range_max_spin.valueChanged.connect(lambda v: self._handle_spin_change(v, False))

        # Smooth signals
        for btn in self.smooth_buttons.values():
            btn.clicked.connect(self._handle_smooth_preset)

        self.iter_spin.valueChanged.connect(self.iter_slider.setValue)
        self.iter_slider.valueChanged.connect(self.iter_spin.setValue)
        self.btn_smooth.clicked.connect(lambda: self.smoothRequested.emit(self.iter_spin.value()))

        # Connect solver selection signals
        self.solver_group.buttonClicked.connect(self._handle_solver_change)

        # Connect mesh and map selection signals
        self.mesh_combo.currentTextChanged.connect(self._handle_mesh_change)
        self.map_combo.currentTextChanged.connect(self._handle_map_change)
        self.paint_button.clicked.connect(self.maya_paint)

    def _handle_solver_change(self, button):
        """Handle solver type selection changes"""
        for solver_type, btn in self.solver_buttons.items():
            if btn == button:
                self.solverChanged.emit(solver_type)
                # Refresh mesh list based on solver type
                self.refresh_mesh_list(solver_type)
                break

    def _handle_mesh_change(self, mesh_name):
        """Handle mesh selection changes"""
        logger.debug(f"handler textChanged - Populating map combobox...{mesh_name}")
        if mesh_name:  # Only proceed if we have a valid mesh name
            self.mesh_combo._current_text = mesh_name
            self.populate_map_combobox()  # Refresh maps
        else:
            logger.warning("ComboBox Mesh doesn't emit mesh")

    def _handle_map_change(self, map_name):
        """Handle map selection changes"""
        self.mapChanged.emit(map_name)
        # Enable/disable paint button based on selection
        self.paint_button.setEnabled(bool(map_name))

    def refresh_mesh_list(self, solver_type: SolverType):
        """Refresh the mesh combo box based on solver type"""
        self.mesh_combo.clear()
        self.map_combo.clear()

        if solver_type == SolverType.NUCLEUS:
            # Implementation will be added to fetch nucleus nodes
            pass
        elif solver_type == SolverType.DEFORMER:
            # Implementation for deformers will be added later
            pass

    def refresh_map_list(self, mesh_name: str):
        """Refresh the map combo box based on selected mesh"""
        self.map_combo.clear()
        if not mesh_name:
            return

        # Implementation will be added to fetch maps for the selected mesh

    def set_active_mesh(self, mesh_name: str):
        """Set the active mesh in the combo box"""
        index = self.mesh_combo.findText(mesh_name)
        if index >= 0:
            self.mesh_combo.setCurrentIndex(index)

    def set_active_map(self, map_name: str):
        """Set the active map in the combo box"""
        index = self.map_combo.findText(map_name)
        if index >= 0:
            self.map_combo.setCurrentIndex(index)

    def _handle_flood(self, value: float):
        """Handle flood button clicks"""
        # Get current edit mode
        current_mode = self.get_current_mode()

        # Apply clamping if enabled
        if self.clamp_min_check.isChecked():
            value = max(value, self.clamp_min_spin.value())
        if self.clamp_max_check.isChecked():
            value = min(value, self.clamp_max_spin.value())

        self.set_flood_weight(value)

    def _validate_clamp_ranges(self):
        """Ensure min clamp is not greater than max clamp"""
        if self.clamp_min_spin.value() > self.clamp_max_spin.value():
            self.clamp_max_spin.setValue(self.clamp_min_spin.value())


    def get_clamp_range(self) -> tuple[Optional[float], Optional[float]]:
        """Get current clamp range values"""
        min_val = self.clamp_min_spin.value() if self.clamp_min_check.isChecked() else None
        max_val = self.clamp_max_spin.value() if self.clamp_max_check.isChecked() else None
        return min_val, max_val

    def get_current_mode(self) -> EditMode:
        """Get current edit mode"""
        for mode, btn in self.mode_buttons.items():
            if btn.isChecked():
                return mode
        return EditMode.REPLACE

    def _handle_selection_mode(self, button):
        """Handle selection mode changes"""
        mode = SelectionMode.RANGE if button == self.rb_range else SelectionMode.VALUE
        self.selectionModeChanged.emit(mode)

        # Update UI based on mode
        self.range_max_spin.setVisible(mode == SelectionMode.RANGE)
        self.range_slider.setVisible(mode == SelectionMode.RANGE)

    def _handle_range_change(self, min_val, max_val):
        """Handle range slider changes"""
        # Convert slider range (0-99) to value range
        value_range = self.config.max_value - self.config.min_value
        min_value = self.config.min_value + (min_val / 99.0) * value_range
        max_value = self.config.min_value + (max_val / 99.0) * value_range

        # Update spinboxes
        self.range_min_spin.setValue(min_value)
        self.range_max_spin.setValue(max_value)

        self.selectionRangeChanged.emit(min_value, max_value)

    def _handle_spin_change(self, value, is_min):
        """Handle changes to range spinboxes"""
        # Convert value to slider range
        value_range = self.config.max_value - self.config.min_value
        slider_value = ((value - self.config.min_value) / value_range) * 99.0

        # Update slider
        if is_min:
            self.range_slider.first_position = slider_value
        else:
            self.range_slider.second_position = slider_value

        self.range_slider.update()

    def _handle_smooth_preset(self):
        """Handle smooth preset button clicks"""
        iterations = self.sender().property("smoothValue")
        self.smoothRequested.emit(iterations)

    def populate_treecombobox(self):
        from ..sim_cmds.paint_wgt_utils import set_data_treecombo, nice_name, get_maya_sel
        sel = get_maya_sel()
        if sel:
            easy_sel = nice_name(sel[0])
        elif self.mesh_selected:
            easy_sel = nice_name(self.mesh_selected)
        else:
            easy_sel = None

        set_data_treecombo(self.mesh_combo, easy_sel)
        self.populate_map_combobox()

    def populate_map_combobox(self):
        from ..sim_cmds.paint_wgt_utils import get_nucx_maps_from_mesh

        logger.debug("Populating map combobox...")
        self.map_combo.clear()
        mesh = self.mesh_combo.get_current_text()

        logger.debug(f"Populating map - Current TreeCombo mesh: {mesh}")
        if not mesh:
            return

        maps, nucx_node = get_nucx_maps_from_mesh(mesh)
        logger.debug(f"Found maps: {maps}, nucx_node: {nucx_node}")

        self.map_combo.nucx_node = nucx_node

        # Sort maps by type
        map_categories = {
            1: [],  # Vertex maps
            2: [],  # Texture maps
            0: []  # Disabled maps
        }

        # Categorize maps
        for map_name in sorted(maps):
            map_type = get_nucx_map_type(nucx_node, f"{map_name}MapType")
            if map_type is not None:  # Check for valid map type
                map_categories[map_type].append(map_name)

        # Add maps with separators
        first_category = True
        for map_type, map_list in map_categories.items():
            if map_list:
                # Add separator between categories (except first)
                if not first_category:
                    self.map_combo.insertSeparator(self.map_combo.count())
                first_category = False

                # Add maps for this category
                for map_name in map_list:
                    self.map_combo.addMapItem(map_name, map_type)

    def maya_paint(self):
        from ..sim_cmds import paint_vtx_map
        mesh = self.mesh_combo.get_current_text()
        map = self.map_combo.currentText()
        nucx_node = self.map_combo.nucx_node
        solver = get_nucleus_solver(nucx_node)
        paint_vtx_map(map, mesh, solver)

    def smooth_flood(self, iteration: int = 1):
        smooth_pervtx_map(iteration)

    def get_combo_data(self) -> Tuple[str, str, str]:
        """
        return nucleus_node, map name, mesh_name
        """
        mesh = self.mesh_combo.get_current_text()
        map = self.map_combo.currentText()
        nucx_node = self.map_combo.nucx_node
        return nucx_node, map, mesh

    def set_flood_weight(self):
        from ..sim_cmds import get_vtx_map_data
        # gather elements set in ui
        nucx, _map, mesh = self.get_combo_data()
        # get the weightList
        weights = get_vtx_map_data(nucx, _map)



# Example usage
if __name__ == '__main__':
    app = QtWidgets.QApplication([])
    config = EditorConfig(min_value=-99.0, max_value=99.0, decimals=4)
    editor = VertexMapEditor(config)
    editor.show()
    app.exec()