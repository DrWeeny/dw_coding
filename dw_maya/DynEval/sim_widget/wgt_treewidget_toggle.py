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
        self._toggle_column = 1  # Column for toggle buttons

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole) -> Any:
        """Override data method to handle toggle state."""
        if not index.isValid():
            return None

        if role == QtCore.Qt.UserRole + 3:  # Toggle state
            return super().data(index, role) or False

        return super().data(index, role)

    def setData(self, index: QtCore.QModelIndex, value: Any, role: int = QtCore.Qt.EditRole) -> bool:
        """Override setData to handle toggle state changes."""
        if not index.isValid():
            return False

        if role == QtCore.Qt.UserRole + 3:
            # Update toggle state
            success = super().setData(index, value, role)
            if success:
                # Update Maya node state if needed
                item = self.itemFromIndex(index)
                if hasattr(item, 'set_state'):
                    try:
                        item.set_state(value)
                    except Exception as e:
                        logger.error(f"Failed to update Maya node state: {e}")
                        return False
                self.dataChanged.emit(index, index, [role])
            return success

        return super().setData(index, value, role)


class SimulationTreeView(QtWidgets.QTreeView):
    """Custom tree view for simulation nodes with toggle support."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Setup delegate
        self.toggle_delegate = ToggleButtonDelegate(self)
        self.setItemDelegateForColumn(1, self.toggle_delegate)

        # Configure view
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setAlternatingRowColors(True)
        self.setAnimated(True)
        self.setIndentation(20)
        self.setSortingEnabled(True)

        self.setModel(SimulationTreeModel())

        # Connect toggle signal to handle batch operations
        self.toggle_delegate.toggled.connect(self._handle_toggle)

    def _handle_toggle(self, index: QtCore.QModelIndex, state: bool):
        """Handle toggle events with support for batch operations."""
        selected_indexes = self.selectedIndexes()

        # If multiple items are selected, toggle them all
        if len(selected_indexes) > 1 and index in selected_indexes:
            items = [
                self.model().itemFromIndex(idx)
                for idx in selected_indexes
                if isinstance(self.model().itemFromIndex(idx), BaseSimulationItem)
            ]
            # Use the first item to handle batch toggle
            if items:
                items[0].batch_toggle(items, state)
        else:
            # Single item toggle
            item = self.model().itemFromIndex(index)
            if isinstance(item, BaseSimulationItem):
                item.set_state(state)