from PySide6 import QtCore, QtGui, QtWidgets
from typing import Optional, Dict, Any, List
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

    # custom signals :
    itemDoubleClicked = QtCore.Signal(BaseSimulationItem)
    selectionChanged = QtCore.Signal(list)
    clicked = QtCore.Signal(BaseSimulationItem)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Set the model
        self.setModel(SimulationTreeModel())

        # Setup delegate
        self.toggle_delegate = ToggleButtonDelegate(self)
        self.setItemDelegateForColumn(1, self.toggle_delegate)

        self.setColumnWidth(0, 200)
        self.setColumnWidth(1, 32)
        # self.setFirstColumnSpanned(0, QtCore.QModelIndex(), True)

        # Configure view
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection) # multiple sel
        self.setAlternatingRowColors(True)
        self.setAnimated(True)
        self.setIndentation(20)
        self.setSortingEnabled(True)

        # Optional: Prevent column resize
        header = self.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        header.setStretchLastSection(False)

        self.setMouseTracking(True)

        # Connect toggle signal to handle batch operations
        self.toggle_delegate.toggled.connect(self._handle_toggle)
        self.doubleClicked.connect(self._handle_double_click)
        self.selectionModel().selectionChanged.connect(self._handle_selection_changed)

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

    def _handle_double_click(self, index: QtCore.QModelIndex):
        """Handle double-click events on tree items."""
        try:
            # Get the item from the first column (where the simulation item is stored)
            item_index = self.model().index(index.row(), 0, index.parent())
            item = self.model().itemFromIndex(item_index)

            if isinstance(item, BaseSimulationItem):
                self.itemDoubleClicked.emit(item)

        except Exception as e:
            logger.error(f"Double-click handling failed: {e}")

    def _handle_selection_changed(self, selected: QtCore.QItemSelection, deselected: QtCore.QItemSelection):
        """Handle selection changes and emit selected items."""
        try:
            selected_items = self.get_selected_items()  # Use existing method
            self.selectionChanged.emit(selected_items)  # Emit the items
            print(f"Selection changed: {len(selected_items)} items")  # Debug print
        except Exception as e:
            logger.error(f"Selection change handling failed: {e}")

    def get_selected_items(self) -> List[BaseSimulationItem]:
        """Get currently selected items."""
        try:
            selected_items = []
            selection_model = self.selectionModel()

            if selection_model:
                selected_indexes = selection_model.selectedRows()

                for index in selected_indexes:
                    item = self.model().itemFromIndex(index)
                    if isinstance(item, BaseSimulationItem):
                        selected_items.append(item)

            return selected_items

        except Exception as e:
            logger.error(f"Failed to get selected items: {e}")
            return []

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """Handle mouse press events."""
        super().mousePressEvent(event)
        index = self.indexAt(event.pos())
        if index.isValid():
            item = self.model().itemFromIndex(self.model().index(index.row(), 0, index.parent()))
            if isinstance(item, BaseSimulationItem):
                self.clicked.emit(item)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        """Handle keyboard navigation and actions.

        Implements:
        - Enter/Return: Trigger double-click behavior (select in Maya)
        - Escape: Clear selection
        """
        try:
            if event.key() in (QtCore.Qt.Key_Enter, QtCore.Qt.Key_Return):
                # Get selected items and trigger double-click behavior
                selected_items = self.get_selected_items()
                if selected_items:
                    for item in selected_items:
                        self.itemDoubleClicked.emit(item)

            elif event.key() == QtCore.Qt.Key_Escape:
                self.clear_selection()

            else:
                # Let other key events propagate normally
                super().keyPressEvent(event)

        except Exception as e:
            logger.error(f"Key press handling failed: {e}")

    def clear_selection(self):
        """Clear the current selection."""
        if self.selectionModel():
            self.selectionModel().clearSelection()

    def mouseMoveEvent(self, event):
        """Handle mouse movement for hover effects."""
        super().mouseMoveEvent(event)
        index = self.indexAt(event.pos())
        if index.isValid() and index.column() == 1:
            self.viewport().update()

    def select_items(self, items: List[BaseSimulationItem]):
        """Programmatically select specific items."""
        try:
            if not items:
                return

            selection_model = self.selectionModel()
            if not selection_model:
                return

            # Clear current selection
            selection_model.clearSelection()

            # Create new selection
            selection = QtCore.QItemSelection()

            def find_item_index(target_item):
                """Helper to find the model index for an item."""
                for row in range(self.model().rowCount()):
                    parent_index = self.model().index(row, 0)
                    parent_item = self.model().itemFromIndex(parent_index)

                    if parent_item == target_item:
                        return parent_index

                    # Check children
                    for child_row in range(parent_item.rowCount()):
                        child_index = self.model().index(child_row, 0, parent_index)
                        child_item = self.model().itemFromIndex(child_index)

                        if child_item == target_item:
                            return child_index

                return None

            # Add each item to selection
            for item in items:
                index = find_item_index(item)
                if index:
                    selection.select(index, index)

            # Apply selection
            selection_model.select(selection, QtCore.QItemSelectionModel.Select |
                                   QtCore.QItemSelectionModel.Rows)

        except Exception as e:
            logger.error(f"Failed to select items: {e}")