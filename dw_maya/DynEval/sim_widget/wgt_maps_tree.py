from PySide6 import QtWidgets, QtCore, QtGui
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any
import maya.cmds as cmds
import maya.utils as mu

from dw_logger import get_logger

logger = get_logger()


class MapType(Enum):
    NONE = 0
    VERTEX = 1
    TEXTURE = 2


@dataclass
class MapInfo:
    """Enhanced data container for map information."""
    name: str
    mode: str
    mesh: Optional[str] = None
    solver: Optional[str] = None
    map_type: MapType = MapType.VERTEX
    value_range: tuple[float, float] = (0.0, 1.0)


class MapEditWidget(QtWidgets.QWidget):
    """Widget for editing map values and ranges."""

    value_changed = QtCore.Signal(MapInfo, float, float)  # Signal for range/value changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._current_map: Optional[MapInfo] = None

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Mode selection
        mode_group = QtWidgets.QGroupBox("Edit Mode")
        mode_layout = QtWidgets.QVBoxLayout()

        self.rb_range = QtWidgets.QRadioButton("Range")
        self.rb_value = QtWidgets.QRadioButton("Value")
        self.rb_range.setChecked(True)

        mode_layout.addWidget(self.rb_range)
        mode_layout.addWidget(self.rb_value)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)

        # Value widgets
        value_widget = QtWidgets.QWidget()
        value_layout = QtWidgets.QGridLayout(value_widget)

        self.min_label = QtWidgets.QLabel("Min:")
        self.max_label = QtWidgets.QLabel("Max:")
        self.min_value = QtWidgets.QDoubleSpinBox()
        self.max_value = QtWidgets.QDoubleSpinBox()

        # Configure spinboxes
        for spinbox in (self.min_value, self.max_value):
            spinbox.setRange(0.0, 1.0)
            spinbox.setSingleStep(0.1)
            spinbox.setDecimals(3)

        value_layout.addWidget(self.min_label, 0, 0)
        value_layout.addWidget(self.min_value, 0, 1)
        value_layout.addWidget(self.max_label, 1, 0)
        value_layout.addWidget(self.max_value, 1, 1)

        layout.addWidget(value_widget)

        # Quick value buttons
        quick_values = QtWidgets.QGroupBox("Quick Values")
        quick_layout = QtWidgets.QHBoxLayout()

        self.btn_zero = QtWidgets.QPushButton("0")
        self.btn_half = QtWidgets.QPushButton("0.5")
        self.btn_one = QtWidgets.QPushButton("1")

        quick_layout.addWidget(self.btn_zero)
        quick_layout.addWidget(self.btn_half)
        quick_layout.addWidget(self.btn_one)
        quick_values.setLayout(quick_layout)

        layout.addWidget(quick_values)

        # Connect signals
        self._connect_signals()

    def _connect_signals(self):
        """Connect widget signals."""
        self.rb_range.toggled.connect(self._update_mode)
        self.rb_value.toggled.connect(self._update_mode)
        self.min_value.valueChanged.connect(self._on_value_changed)
        self.max_value.valueChanged.connect(self._on_value_changed)

        # Quick value buttons
        self.btn_zero.clicked.connect(lambda: self._set_quick_value(0.0))
        self.btn_half.clicked.connect(lambda: self._set_quick_value(0.5))
        self.btn_one.clicked.connect(lambda: self._set_quick_value(1.0))

    def set_map(self, map_info: MapInfo):
        """Set the current map being edited."""
        self._current_map = map_info
        if map_info:
            self.min_value.setValue(map_info.value_range[0])
            self.max_value.setValue(map_info.value_range[1])

    def _update_mode(self):
        """Update UI based on selected mode."""
        is_range = self.rb_range.isChecked()
        self.max_label.setVisible(is_range)
        self.max_value.setVisible(is_range)

    def _on_value_changed(self):
        """Handle value changes."""
        if self._current_map:
            min_val = self.min_value.value()
            max_val = self.max_value.value() if self.rb_range.isChecked() else min_val
            self.value_changed.emit(self._current_map, min_val, max_val)

    def _set_quick_value(self, value: float):
        """Set quick value for both min and max."""
        self.min_value.setValue(value)
        if self.rb_range.isChecked():
            self.max_value.setValue(value)


