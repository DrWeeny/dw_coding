from PySide6 import QtWidgets, QtCore, QtGui
from dw_logger import get_logger

logger = get_logger()


class MeshComboModel(QtGui.QStandardItemModel):
    """Custom model for hierarchy in combo box"""

    def __init__(self):
        super().__init__()
        self.setHorizontalHeaderLabels(['Meshes'])

    def add_nucleus(self, nucleus_name: str) -> QtGui.QStandardItem:
        """Add a nucleus header item"""
        nucleus_item = QtGui.QStandardItem(nucleus_name)
        nucleus_item.setSelectable(False)
        nucleus_item.setEnabled(False)
        nucleus_item.setBackground(QtCore.Qt.gray)
        self.appendRow(nucleus_item)
        return nucleus_item

    def add_cloth(self, parent_item: QtGui.QStandardItem, cloth_name: str):
        """Add a cloth mesh item"""
        cloth_item = QtGui.QStandardItem(cloth_name)
        cloth_item.setForeground(QtCore.Qt.green)
        parent_item.appendRow(cloth_item)
        return cloth_item

    def add_rigid(self, parent_item: QtGui.QStandardItem, rigid_name: str):
        """Add a rigid mesh item"""
        rigid_item = QtGui.QStandardItem(rigid_name)
        rigid_item.setForeground(QtCore.Qt.blue)
        parent_item.appendRow(rigid_item)
        return rigid_item

    def indexToRow(self, index) -> int:
        """Convert a tree index to a flat row number for the combo box"""
        if not index.isValid():
            return -1

        row = 0

        def count_items(parent_index, target_index):
            nonlocal row
            if parent_index == target_index:
                return True

            for r in range(self.rowCount(parent_index)):
                child_index = self.index(r, 0, parent_index)
                if child_index == target_index:
                    return True

                if self.hasChildren(child_index):
                    if count_items(child_index, target_index):
                        return True
                row += 1
            return False

        count_items(self.invisibleRootItem().index(), index)
        return row


class TreeComboBox(QtWidgets.QComboBox):
    """Custom combo box with tree view"""

    textChanged = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view().clicked.connect(self._handle_item_clicked)

        # Create and set the model
        self.model = MeshComboModel()
        self.setModel(self.model)

        # Create and set the tree view
        self.tree_view = QtWidgets.QTreeView()
        self.tree_view.setHeaderHidden(True)
        self.tree_view.setRootIsDecorated(True)
        self.tree_view.setSelectionBehavior(QtWidgets.QTreeView.SelectRows)
        self.tree_view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setView(self.tree_view)

        # Adjust size policies
        self.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.setMaximumWidth(300)

        # Track items and their indices
        self._items_map = {}  # {text: index}
        self._current_index = 0

        # Connect the native currentIndexChanged signal to our handler
        self.currentIndexChanged.connect(self._handle_index_changed)

    def _handle_index_changed(self, index: int):
        """Handle index changes and emit text signal"""
        # Find text for this index
        text = ""
        for item_text, item_index in self._items_map.items():
            if item_index == index:
                text = item_text
                print(text)
                break

        logger.debug(f"Index changed to {index}, text: {text}")
        # Emit our custom signal with the text
        self.textChanged.emit(text)

    def add_nucleus_data(self, nucleus_name: str, cloths=None, rigids=None):
        """Add a complete nucleus system with its meshes"""
        logger.debug(f"Adding nucleus data: {nucleus_name}")
        try:
            # Create nucleus header
            nucleus_item = self.model.add_nucleus(nucleus_name)

            # Track nucleus (even though not selectable)
            self._items_map[nucleus_name] = self._current_index
            self._current_index += 1

            # Add cloth meshes
            if cloths:
                logger.debug(f"Adding cloth meshes: {cloths}")
                for cloth in cloths:
                    self.model.add_cloth(nucleus_item, cloth)
                    self._items_map[cloth] = self._current_index
                    self._current_index += 1

            # Add rigid meshes
            if rigids:
                logger.debug(f"Adding rigid meshes: {rigids}")
                for rigid in rigids:
                    self.model.add_rigid(nucleus_item, rigid)
                    self._items_map[rigid] = self._current_index
                    self._current_index += 1

            # Expand the nucleus item
            self.tree_view.expand(nucleus_item.index())
            logger.debug(f"Items map after adding nucleus: {self._items_map}")

        except Exception as e:
            logger.error(f"Error adding nucleus data: {str(e)}")
            raise

    def clear(self):
        """Clear all items and reset tracking"""
        logger.debug("Clearing TreeComboBox")
        self.model.clear()
        self.model.setHorizontalHeaderLabels(['Meshes'])
        self._items_map.clear()
        self._current_index = 0
        self.setCurrentIndex(-1)
        logger.debug("TreeComboBox cleared")

    def select_item_by_text(self, text: str) -> bool:
        """Select item by text using tracked indices"""
        logger.debug(f"Attempting to select item: {text}")

        if text in self._items_map:
            index = self._items_map[text]
            logger.debug(f"Found item {text} at index {index}")

            # Set both combo box and tree view selection
            self.setCurrentIndex(index)

            # Set tree view selection
            model_index = self.model.index(index, 0)
            self.tree_view.setCurrentIndex(model_index)

            # Expand parent if needed
            parent = model_index.parent()
            if parent.isValid():
                self.tree_view.expand(parent)

            logger.debug(f"Selected item {text} at index {index}")
            return True

        logger.debug(f"Item not found: {text}")
        return False

    def _handle_item_clicked(self, index):
        """Handle item clicks"""
        item = self.model.itemFromIndex(index)
        if item and item.isSelectable():
            text = item.text()
            if text in self._items_map:
                self.setCurrentIndex(self._items_map[text])

# Example usage:
if __name__ == "__main__":
    app = QApplication([])

    # Create test window
    window = QWidget()
    layout = QVBoxLayout(window)

    # Create the combo box
    combo = TreeComboBox()
    layout.addWidget(combo)

    # Add test data
    combo.add_nucleus_data(
        "nucleus1",
        cloths=["cloth1", "cloth2"],
        rigids=["rigid1"]
    )

    combo.add_nucleus_data(
        "nucleus2",
        cloths=["cloth3"],
        rigids=["rigid2", "rigid3"]
    )

    # Select specific item
    combo.select_item_by_text("cloth2")  # Will find and select "cloth2"

    # Get selected text
    print(f"Selected item: {combo.get_selected_text()}")

    window.show()
    app.exec()