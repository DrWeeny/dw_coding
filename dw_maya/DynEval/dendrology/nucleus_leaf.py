#!/usr/bin/env python
#----------------------------------------------------------------------------#
#------------------------------------------------------------------ HEADER --#

"""
@author:
    abtidona

@description:
    this is a description

@applications:
    - groom
    - cfx
    - fur
"""

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#

# built-in
import sys, os
# ----- Edit sysPath -----#
rdPath = '/user_data/AMJB/coding/dw_tools/maya/DNEG2'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)
import re
from . import ncloth_cmds


# internal
from PySide6 import QtCore, QtGui, QtWidget
from PySide6.QtGui import QStandardItem
import maya.cmds as cmds

# external
import dw_maya_utils as dwu

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#


#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

class CharacterData:
    """
    Container for character information.
    """

    def __init__(self, name, node_type=None):
        self.name = name
        self.node_type = node_type
        self.short_name = self.get_short_name()
        self.character_name = name

    def get_short_name(self):
        """Return a short version of the name for cleaner display."""
        return self.name.split('|')[-1].split(':')[-1] if '|' in self.name else self.name


class CharacterTreeItem(QtWidgets.QTreeWidgetItem):
    """
    Represents a character in the tree. This item is a container for character data.
    """

    def __init__(self, character_data: CharacterData, parent=None):
        super().__init__(parent)

        self.character_data = character_data
        self.setText(0, self.character_data.short_name)

        # Set a bold font for the character name
        font = QtGui.QFont()
        font.setBold(True)
        self.setFont(0, font)

    @property
    def name(self):
        return self.character_data.name

    @property
    def character_name(self):
        return self.character_data.character_name

    @property
    def node_type(self):
        return self.character_data.node_type


class NucleusStandardItem(QtGui.QStandardItem):
    onIcon = QtGui.QIcon('path/to/on.png')
    offIcon = QtGui.QIcon('path/to/off.png')
    iconList = {
        'nucleus': '',
        'nCloth': 'path/to/ncloth.png',
        'hairSystem': 'path/to/nhair.png',
        'nRigid': 'path/to/collider.png',
        'nConstraint': 'path/to/nconstraint.png'
    }
    textColor = {
        'nucleus': (194, 177, 109),
        'nCloth': (224, 255, 202),
        'nRigid': (0, 150, 255),
        'hairSystem': (237, 150, 0),
        'nConstraint': ''
    }

    def __init__(self, node):
        super(NucleusStandardItem, self).__init__()
        self.node = node
        self.setText(self.short_name)
        self.setForeground(QtGui.QBrush(self.node_color))
        self.setIcon(self.node_icon)
        self.setCheckable(True)
        self.setCheckState(QtCore.Qt.Checked if self.state else QtCore.Qt.Unchecked)


    @property
    def short_name(self):
        try:
            p = cmds.listRelatives(self.node, p=True)[0]
        except:
            p = self.node

        return p.split('|')[-1].split(':')[-1].split('_Sim')[0]

    @property
    def state_attr(self):
        if cmds.getAttr('{}.enable'.format(self.node), se=True):
            return 'enable'
        else:
            # I like visibility to drive the enable too
            poss = cmds.listConnections('{}.enable'.format(self.node), p=1)
            for i in poss:
                if cmds.getAttr(i, se=True):
                    return i.split('.')[-1]

    @property
    def state(self):
        return cmds.getAttr(f'{self.node}.{self.state_attr}')

    @property
    def node_type(self):
        return cmds.nodeType(self.node)

    @property
    def node_color(self):
        rgb = self.textColor[self.node_type]
        return QtGui.QColor(*rgb)

    @property
    def node_icon(self):
        iconPath = self.iconList[self.node_type]
        return QtGui.QIcon(iconPath)

    def set_state(self, state):
        cmds.setAttr(f'{self.node}.{self.state_attr}', state)
        if state:
            self.btn_state.setIcon(self.onIcon)
        else:
            self.btn_state.setIcon(self.offIcon)
        self.btn_state.setIconSize(QtCore.QSize(20, 20))


    def toggle_state(self):
        current_state = self.state
        self.set_state(not current_state)


