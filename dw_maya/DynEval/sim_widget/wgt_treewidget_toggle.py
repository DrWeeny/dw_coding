from PySide6 import QtCore, QtGui, QtWidgets
from dw_maya.DynEval.dendrology.nucleus_leaf.tree_togglebutton import ToggleButtonDelegate

class TreeViewWithToggle(QtWidgets.QWidget):
    def __init__(self):
        super(TreeViewWithToggle, self).__init__()

        # Create the QTreeView
        self.tree_view = QtWidgets.QTreeView(self)
        self.tree_view.setHeaderHidden(False)
        self.tree_view.setMaximumWidth(280)
        self.tree_view.setMaximumHeight(300)
        self.tree_view.setExpandsOnDoubleClick(False)
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setColumnWidth(0, 250)
        self.tree_view.setColumnWidth(1, 25)

        # Create the model
        self.model = QtGui.QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["Name", "State"])

        header = self.tree_view.header()
        header.setStretchLastSection(False)

        # Set the model to the tree view
        self.tree_view.setModel(self.model)

        # Add example rows
        self.add_row("Item 1", True)
        self.add_row("Item 2", False)

        # Create and set the toggle button delegate
        toggle_delegate = ToggleButtonDelegate()
        toggle_delegate.toggled.connect(self.on_toggled)
        self.tree_view.setItemDelegateForColumn(1, toggle_delegate)

        # Layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.tree_view)
        self.setLayout(layout)

    def add_row(self, name, state):
        # Create the name item
        name_item = QtGui.QStandardItem(name)

        # Create the toggle item
        toggle_item = QtGui.QStandardItem()
        toggle_item.setData(state, QtCore.Qt.UserRole + 3)  # Store toggle state in UserRole + 3

        # Add the items to the model
        self.model.appendRow([name_item, toggle_item])

    def on_toggled(self, index, new_state):
        print(f"Toggled {index.row()} to {'On' if new_state else 'Off'}")

    def selectedItems(self):
        return self.selectedItems()

    def currentItem(self):
        return self.currentItem()

    def setCurrentItem(self, item):
        self.setCurrentItem(item)