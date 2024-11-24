from PySide6 import QtWidgets, QtCore, QtGui
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any
import maya.cmds as cmds
import maya.utils as mu
from dw_maya.DynEval.sim_cmds import vtx_map_management
from dw_logger import get_logger

logger = get_logger()


class MapType(Enum):
    Null = 0
    PerVertex = 1
    Texture = 2

@dataclass
class MapInfo:
    """Enhanced data container for map information."""
    name: str
    mode: int
    mesh: Optional[str] = None
    solver: Optional[str] = None
    map_type: MapType = MapType.PerVertex
    value_range: tuple[float, float] = (0.0, 1.0)
    is_edited: bool = False


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

        # Store the map info for access
        self.setData(map_info, QtCore.Qt.UserRole)


class MapTypeDelegate(QtWidgets.QStyledItemDelegate):
    """Delegate for the map type column with combobox."""

    typeChanged = QtCore.Signal(MapInfo, MapType)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.type_colors = {
            MapType.Null: QtGui.QColor(175, 175, 175),
            MapType.PerVertex: QtGui.QColor(0, 255, 0),
            MapType.Texture: QtGui.QColor(0, 125, 255)
        }

    def createEditor(self, parent, option, index):
        if not index.isValid() or index.column() != 1:
            return None

        editor = QtWidgets.QComboBox(parent)
        editor.addItems([t.name for t in MapType])
        editor.currentIndexChanged.connect(
            lambda idx: self._handle_type_change(index, MapType(idx))
        )
        return editor

    def setEditorData(self, editor, index):
        if not isinstance(editor, QtWidgets.QComboBox):
            return

        map_info = self._get_map_info(index)
        if map_info:
            editor.setCurrentIndex(map_info.map_type.value)

    def paint(self, painter, option, index):
        if not index.isValid():
            return

        painter.save()

        # Get map info and set color
        map_info = self._get_map_info(index)
        if map_info:
            color = self.type_colors.get(map_info.map_type, self.type_colors[MapType.Null])
            painter.setPen(color)

        # Draw the text
        text = index.data(QtCore.Qt.DisplayRole)
        text_rect = option.rect.adjusted(4, 0, -4, 0)  # Add some padding
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter, text)

        painter.restore()

    def _get_map_info(self, index) -> Optional[MapInfo]:
        """Get MapInfo from the name column of the same row."""
        name_item = index.model().item(index.row(), 0)
        return name_item.data(QtCore.Qt.UserRole) if name_item else None

    def _handle_type_change(self, index, new_type: MapType):
        """Handle map type changes."""
        map_info = self._get_map_info(index)
        if map_info:
            map_info.map_type = new_type
            self.typeChanged.emit(map_info, new_type)
            # Force repaint
            index.model().dataChanged.emit(index, index)


