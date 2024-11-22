from PySide6 import QtCore, QtGui, QtWidgets
from .base_standarditem import BaseSimulationItem


class CharacterData:
    """
    Container for character information.
    """

    def __init__(self, name):
        self.name = name
        self.node_type = "null"
        self.short_name = self.get_short_name()
        self.character_name = name

    def get_short_name(self):
        """Return a short version of the name for cleaner display."""
        return self.name.split('|')[-1].split(':')[-1] if '|' in self.name else self.name


class CharacterTreeItem(QtGui.QStandardItem):
    """
    Represents a character in the tree. This item is a container for character data.
    """
    # Class-level settings
    CUSTOM_ROLES = {
        'NODE_NAME': QtCore.Qt.UserRole + 1,
        'NAMESPACE': QtCore.Qt.UserRole + 2,
        'STATE': QtCore.Qt.UserRole + 3,
        'SOLVER': QtCore.Qt.UserRole + 4,
        'NODE_TYPE': QtCore.Qt.UserRole + 5
    }
    def __init__(self, name):
        super().__init__(name)

        self._name = name

        self.character_data = CharacterData(name)
        self.setText(self.character_data.short_name)

        # Set a bold font for the character name
        font = QtGui.QFont()
        font.setBold(True)
        self.setFont(0, font)

        self._setup_item()

    def _setup_item(self):
        """Configure item properties and data."""
        self.setEditable(False)

        # Set display data
        self.setData(self._name, self.CUSTOM_ROLES['NODE_NAME'])
        self.setData(self.namespace, self.CUSTOM_ROLES['NAMESPACE'])
        self.setData("null", self.CUSTOM_ROLES['SOLVER'])
        self.setData(self.node_type, self.CUSTOM_ROLES['NODE_TYPE'])
        self.setData(self.character_data.short_name, QtCore.Qt.DisplayRole)

        # Initialize state
        self.setData("null", self.CUSTOM_ROLES['STATE'])

    @property
    def name(self):
        return self.character_data.name

    @property
    def character_name(self):
        return self.character_data.character_name

    @property
    def node_type(self):
        return self.character_data.node_type

    @property
    def namespace(self):
        return self.character_data.name.split(":")[0] if ":" in self.character_data.name else ":"