from PySide6 import QtWidgets, QtGui, QtCore
import maya.cmds as cmds


class ToggleButtonDelegate(QtWidgets.QStyledItemDelegate):
    """Delegate for rendering an on/off button for dynamic state in the view."""

    toggled = QtCore.Signal(QtCore.QModelIndex, bool)  # Signal to notify toggle changes

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_icon = QtGui.QIcon("path/to/on_icon.png")  # Path to on icon
        self.off_icon = QtGui.QIcon("path/to/off_icon.png")  # Path to off icon

    def paint(self, painter, option, index):
        # Set up the button's rect (aligned to the right of the cell)
        button_rect = option.rect.adjusted(option.rect.width() - 24, 4, -4, -4)

        # Retrieve the button state from the model data
        is_on = index.data(QtCore.Qt.UserRole + 3)

        # Choose the icon based on the state
        icon = self.on_icon if is_on else self.off_icon
        icon.paint(painter, button_rect, QtCore.Qt.AlignCenter)

    def editorEvent(self, event, model, option, index):
        """Handle the toggle state when clicking on the icon."""
        if event.type() == QtCore.QEvent.MouseButtonRelease:
            # Calculate button rect and check if click is inside
            button_rect = option.rect.adjusted(option.rect.width() - 24, 4, -4, -4)
            if button_rect.contains(event.pos()):
                # Toggle the state
                is_on = index.data(QtCore.Qt.UserRole + 3)
                model.setData(index, not is_on, QtCore.Qt.UserRole + 3)
                # Emit signal for external handling if needed
                self.toggled.emit(index, not is_on)
                return True
        return False


class BaseSimulationItem(QtGui.QStandardItem):
    """Base item class for simulation nodes."""

    def __init__(self, name):
        super().__init__(name)
        self.node = name
        self.namespace = self.get_ns(name)
        self.solver_name = self.get_solver(name)
        self.setEditable(False)

        # Model data properties
        self.setData(name, QtCore.Qt.DisplayRole)
        self.setData(self.solver_name, QtCore.Qt.UserRole + 1)
        self.setData(self.namespace, QtCore.Qt.UserRole + 2)

    def get_ns(self, node_name):
        """Retrieve namespace from node."""
        return node_name.split(':')[0] if ':' in node_name else ''

    def get_solver(self, node_name):
        """Find connected solver."""
        connections = cmds.listConnections(node_name, type="nucleus")
        return connections[0].split(':')[-1] if connections else ''

    @property
    def state(self):
        return cmds.getAttr(f"{self.node}.{self.state_attr}")

    def set_state(self, state):
        cmds.setAttr(f"{self.node}.{self.state_attr}", state)


class ClothTreeItem(BaseSimulationItem):
    """Tree item for cloth simulation nodes."""

    def __init__(self, name):
        super().__init__(name)
        self.setText(self.short_name)

        self.setData(self.state, QtCore.Qt.UserRole + 3)  # Toggle state data

    @property
    def short_name(self):
        """Display-friendly name."""
        return self.node.split('|')[-1].split(':')[-1].split('_cloth')[0]

    @property
    def state_attr(self):
        """Simulation state attribute."""
        return 'isDynamic'

    def cache_dir(self, mode=1):
        """Get cache directory path."""
        base_dir = Path(cmds.workspace(fileRuleEntry='fileCache')).resolve()
        sub_dir = Path(self.namespace, self.solver_name, self.short_name)
        return (base_dir / ('dynTmp' if mode == 0 else sub_dir)).as_posix()

    def cache_file(self, mode=1, suffix=''):
        """Construct cache filename."""
        iteration = self.get_iter() + mode
        suffix_text = f"_{suffix}" if suffix else ""
        cache_filename = f"{self.short_name}{suffix_text}_v{iteration:03d}.xml"
        return (Path(self.cache_dir()) / cache_filename).as_posix()

    def has_cache(self):
        """Check if the cache exists for the node."""
        # Custom logic based on requirements
        pass

    def get_cache_list(self):
        """List all available cache files."""
        path = Path(self.cache_dir())
        return sorted([file.stem for file in path.glob('*.xml')]) if path.exists() else []

    def get_iter(self):
        """Determine current cache iteration/version."""
        path = Path(self.cache_dir())
        if path.exists():
            versions = [int(file.stem.split('_v')[-1]) for file in path.glob('*.xml')]
            return max(versions, default=0)
        return 0

    def get_maps(self):
        """Retrieve available vertex maps for the node."""
        return ncloth_cmds.get_vtx_maps(self.node)

    def get_maps_mode(self):
        """Retrieve vertex map modes for each map."""
        return [ncloth_cmds.get_vtx_map_type(self.node, f"{map_name}MapType") for map_name in self.get_maps()]

