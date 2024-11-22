from PySide6 import QtCore, QtGui, QtWidgets
from typing import Optional, Dict, Any
from ..dendrology.nucleus_leaf.base_standarditem import BaseSimulationItem
from dw_maya.DynEval.dendrology.tree_togglebutton import ToggleButtonDelegate
from dw_logger import get_logger

logger = get_logger()


class SimulationTreeModel(QtGui.QStandardItemModel):
    """Custom model for simulation nodes with toggle state handling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHorizontalHeaderLabels(["Dynamic Items", "State"])
        self._toggle_column = 1  # Column for toggle buttons

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole) -> Any:
        """Override data method to handle toggle state."""
        if not index.isValid():
            return None

        # Handle toggle state for column 1
        if index.column() == 1:
            if role == QtCore.Qt.UserRole + 3:  # Toggle state
                return super().data(index, role) or False

        return super().data(index, role)

    def setData(self, index: QtCore.QModelIndex, value: Any, role: int = QtCore.Qt.EditRole) -> bool:
        """Override setData to handle toggle state changes."""
        if not index.isValid():
            return False

        if index.column() == 1 and role == QtCore.Qt.UserRole + 3:
            # Update toggle state
            success = super().setData(index, value, role)
            if success:
                self.dataChanged.emit(index, index, [role])
            return success

        return super().setData(index, value, role)

    def itemFromIndex(self, index: QtCore.QModelIndex) -> Optional[QtGui.QStandardItem]:
        """Get item from index, handling parent-child relationships."""
        if not index.isValid():
            return None

        if index.parent().isValid():
            # Get parent item first
            parent_item = self.itemFromIndex(index.parent())
            if parent_item:
                # Return child item at the given row
                return parent_item.child(index.row(), index.column())
        else:
            # Root level item
            return self.item(index.row(), index.column())


class SimulationTreeView(QtWidgets.QTreeView):
    """Custom tree view for simulation nodes with toggle support."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Setup delegate
        self.toggle_delegate = ToggleButtonDelegate(self)
        self.setItemDelegateForColumn(1, self.toggle_delegate)

        self.setColumnWidth(0, 200)
        self.setColumnWidth(1, 32)
        # self.setFirstColumnSpanned(0, QtCore.QModelIndex(), True)

        # Configure view
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.setAnimated(True)
        self.setIndentation(20)
        self.setSortingEnabled(True)

        # Optional: Prevent column resize
        # header = self.header()
        # header.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)

        self.setModel(SimulationTreeModel())

        # Connect toggle signal to handle batch operations
        self.toggle_delegate.toggled.connect(self._handle_toggle)

    def clear(self):
        self.setModel(SimulationTreeModel())

    def _handle_toggle(self, state_index: QtCore.QModelIndex, new_state: bool):
        """Handle toggle events with support for batch operations."""
        try:
            # Get the corresponding item from the first column
            if state_index.parent().isValid():
                parent_index = state_index.parent()
                item_index = self.model().index(state_index.row(), 0, parent_index)
            else:
                item_index = self.model().index(state_index.row(), 0)

            item = self.model().itemFromIndex(item_index)

            if not isinstance(item, BaseSimulationItem):
                logger.warning(f"Toggle attempted on non-simulation item: {type(item)}")
                return

            # Update the state
            logger.debug(f"Toggling {item.node_type} state - Node: {item.node}, State: {new_state}")
            item.set_state(new_state)

            # Update the model
            self.model().setData(state_index, new_state, QtCore.Qt.UserRole + 3)

        except Exception as e:
            logger.error(f"Toggle operation failed: {e}")
