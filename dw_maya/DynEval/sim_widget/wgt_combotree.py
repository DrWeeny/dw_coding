from PySide6 import QtWidgets, QtCore, QtGui


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

    def __init__(self, parent=None):
        super().__init__(parent)

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

    def add_nucleus_data(self, nucleus_name: str, cloths=None, rigids=None):
        """Add a complete nucleus system with its meshes"""
        nucleus_item = self.model.add_nucleus(nucleus_name)

        if cloths:
            for cloth in cloths:
                self.model.add_cloth(nucleus_item, cloth)

        if rigids:
            for rigid in rigids:
                self.model.add_rigid(nucleus_item, rigid)

        # Expand the nucleus item
        self.tree_view.expand(nucleus_item.index())

    def clear_items(self):
        """Clear all items from the model"""
        self.model.clear()
        self.model.setHorizontalHeaderLabels(['Meshes'])

    def select_item_by_text(self, text: str) -> bool:
        """
        Find and select an item in the tree that matches the given text.

        Args:
            text (str): The text to match

        Returns:
            bool: True if item was found and selected, False otherwise
        """

        def find_match(parent_item):
            # Check all rows under the parent
            for row in range(parent_item.rowCount()):
                child = parent_item.child(row)
                if child:
                    # Check if this item matches
                    if child.text() == text and child.isSelectable():
                        return child
                    # Recursively check child's children
                    if child.hasChildren():
                        result = find_match(child)
                        if result:
                            return result
            return None

        # Start search from root
        root = self.model.invisibleRootItem()
        matching_item = find_match(root)

        if matching_item:
            # Get the model index
            index = matching_item.index()

            # Set the current index in the combo box
            self.setCurrentIndex(self.model.indexToRow(index))

            # Expand parent items to make selection visible
            parent = matching_item.parent()
            while parent:
                self.tree_view.expand(parent.index())
                parent = parent.parent()

            return True

        return False

    def get_selected_text(self) -> str:
        """Get the text of the currently selected item"""
        current_index = self.tree_view.currentIndex()
        if current_index.isValid():
            item = self.model.itemFromIndex(current_index)
            return item.text()
        return ""


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