class HairTreeItem(BaseSimulationItem):
    """Item class for hair simulation nodes."""

    def __init__(self, name):
        super().__init__(name)
        self.setText(self.short_name)
        self.setIcon(QtGui.QIcon("path/to/hair_icon.png"))

        # Set initial state for the button, specific to hair (simulationMethod attribute)
        self.setData(self.state, QtCore.Qt.UserRole + 3)  # Toggle state data


    @property
    def mesh_transform(self):
        """Returns the transform of the hair node's mesh."""
        parent = cmds.listRelatives(self.node, p=True, f=True)
        return parent[0] if parent else None

    @property
    def short_name(self):
        """A simplified name for the node, avoiding namespace clutter."""
        return self.node.split('|')[-1].split(':')[-1]

    @property
    def state_attr(self):
        """Returns the attribute used to toggle hair simulation."""
        return 'simulationMethod'

    @property
    def state(self):
        """Current state of the simulation (0 = Off, 1 = Static, 2+ = Dynamic)."""
        return cmds.getAttr(f"{self.node}.{self.state_attr}")

    def set_state(self, state):
        """Set the simulation state for hair."""
        cmds.setAttr(f"{self.node}.{self.state_attr}", state)
        self.setData(state, QtCore.Qt.UserRole + 3)  # Update model data for delegate use


class NRigidTreeItem(BaseSimulationItem):
    """Item class for nRigid simulation nodes."""

    def __init__(self, name):
        super().__init__(name)
        self.setText(self.short_name)
        self.setIcon(QtGui.QIcon("path/to/rigid_icon.png"))

        # Set initial data for model
        self.setData(self.short_name, QtCore.Qt.DisplayRole)
        self.setData(self.state, QtCore.Qt.UserRole + 3)

    @property
    def short_name(self):
        """Returns a clean short name without suffixes for better readability."""
        shortname = self.node.split('|')[-1].split(':')[-1].split('_collider')[0]
        shortname = re.sub(r'_nRigid(Shape)?\d+$', '', shortname)
        return shortname

    @property
    def mesh_transform(self):
        """Gets the associated mesh transform for the nRigid node."""
        connected_meshes = [
            i for i in cmds.listConnections(f"{self.node}.inputMesh", sh=True)
            if cmds.nodeType(i) == 'mesh' and len(i.split('.')) == 1
        ]
        return dwu.lsTr(connected_meshes[0], long=True)[0] if connected_meshes else None

    @property
    def state_attr(self):
        """Returns the attribute used to toggle nRigid state."""
        return 'isDynamic'

    @property
    def state(self):
        """Current state of the rigid body."""
        return cmds.getAttr(f"{self.node}.{self.state_attr}")

    def cache_dir(self, mode=1):
        """Returns the directory path for cache files."""
        base_dir = cmds.workspace(fileRuleEntry='fileCache')
        cache_subdir = f"/{self.namespace}/{self.solver_name}/{self.short_name}/"
        return os.path.join(base_dir, 'dynTmp' if mode == 0 else cache_subdir).replace('//', '/')

    def cache_file(self, mode=1, suffix=''):
        """Generates the file path for the cache file based on the iteration."""
        path = self.cache_dir()
        iteration = self.get_iter() + mode
        suffix_text = f'_{suffix}' if suffix else ''
        cache_file = f"{self.short_name}{suffix_text}_v{iteration:03d}.xml"
        return os.path.join(path, cache_file).replace('__', '_')

    def get_cache_list(self):
        """Lists all existing cache files."""
        path = self.cache_dir()
        return sorted(
            [file.replace('.xml', '') for file in os.listdir(path) if file.endswith('.xml')],
            reverse=True
        ) if os.path.exists(path) else []

    def get_iter(self):
        """Retrieves the latest iteration version number."""
        path = self.cache_dir()
        if os.path.exists(path):
            versions = [
                int(re.search(r'v(\d{3})', file).group(1))
                for file in os.listdir(path) if file.endswith('.xml')
            ]
            return max(versions, default=0)
        return 0

    def get_maps(self):
        """Retrieves the vertex maps associated with this node."""
        return ncloth_cmds.get_vtx_maps(self.node)

    def get_maps_mode(self):
        """Retrieves the vertex map modes (types) for the maps associated with this node."""
        return [
            ncloth_cmds.get_vtx_map_type(self.node, f"{map_name}MapType")
            for map_name in self.get_maps()
        ]