class MapTreeWidget(QtWidgets.QWidget):
    """Enhanced widget for map management using model/view architecture."""

    mapSelected = QtCore.Signal(MapInfo)
    mapTypeChanged = QtCore.Signal(MapInfo, MapType)
    itemDoubleClicked = QtCore.Signal(MapNameItem)


    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_node = None
        self.name = None
        self.mesh_name = None
        self.solver = None
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        # Filter controls
        filter_layout = QtWidgets.QHBoxLayout()
        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText("Filter maps...")
        self.type_filter = QtWidgets.QComboBox()
        self.type_filter.addItems(["All Types"] + [t.name for t in MapType])

        filter_layout.addWidget(self.search_box)
        filter_layout.addWidget(self.type_filter)
        layout.addLayout(filter_layout)

        # Tree View
        self.tree_view = QtWidgets.QTreeView()
        self.tree_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree_view.setAllColumnsShowFocus(True)
        self.tree_view.setAlternatingRowColors(True)


        # Set up model and delegate
        self.model = MapTreeModel()
        self.tree_view.setModel(self.model)

        self.type_delegate = MapTypeDelegate()
        self.tree_view.setItemDelegateForColumn(1, self.type_delegate)

        # Configure columns
        header = self.tree_view.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        header.setStretchLastSection(False)
        self.tree_view.setColumnWidth(1, 120)

        self.model.setHorizontalHeaderLabels(["Map Name", "Type"])

        layout.addWidget(self.tree_view)

    def _connect_signals(self):
        self.search_box.textChanged.connect(self._filter_maps)
        self.type_filter.currentIndexChanged.connect(self._filter_maps)
        # self.tree_view.selectionModel().selectionChanged.connect(self._handle_selection)
        self.type_delegate.typeChanged.connect(self.mapTypeChanged)
        self.doubleClicked.connect(self._handle_double_click)

    def _handle_double_click(self, index: QtCore.QModelIndex):
        """Handle double-click events on tree items."""
        try:
            # Get the item from the first column (where the simulation item is stored)
            item_index = self.tree_view.model().index(index.row(), 0, index.parent())
            item = self.tree_view.model().itemFromIndex(item_index)

            if isinstance(item, MapNameItem):
                self.itemDoubleClicked.emit(item)

        except Exception as e:
            logger.error(f"Double-click handling failed: {e}")

    def set_current_node(self, item):
        self.current_node = item
        self.name = item.node
        self.mesh_name = item.mesh_transform
        self.solver = self._get_solver(self.name)
        self.populate_maps()

    def get_maps(self):
        '''
        :return: <<list>> of string
        '''
        return vtx_map_management.get_vtx_maps(self.current_node.node)

    def get_maps_info(self):
        '''
        :return: <<list>> of integer
        '''
        result_MAPS = []
        for map_name in self.get_maps():
            value = vtx_map_management.get_vtx_map_type(self.current_node.node,
                                                    f'{map_name}MapType')

            map_info = MapInfo(map_name,
                               value,
                               map_type=MapType(value),
                               solver=self.solver)
            result_MAPS.append(map_info)
        return result_MAPS


    def populate_maps(self):
        """Update the tree with new map data."""
        self.model.clear()

        for map_info in self.get_maps_info():
            name_item = MapNameItem(map_info)
            type_item = QtGui.QStandardItem(map_info.map_type.name)
            type_item.setData(map_info.map_type.value, QtCore.Qt.UserRole)

            self.model.appendRow([name_item, type_item])

        # Clear filters
        self.search_box.clear()
        self.type_filter.setCurrentIndex(0)

    def _filter_maps(self):
        """Filter maps based on search text and type."""
        search_text = self.search_box.text().lower()
        type_filter = MapType[self.type_filter.currentText()] if self.type_filter.currentIndex() > 0 else None

        for row in range(self.model.rowCount()):
            item = self.model.item(row, 0)
            map_info = item.data(QtCore.Qt.UserRole)

            should_show = True
            if search_text:
                should_show = search_text in map_info.name.lower()
            if type_filter and should_show:
                should_show = map_info.map_type == type_filter

            self.tree_view.setRowHidden(row, QtCore.QModelIndex(), not should_show)

    def get_selected_maps(self) -> List[MapInfo]:
        """Get currently selected maps."""
        maps = []
        for index in self.tree_view.selectedIndexes():
            if index.column() == 0:  # Only process name column
                item = self.model.itemFromIndex(index)
                map_info = item.data(QtCore.Qt.UserRole)
                if map_info:
                    maps.append(map_info)
        return maps

    def clear(self):
        """Clear all maps and reset the widget state."""
        self.model.clear()
        self.search_box.clear()
        self.type_filter.setCurrentIndex(0)

    def paint_map(self):
        """
        trigger the maya paint tool on selected cloth mesh
        (will keep component if some are selected)
        """
        map_item = self.maps_tree.currentItem()
        if self.node.node_type in ['nCloth', 'nRigid']:
            vtx_map_management.paint_vtx_map(map_item.map_to_paint,
                                             map_item.cloth_mesh,
                                             self.solver)

    def _get_solver(self, node_name: str) -> str:
        """Get connected solver with error handling."""
        try:
            connections = cmds.listConnections(node_name, type="nucleus") or []
            return connections[0].split(':')[-1] if connections else ''
        except Exception as e:
            return None