class MapTreeWidget(QtWidgets.QWidget):
    """Enhanced widget for displaying and managing vertex maps."""

    map_selected = QtCore.Signal(MapInfo)
    map_edited = QtCore.Signal(MapInfo, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.node = None
        self._setup_ui()

    def _setup_ui(self):
        """Initialize UI components."""
        main_layout = QtWidgets.QHBoxLayout(self)

        # Left side: Tree and controls
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)

        # Search and filter
        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText("Filter maps...")
        left_layout.addWidget(self.search_box)

        # Map type filter
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItems(["All Types", "Vertex", "Texture"])
        left_layout.addWidget(self.type_combo)

        # Tree widget
        self.maps_tree = QtWidgets.QTreeWidget()
        self.maps_tree.setHeaderLabels(["Map", "Type"])
        self.maps_tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        left_layout.addWidget(self.maps_tree)

        # Quick actions
        action_layout = QtWidgets.QHBoxLayout()
        self.paint_btn = QtWidgets.QPushButton("Paint")
        self.reset_btn = QtWidgets.QPushButton("Reset")
        action_layout.addWidget(self.paint_btn)
        action_layout.addWidget(self.reset_btn)
        left_layout.addLayout(action_layout)

        main_layout.addWidget(left_widget)

        # Right side: Map editor
        self.map_editor = MapEditWidget()
        main_layout.addWidget(self.map_editor)

        # Connect signals
        self._connect_signals()

    def set_node(self, node):
        """Set the current simulation node and update cache list."""
        self.node = node
        self.populate_maps()

    def _connect_signals(self):
        """Connect widget signals."""
        self.search_box.textChanged.connect(self._filter_maps)
        self.type_combo.currentIndexChanged.connect(self._filter_maps)
        self.maps_tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.paint_btn.clicked.connect(self._on_paint_clicked)
        self.reset_btn.clicked.connect(self._on_reset_clicked)
        self.map_editor.value_changed.connect(self._on_map_edited)

    def _on_map_edited(self, map_info: MapInfo, min_val: float, max_val: float):
        """Handle map value edits."""
        try:
            if self.node and map_info:
                values = self._get_vertex_count() * [min_val]
                self._set_map_values(map_info.name, values)
                self.map_edited.emit(map_info, min_val, max_val)
        except Exception as e:
            logger.error(f"Failed to edit map values: {e}")

    def _get_vertex_count(self) -> int:
        """Get vertex count of current mesh."""
        if self.node and self.node.mesh_transform:
            return cmds.polyEvaluate(self.node.mesh_transform, vertex=True)
        return 0

    def _set_map_values(self, map_name: str, values: List[float]):
        """Set vertex map values."""
        from ..sim_cmds import vtx_map_management
        vtx_map_management.set_vtx_map_data(
            self.node.node,
            f"{map_name}PerVertex",
            values,
            refresh=True
        )

    def populate_maps(self):
        """Populate tree with maps from current node."""
        self.maps_tree.clear()
        if not self.node or self.node.node_type not in ['nCloth', 'nRigid']:
            return

        try:
            for map_name, map_mode in zip(self.node.get_maps(), self.node.get_maps_mode()):
                item = QtWidgets.QTreeWidgetItem(self.maps_tree)
                item.setText(0, map_name)
                item.setText(1, map_mode)

                # Store map info
                map_info = MapInfo(
                    name=map_name,
                    mode=map_mode,
                    mesh=self.node.mesh_transform,
                    solver=self.node.solver_name
                )
                item.setData(0, QtCore.Qt.UserRole, map_info)

        except Exception as e:
            logger.error(f"Failed to populate maps: {e}")

    def _filter_maps(self, filter_text: str = ""):
        """Filter visible maps based on search text and type."""
        filter_text = self.search_box.text().lower()
        type_filter = self.type_combo.currentText()

        for i in range(self.maps_tree.topLevelItemCount()):
            item = self.maps_tree.topLevelItem(i)
            map_info = item.data(0, QtCore.Qt.UserRole)

            # Check type filter
            show_item = True
            if type_filter != "All Types":
                show_item = (
                        (type_filter == "Vertex" and "PerVertex" in map_info.mode) or
                        (type_filter == "Texture" and "Map" in map_info.mode)
                )

            # Check text filter
            if show_item and filter_text:
                show_item = filter_text in map_info.name.lower()

            item.setHidden(not show_item)

    def _on_selection_changed(self):
        """Handle map selection change."""
        items = self.maps_tree.selectedItems()
        if not items:
            return

        map_info = items[0].data(0, QtCore.Qt.UserRole)
        self.map_editor.set_map(map_info)
        self.map_selected.emit(map_info)

        # Update button states
        self.paint_btn.setEnabled("PerVertex" in map_info.mode)
        self.reset_btn.setEnabled(True)

    def _on_paint_clicked(self):
        """Handle paint button click."""
        items = self.maps_tree.selectedItems()
        if not items:
            return

        map_info = items[0].data(0, QtCore.Qt.UserRole)
        if "PerVertex" not in map_info.mode:
            return

        try:
            from ..sim_cmds import vtx_map_management
            mu.executeInMainThreadWithResult(
                vtx_map_management.paint_vtx_map,
                f"{self.node.node}.{map_info.name}",
                map_info.mesh,
                map_info.solver
            )
        except Exception as e:
            logger.error(f"Failed to start paint tool: {e}")

    def _on_reset_clicked(self):
        """Handle reset button click."""
        items = self.maps_tree.selectedItems()
        if not items:
            return

        try:
            for item in items:
                map_info = item.data(0, QtCore.Qt.UserRole)
                values = [0.0] * self._get_vertex_count()
                self._set_map_values(map_info.name, values)
        except Exception as e:
            logger.error(f"Failed to reset map values: {e}")