class MapItemModel(QtGui.QStandardItem):
    """Model item representing a paintable map in the tree view."""

    def __init__(self, node_name, map_attr):
        super().__init__()
        self.node_name = node_name
        self.map_name = map_attr[0]
        self.map_index = map_attr[1]

        # Set text display
        self.setText(self.map_name)
        self.setEditable(False)

        # Storing full attribute for painting
        self.setData(self.get_attr_full(), QtCore.Qt.UserRole)
        # Store the map index for display in the combobox
        self.setData(self.map_index, QtCore.Qt.UserRole + 1)

    def get_attr_full(self):
        """Constructs the full attribute path."""
        map_type = {0: '', 1: 'PerVertex', 2: 'Map'}.get(self.map_index, '')
        return f"{self.node_name}.{self.map_name}{map_type}"



class MapTypeDelegate(QtWidgets.QStyledItemDelegate):
    """Delegate for managing the combobox, label color, and painting functionality."""

    COLOR_MAP = {0: "color: rgb(175, 175, 175);", 1: "color: rgb(0, 255, 0);", 2: "color: rgb(0, 125, 255);"}

    def createEditor(self, parent, option, index):
        """Creates a combobox editor for map type selection."""
        editor = QtWidgets.QComboBox(parent)
        editor.addItems(["None", "Vertex", "Texture"])
        current_index = index.data(QtCore.Qt.UserRole + 1)
        editor.setCurrentIndex(current_index if current_index is not None else 0)
        editor.currentIndexChanged.connect(lambda idx, i=index: self.on_map_type_changed(i, idx))
        return editor

    def setEditorData(self, editor, index):
        """Sets the editor data, updating colors and initial value."""
        current_index = index.data(QtCore.Qt.UserRole + 1)
        editor.setCurrentIndex(current_index if current_index is not None else 0)

    def setModelData(self, editor, model, index):
        """Stores selected map type in model, applies coloring and sets updated values."""
        new_index = editor.currentIndex()
        model.setData(index, new_index, QtCore.Qt.UserRole + 1)  # Update the stored map type
        model.setData(index, self.COLOR_MAP[new_index], QtCore.Qt.ForegroundRole)

    def paint(self, painter, option, index):
        """Custom painting to handle color updates on text and double-click behavior."""
        painter.save()
        map_type_index = index.data(QtCore.Qt.UserRole + 1) or 0
        color = self.COLOR_MAP.get(map_type_index, "color: rgb(175, 175, 175);")
        option.font.setItalic(True)  # Optional for styling
        painter.setPen(QtGui.QColor(color))
        super().paint(painter, option, index)
        painter.restore()

    def on_map_type_changed(self, index, map_type_idx):
        """Updates the map type on change."""
        node_name = map_type_idx.data(QtCore.Qt.DisplayRole)
        map_name = map_type_idx.data(QtCore.Qt.UserRole)
        ncloth_cmds.set_vtx_map_type(node_name, f"{map_name}MapType", index)

    def editorEvent(self, event, model, option, index):
        """Handles double-click events to initiate map painting."""
        if event.type() == QtCore.QEvent.MouseButtonDblClick:
            attr_full = index.data(QtCore.Qt.UserRole)
            cloth_mesh = index.data(QtCore.Qt.UserRole + 2)  # Stored if needed for painting
            if attr_full:
                ncloth_cmds.paint_vtx_map(attr_full, cloth_mesh)
        return super().editorEvent(event, model, option, index)
