"""
Map Tree Widget with DataHub Integration

Displays and manages vertex maps for simulation nodes.
Publishes map selection and subscribes to node selection.
"""

from PySide6 import QtWidgets, QtCore, QtGui
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any
import maya.cmds as cmds

from dw_logger import get_logger

# Local imports
from ..hub_keys import HubKeys
from .wgt_base import DynEvalWidget
from ..sim_cmds import vtx_map_management

logger = get_logger()


class MapType(Enum):
    NONE = 0
    PerVertex = 1
    Texture = 2


@dataclass
class MapInfo:
    """Data container for map information."""
    name: str
    mode: int
    mesh: Optional[str] = None
    solver: Optional[str] = None
    map_type: MapType = MapType.PerVertex
    value_range: tuple = (0.0, 1.0)
    is_edited: bool = False
    per_vertex_weights: list = None


class MapTreeModel(QtGui.QStandardItemModel):
    """Model for map management."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(["Map Name", "Type"])


class MapNameItem(QtGui.QStandardItem):
    """Item representing a map in the tree."""

    def __init__(self, map_info: MapInfo):
        super().__init__(map_info.name)
        self.map_info = map_info
        self.setEditable(False)
        self.setData(map_info, QtCore.Qt.UserRole)


class MapTypeDelegate(QtWidgets.QStyledItemDelegate):
    """Delegate for the map type column with combobox."""

    typeChanged = QtCore.Signal(object, object)  # MapInfo, MapType

    TYPE_COLORS = {
        MapType.NONE: QtGui.QColor(175, 175, 175),
        MapType.PerVertex: QtGui.QColor(0, 255, 0),
        MapType.Texture: QtGui.QColor(0, 125, 255)
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_editor = None

    def createEditor(self, parent, option, index):
        if not index.isValid() or index.column() != 1:
            return None

        editor = QtWidgets.QComboBox(parent)
        editor.addItems([t.name for t in MapType])
        editor.setFrame(False)
        editor.activated.connect(
            lambda idx: self._handle_type_change(index, MapType(idx), editor)
        )

        self._current_editor = editor
        return editor

    def setEditorData(self, editor, index):
        if not isinstance(editor, QtWidgets.QComboBox):
            return

        map_info = self._get_map_info(index)
        if map_info:
            editor.setCurrentIndex(map_info.map_type.value)
            QtCore.QTimer.singleShot(0, editor.showPopup)

    def setModelData(self, editor, model, index):
        if not isinstance(editor, QtWidgets.QComboBox):
            return

        value = editor.currentText()
        model.setData(index, value, QtCore.Qt.DisplayRole)

        map_info = self._get_map_info(index)
        if map_info:
            map_info.map_type = MapType(editor.currentIndex())

    def paint(self, painter, option, index):
        if not index.isValid():
            return

        painter.save()

        map_info = self._get_map_info(index)
        if map_info:
            color = self.TYPE_COLORS.get(map_info.map_type, self.TYPE_COLORS[MapType.NONE])
            text = map_info.map_type.name
        else:
            color = self.TYPE_COLORS[MapType.NONE]
            text = MapType.NONE.name

        # Handle states
        if option.state & QtWidgets.QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
            painter.setPen(option.palette.highlightedText().color())
        elif option.state & QtWidgets.QStyle.State_MouseOver:
            painter.fillRect(option.rect, QtGui.QColor(60, 60, 60, 100))
            painter.setPen(color)
        else:
            painter.setPen(color)

        text_rect = option.rect.adjusted(4, 0, -4, 0)
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter, text)
        painter.restore()

    def _get_map_info(self, index) -> Optional[MapInfo]:
        """Get MapInfo from the name column of the same row."""
        name_item = index.model().item(index.row(), 0)
        return name_item.data(QtCore.Qt.UserRole) if name_item else None

    def _handle_type_change(self, index, new_type: MapType, editor):
        """Handle type changes."""
        try:
            map_info = self._get_map_info(index)
            if map_info:
                map_info.map_type = new_type
                index.model().setData(index, new_type.name, QtCore.Qt.DisplayRole)
                self.typeChanged.emit(map_info, new_type)
                index.model().dataChanged.emit(index, index)
                QtCore.QTimer.singleShot(10, lambda: self.closeEditor.emit(editor))
        except Exception as e:
            logger.error(f"Error handling type change: {e}")

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class MapTreeWidget(DynEvalWidget):
    """
    Widget for managing vertex maps.

    Subscribes to:
        - HubKeys.SELECTED_ITEM: Updates map list when selection changes
        - HubKeys.PAINT_ACTIVE: Reacts to paint tool state

    Publishes:
        - HubKeys.MAP_SELECTED: When a map is selected
        - HubKeys.MAP_LIST: Current list of maps
    """

    # Qt Signals
    mapSelected = QtCore.Signal(object)  # MapInfo
    mapTypeChanged = QtCore.Signal(object, object)  # MapInfo, MapType
    mapDoubleClicked = QtCore.Signal(object)  # MapInfo

    def __init__(self, parent=None):
        super().__init__(parent)

        # Current state
        self._current_node = None
        self._node_name = None
        self._mesh_name = None
        self._solver = None

        # Setup
        self._setup_ui()
        self._connect_signals()
        self._setup_hub_subscriptions()

    def _setup_ui(self):
        """Initialize UI."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Filter controls
        filter_layout = QtWidgets.QHBoxLayout()

        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText("Filter maps...")
        self.search_box.setClearButtonEnabled(True)

        self.type_filter = QtWidgets.QComboBox()
        self.type_filter.addItems(["All Types"] + [t.name for t in MapType])
        self.type_filter.setFixedWidth(100)

        filter_layout.addWidget(self.search_box)
        filter_layout.addWidget(self.type_filter)
        layout.addLayout(filter_layout)

        # Tree View
        self.tree_view = QtWidgets.QTreeView()
        self.tree_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree_view.setAllColumnsShowFocus(True)
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setMouseTracking(True)

        # Styling
        self.tree_view.setStyleSheet("""
            QTreeView {
                outline: 0;
            }
            QTreeView::item {
                min-height: 24px;
                padding: 2px;
            }
            QTreeView::item:hover {
                background: rgba(60, 60, 60, 100);
            }
            QTreeView::item:selected {
                background: rgba(80, 80, 80, 150);
            }
        """)

        # Model and delegate
        self.model = MapTreeModel()
        self.tree_view.setModel(self.model)

        self.type_delegate = MapTypeDelegate()
        self.tree_view.setItemDelegateForColumn(1, self.type_delegate)

        # Configure columns
        header = self.tree_view.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        header.setStretchLastSection(False)
        self.tree_view.setColumnWidth(0, 180)
        self.tree_view.setColumnWidth(1, 80)

        layout.addWidget(self.tree_view)

        # Action buttons
        action_layout = QtWidgets.QHBoxLayout()

        self.paint_btn = QtWidgets.QPushButton("Paint")
        self.paint_btn.setToolTip("Open Maya paint tool for selected map")
        self.paint_btn.setEnabled(False)

        self.reset_btn = QtWidgets.QPushButton("Reset")
        self.reset_btn.setToolTip("Reset map to default values")
        self.reset_btn.setEnabled(False)

        action_layout.addWidget(self.paint_btn)
        action_layout.addWidget(self.reset_btn)
        action_layout.addStretch()

        layout.addLayout(action_layout)

    def _connect_signals(self):
        """Connect widget signals."""
        self.search_box.textChanged.connect(self._filter_maps)
        self.type_filter.currentIndexChanged.connect(self._filter_maps)

        self.tree_view.clicked.connect(self._handle_click)
        self.tree_view.doubleClicked.connect(self._handle_double_click)
        self.tree_view.selectionModel().selectionChanged.connect(self._handle_selection)

        self.type_delegate.typeChanged.connect(self._on_type_changed)

        self.paint_btn.clicked.connect(self._paint_selected)
        self.reset_btn.clicked.connect(self._reset_selected)

    def _setup_hub_subscriptions(self):
        """Setup DataHub subscriptions."""
        self.hub_subscribe(HubKeys.SELECTED_ITEM, self._on_node_selected)
        self.hub_subscribe(HubKeys.PAINT_ACTIVE, self._on_paint_state_changed)

    # ========================================================================
    # HUB CALLBACKS
    # ========================================================================

    def _on_node_selected(self, old_value, new_value):
        """Hub callback: node selection changed."""
        if new_value is not None:
            self.set_current_node(new_value)

    def _on_paint_state_changed(self, old_value, new_value):
        """Hub callback: paint tool state changed."""
        # Could update UI to reflect paint state
        pass

    # ========================================================================
    # PUBLIC METHODS
    # ========================================================================

    def set_current_node(self, item):
        """Set current node and populate maps."""
        self._current_node = item
        self._node_name = getattr(item, 'node', None)
        self._mesh_name = getattr(item, 'mesh_transform', None)
        self._solver = self._get_solver(self._node_name) if self._node_name else None

        self.populate_maps()

    def populate_maps(self):
        """Update the tree with map data."""
        self.model.clear()
        self.model.setHorizontalHeaderLabels(["Map Name", "Type"])

        if not self._current_node:
            return

        try:
            maps_info = self._get_maps_info()

            for map_info in maps_info:
                name_item = MapNameItem(map_info)
                type_item = QtGui.QStandardItem(map_info.map_type.name)
                type_item.setData(map_info.map_type.value, QtCore.Qt.UserRole)
                self.model.appendRow([name_item, type_item])

            # Publish map list to hub
            self.hub_publish(HubKeys.MAP_LIST, maps_info)

            # Clear filters
            self.search_box.clear()
            self.type_filter.setCurrentIndex(0)

        except Exception as e:
            logger.error(f"Failed to populate maps: {e}")

    def get_selected_maps(self) -> List[MapInfo]:
        """Get currently selected maps."""
        maps = []
        for index in self.tree_view.selectedIndexes():
            if index.column() == 0:
                item = self.model.itemFromIndex(index)
                if item:
                    map_info = item.data(QtCore.Qt.UserRole)
                    if map_info:
                        maps.append(map_info)
        return maps

    def clear(self):
        """Clear all maps."""
        self.model.clear()
        self.model.setHorizontalHeaderLabels(["Map Name", "Type"])
        self._current_node = None
        self.search_box.clear()
        self.type_filter.setCurrentIndex(0)

    # ========================================================================
    # PRIVATE METHODS
    # ========================================================================

    def _get_maps(self) -> List[str]:
        """Get list of map names."""
        if not self._node_name:
            return []
        return vtx_map_management.get_vtx_maps(self._node_name)

    def _get_maps_info(self) -> List[MapInfo]:
        """Get detailed map information."""
        result = []

        for map_name in self._get_maps():
            try:
                value = vtx_map_management.get_vtx_map_type(
                    self._node_name, f'{map_name}MapType'
                )

                map_info = MapInfo(
                    name=map_name,
                    mode=value,
                    mesh=self._mesh_name,
                    solver=self._solver,
                    map_type=MapType(value) if value is not None else MapType.NONE
                )

                # Check if map has been painted
                vtx_data = vtx_map_management.get_vtx_map_data(
                    self._node_name, f"{map_name}PerVertex"
                )
                if vtx_data and not all(v == 1.0 for v in vtx_data):
                    map_info.is_edited = True
                    map_info.per_vertex_weights = vtx_data

                result.append(map_info)

            except Exception as e:
                logger.warning(f"Failed to get info for map {map_name}: {e}")

        result.sort(key=lambda x: x.name)
        return result

    def _get_solver(self, node_name: str) -> Optional[str]:
        """Get connected solver."""
        try:
            connections = cmds.listConnections(node_name, type="nucleus") or []
            return connections[0].split(':')[-1] if connections else None
        except Exception:
            return None

    # ========================================================================
    # SELECTION & INTERACTION
    # ========================================================================

    def _handle_click(self, index: QtCore.QModelIndex):
        """Handle click - open combobox for type column."""
        if index.column() == 1:
            self.tree_view.edit(index)

    def _handle_double_click(self, index: QtCore.QModelIndex):
        """Handle double-click to paint map."""
        try:
            item_index = self.model.index(index.row(), 0, index.parent())
            item = self.model.itemFromIndex(item_index)

            if isinstance(item, MapNameItem):
                map_info = item.map_info
                self._paint_map(map_info)
                self.mapDoubleClicked.emit(map_info)

        except Exception as e:
            logger.error(f"Double-click paint failed: {e}")

    def _handle_selection(self):
        """Handle selection changes."""
        selected_maps = self.get_selected_maps()

        # Update button states
        has_selection = bool(selected_maps)
        self.paint_btn.setEnabled(has_selection)
        self.reset_btn.setEnabled(has_selection)

        # Publish and emit first selected
        if selected_maps:
            map_info = selected_maps[0]
            self.hub_publish(HubKeys.MAP_SELECTED, map_info)
            self.mapSelected.emit(map_info)

    def _on_type_changed(self, map_info: MapInfo, new_type: MapType):
        """Handle map type change from delegate."""
        try:
            if self._node_name:
                vtx_map_management.set_vtx_map_type(
                    self._node_name,
                    f"{map_info.name}MapType",
                    new_type.value
                )
            self.mapTypeChanged.emit(map_info, new_type)
        except Exception as e:
            logger.error(f"Failed to change map type: {e}")

    # ========================================================================
    # ACTIONS
    # ========================================================================

    def _paint_selected(self):
        """Paint the first selected map."""
        maps = self.get_selected_maps()
        if maps:
            self._paint_map(maps[0])

    def _paint_map(self, map_info: MapInfo):
        """Launch Maya paint tool for map."""
        if not self._current_node:
            return

        node_type = getattr(self._current_node, 'node_type', None)

        if node_type in ['nCloth', 'nRigid']:
            attr_path = f"{self._node_name}.{map_info.name}"
            if map_info.map_type == MapType.PerVertex:
                attr_path += "PerVertex"

            vtx_map_management.paint_vtx_map(
                attr_path,
                self._mesh_name,
                self._solver
            )

            # Publish paint context
            self.hub_publish(HubKeys.PAINT_ACTIVE, True)
            self.hub_publish(HubKeys.PAINT_CONTEXT, (self._node_name, map_info.name, self._mesh_name))

    def _reset_selected(self):
        """Reset selected maps to default values."""
        maps = self.get_selected_maps()
        if not maps:
            return

        reply = QtWidgets.QMessageBox.question(
            self,
            "Reset Maps",
            f"Reset {len(maps)} map(s) to default values?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )

        if reply == QtWidgets.QMessageBox.Yes:
            for map_info in maps:
                try:
                    # Get vertex count
                    vtx_count = cmds.polyEvaluate(self._mesh_name, vertex=True)
                    default_values = [1.0] * vtx_count

                    vtx_map_management.set_vtx_map_data(
                        self._node_name,
                        f"{map_info.name}PerVertex",
                        default_values
                    )
                except Exception as e:
                    logger.error(f"Failed to reset map {map_info.name}: {e}")

            self.populate_maps()

    # ========================================================================
    # FILTERING
    # ========================================================================

    def _filter_maps(self):
        """Filter maps based on search and type filter."""
        search_text = self.search_box.text().lower()
        type_index = self.type_filter.currentIndex()
        type_filter = MapType(type_index - 1) if type_index > 0 else None

        for row in range(self.model.rowCount()):
            item = self.model.item(row, 0)
            if not item:
                continue

            map_info = item.data(QtCore.Qt.UserRole)
            if not map_info:
                continue

            should_show = True

            if search_text:
                should_show = search_text in map_info.name.lower()

            if type_filter is not None and should_show:
                should_show = map_info.map_type == type_filter

            self.tree_view.setRowHidden(row, QtCore.QModelIndex(), not should_show)

    # CLEANUP - handled by DynEvalWidget base class