from PySide6 import QtWidgets, QtGui, QtCore


class ColoredMapComboBox(QtWidgets.QComboBox):
    """ComboBox with colored items for map types"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # self.setItemDelegate(ColoredItemDelegate())

        self.nucx_node = ""

        # Define colors for different map types (0=None, 1=Vertex, 2=Texture)
        self.type_colors = {
            0: QtGui.QColor(175, 175, 175),     # Grey for disabled
            1: QtGui.QColor(100, 200, 100),     # Green for vertex maps
            2: QtGui.QColor(100, 150, 255)      # Blue for texture maps
        }

    def addMapItem(self, text: str, map_type: int):
        """Add a map item with associated color

        Args:
            text: Map name to display
            map_type: Type of map (0=None, 1=Vertex, 2=Texture)
        """
        self.addItem(text)
        index = self.count() - 1

        # Get color based on map type
        color = self.type_colors.get(map_type, self.type_colors[0])
        self.setItemData(index, color, QtCore.Qt.ForegroundRole)

    def clear(self):
        """Override clear to reset internal data"""
        super().clear()
        self.nucx_node = ""


class ColoredItemDelegate(QtWidgets.QStyledItemDelegate):
    """Custom delegate for colored combobox items"""

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionViewItem,
              index: QtCore.QModelIndex):
        """Custom paint method for items"""
        option = QtWidgets.QStyleOptionViewItem(option)

        # Get the color from item data
        color = index.data(QtCore.Qt.ForegroundRole)
        if color:
            option.palette.setColor(QtGui.QPalette.Text, color)

        # Handle selection highlighting
        if option.state & QtWidgets.QStyle.State_Selected:
            option.palette.setColor(QtGui.QPalette.HighlightedText, color)

        super().paint(painter, option, index)