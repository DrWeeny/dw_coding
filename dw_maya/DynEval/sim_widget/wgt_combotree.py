from PySide6 import QtWidgets, QtCore, QtGui
from typing import Optional, Dict, List
from dw_logger import get_logger

logger=get_logger()

class MeshComboModel(QtGui.QStandardItemModel):
    """Custom model for hierarchy in combo box"""

    def __init__(self):
        super().__init__()
        self.setHorizontalHeaderLabels(['Meshes'])
        self._flat_index_map: Dict[str, QtGui.QStandardItem] = {}  # Maps item text to model item

    def add_nucleus(self, nucleus_name: str) -> QtGui.QStandardItem:
        """Add a nucleus header item"""
        nucleus_item = QtGui.QStandardItem(nucleus_name)
        nucleus_item.setSelectable(False)
        nucleus_item.setEnabled(False)
        nucleus_item.setBackground(QtGui.QColor(200, 200, 200))  # Light gray
        self.appendRow(nucleus_item)
        return nucleus_item

    def add_mesh(self, parent_item: QtGui.QStandardItem, mesh_name: str, is_cloth: bool = True) -> QtGui.QStandardItem:
        """Add a mesh item (cloth or rigid)"""
        mesh_item = QtGui.QStandardItem(mesh_name)
        color = QtGui.QColor(100, 200, 100) if is_cloth else QtGui.QColor(100, 100, 200)
        mesh_item.setForeground(color)
        parent_item.appendRow(mesh_item)
        self._flat_index_map[mesh_name] = mesh_item
        return mesh_item

    def get_item(self, text: str) -> Optional[QtGui.QStandardItem]:
        """Get the model item for a given text"""
        return self._flat_index_map.get(text)

    def clear(self):
        """Clear the model and index mapping"""
        super().clear()
        self._flat_index_map.clear()
        self.setHorizontalHeaderLabels(['Meshes'])


class TreeComboBox(QtWidgets.QComboBox):
    """Custom combo box with tree view for nucleus/mesh hierarchy"""

    textChanged = QtCore.Signal(str)  # Emitted when selection changes

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        # Setup model
        self.mesh_model = MeshComboModel()
        self.setModel(self.mesh_model)

        self._current_text = ""

        # Setup tree view
        self.tree_view = QtWidgets.QTreeView()
        self.tree_view.setHeaderHidden(True)
        self.tree_view.setRootIsDecorated(True)
        self.tree_view.setSelectionBehavior(QtWidgets.QTreeView.SelectItems)
        self.tree_view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setView(self.tree_view)

        # Track root items for selection handling
        self._root_items: List[QtGui.QStandardItem] = []

        # Configure size
        self.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.setMaximumWidth(300)

        # Connect signals
        self.tree_view.clicked.connect(self._handle_item_clicked)

    def add_nucleus_data(self, nucleus_name: str, cloths: Optional[list] = None,
                         rigids: Optional[list] = None) -> None:
        """Add a nucleus system with its meshes"""
        nucleus_item = self.mesh_model.add_nucleus(nucleus_name)
        self._root_items.append(nucleus_item)

        # Add cloth meshes
        if cloths:
            for cloth in cloths:
                self.mesh_model.add_mesh(nucleus_item, cloth, is_cloth=True)

        # Add rigid meshes
        if rigids:
            for rigid in rigids:
                self.mesh_model.add_mesh(nucleus_item, rigid, is_cloth=False)

        # Expand the nucleus item
        self.tree_view.expand(nucleus_item.index())

    def select_item_by_text(self, text: str) -> bool:
        """Select an item by its text"""
        if not text:
            return False

        # Get the item from our mapping
        item = self.mesh_model.get_item(text)
        if not item:
            return False

        # Get the model index
        index = self.mesh_model.indexFromItem(item)
        if not index.isValid():
            return False

        # Set the root index to the parent (nucleus)
        parent_index = index.parent()
        if parent_index.isValid():
            self.setRootModelIndex(parent_index)

        # Set the current index to the selected item
        self.setCurrentIndex(index.row())

        # Store current text
        self._current_text = text  # Add this line

        # Reset root index to show full tree in popup
        if self._root_items:
            root_index = self.mesh_model.indexFromItem(self._root_items[0])
            self.setRootModelIndex(root_index.parent())

        # Emit signal
        logger.debug(f"TreeComboBox textChanged emit {text}")
        self.textChanged.emit(text)
        return True

    def _handle_item_clicked(self, index: QtCore.QModelIndex) -> None:
        """Handle clicks in the tree view"""
        item = self.mesh_model.itemFromIndex(index)
        if item and item.isSelectable():
            text = item.text()
            self.select_item_by_text(text)

    def get_current_text(self) -> str:
        """Get the currently selected item's text"""
        item = self.mesh_model.get_item(self._current_text) if hasattr(self, '_current_text') else None
        return item.text() if item else ""

    def clear(self) -> None:
        """Clear all items and reset state"""
        self.mesh_model.clear()
        self._root_items.clear()
        self.setCurrentIndex(-1)
        self.setRootModelIndex(QtCore.QModelIndex())


# Example usage
if __name__ == "__main__":
    app = QtWidgets.QApplication([])

    # Create test window
    window = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(window)

    # Create combo box
    combo = TreeComboBox()
    layout.addWidget(combo)

    # Add test data
    combo.add_nucleus_data(
        "nucleus1",
        cloths=["cloth1", "cloth2"],
        rigids=["rigid1"]
    )

    # Add label to show selection
    label = QtWidgets.QLabel("Selected: None")
    layout.addWidget(label)

    # Connect selection changes to label
    combo.textChanged.connect(lambda text: label.setText(f"Selected: {text}"))

    # Test selection
    combo.select_item_by_text("cloth2")

    window.show()
    app.exec()