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

class HairTreeItem(ClothItem):

    def __init__(self, name, parent):
        super(HairTreeItem, self).__init__(name, parent)
        # ClothTreeItem.__init__(self, name, parent)

        self.solver_name = self.get_solver(name)
        self.namespace = self.get_ns(name)

    @property
    def mesh_transform(self):
        o = cmds.listRelaltives(self.node, p=True, f=True)
        if o:
            o = o[0]
        return o

    @property
    def short_name(self):
        '''
        a nice string to not make pollution in the ui
        :return: str
        '''
        name = self.node.split('|')[-1].split(':')[-1]
        return name

    @property
    def state_attr(self):
        '''
        because nucleus and cloth have different attribute
        :return: str
        '''
        return 'simulationMethod'

    def set_state(self, state):
        cmds.setAttr('{}.{}'.format(self.node, self.state_attr), state)
        if state == 3:
            self.btn_state.setIcon(self.onIcon)
        elif state == 1:
            self.btn_state.setIcon(self.onIcon) # todo : create an orange icon for the static state
        else:
            self.btn_state.setIcon(self.offIcon)
        self.btn_state.setIconSize(QtCore.QSize(20, 20))

    def button_pressed(self):
        '''
        Triggered when Item's button pressed.
        an example of using the Item's own values.
        '''
        if self.state == 2:
            self.set_state(0)
        elif self.state == 0:
            # should be 1 but I've spotted some crash on dneg TODO : Bug
            self.set_state(2)
        elif self.state == 1:
            self.set_state(2)
        # hum have to see the use of this todo : investigate usage
        elif self.state == 3:
            self.set_state(0)

class NRigidTreeItem(NucleusTreeItem):

    def __init__(self, name, parent):
        super(NRigidTreeItem, self).__init__(name, parent)
        # NucleusTreeItem.__init__(self, name, parent)
        # NucleusTreeItem.__init__(self, name, parent)
        # or
        # super().__init__(self, name, parent) in python3
        # super(NucleusTreeItem, self).__init__(self, name, parent) in python3 and 2
        # if multiple class inheritance, make multiple lines

        #TODO : get the fuction from clothCmds or make it static
        self.solver_name = self.get_solver(name)
        self.namespace = self.get_ns(name)

    def get_ns(self, node_name):

        if ':' in node_name:
            return node_name.split(':')[0].split('|')[-1]
        else:
            return ''

    def get_solver(self, node_name):
        c = cmds.listConnections(node_name, c=1, type='nucleus')
        o = [i for i in c if len(i.split('.')) < 2]
        n = list(set(o))[0]
        n = n.split(':')[-1]
        return n

    @property
    def short_name(self):
        '''
        a nice string to not make pollution in the ui
        :return: str
        '''

        shortname = self.node.split('|')[-1].split(':')[-1].split('_collider')[0]

        pattern02 = re.compile('_nRigid(Shape)?\d+$')
        shortname = pattern02.sub('', shortname)

        return shortname

    @property
    def mesh_transform(self):
        o = [i for i in
             cmds.listConnections(self.node + '.inputMesh',
                                  sh=True) if cmds.nodeType(i) == 'mesh']
        o = [i for i in o if len(i.split('.')) == 1]
        o = dwu.lsTr(o[0], l=True)[0]
        return o

    @property
    def state_attr(self):
        return 'isDynamic'

    def cache_dir(self, mode=1):
        '''
        :return: str '../cache/ncache/nucleus/cloth/'
        '''

        self.set_filerule()

        directory = cmds.workspace(fileRuleEntry='fileCache')
        directory = cmds.workspace(en=directory)
        if mode == 0:
            return directory+'/dynTmp/'

        directory += "/{}/{}/{}/".format(self.namespace,
                                         self.solver_name,
                                         self.short_name)
        return directory.replace('//', '/')

    def cache_file(self, mode=1, suffix=''):
        '''

        :param mode: <<int>> 0=replace, 1=create
        :param suffix: <<str>>
        :return:
        '''
        path = self.cache_dir()
        iter = self.get_iter() + mode

        if not suffix:
            path += self.short_name + '_' + suffix + '_v{:03d}.xml'.format(iter)
        else:
            path += self.short_name + '_' + '_v{:03d}.xml'.format(iter)

        if not os.path.isfile(path) and not mode:
            # si le fichier n'existe et qu'on est en replace,
            # passer automatiquement en create
            if not suffix:
                path += '{}_{}_v{:03d}.xml'.format(self.short_name,
                                                   suffix,
                                                   iter + 1)
            else:
                path += self.short_name + '_' + '_v{:03d}.xml'.format(iter + 1)

        return path.replace('__', '_')

    def get_cache_list(self):
        '''
        list all the caches already done
        :return: <<list>> of file
        '''
        path = self.cache_dir()
        if os.path.exists(path):
            files = os.listdir(path)
            cache = [x.replace('.xml', '') for x in files if x.endswith('.xml')]
            return sorted(cache, reverse=True)
        else:
            return None

    def get_iter(self):
        '''
        get current version number
        :return: <<int>>
        '''
        if os.path.exists(self.cache_dir()):
            output = os.listdir(self.cache_dir())
            if not output:
                return 0
            xml = [i for i in output if i.endswith('.xml')]
            pattern = 'v([0-9]{3})'
            iter = sorted([int(re.findall(pattern, i)[0]) for i in xml])[-1]
            return iter
        else:
            return 0

    def get_maps(self):
        '''
        :return: <<list>> of string
        '''
        return ncloth_cmds.get_vtx_maps(self.node)

    def get_maps_mode(self):
        '''
        :return: <<list>> of integer
        '''
        values = []
        for i in self.get_maps():
            value = ncloth_cmds.get_vtx_map_type(self.node,
                                                 '{}MapType'.format(i))
            values.append(value)
        return values

class MapItem(QtWidgets.QTreeWidgetItem):
    '''
    Custom QTreeWidgetItem with Widgets
    '''

    def __init__(self, node_name, map_attr, parent):
        '''
        parent (QTreeWidget) : Item's QTreeWidget parent.
        name   (str)         : Item's name. just an example.
        '''

        ## Init super class ( QtGui.QTreeWidgetItem )
        QtWidgets.QTreeWidgetItem.__init__(self, parent)

        self.map_to_paint = None
        self.cloth_mesh = ''

        ## Column 1 - picker pixmap:
        self.map_widget = MapSetter(node_name, map_attr)
        self.treeWidget().setItemWidget(self, 0, self.map_widget)

        self.map_to_paint = self.get_attr_full()

    def get_attr_full(self):
        return self.map_widget.get_attr_full()


class MapSetter(QtWidgets.QWidget):

    def __init__(self, node_name, map_attr):
        '''
        The Widget is QLABEL + QComboBox
        It sets the nucleus node map to PerVertex or Texture or None
            (defined by maya as : 1,2,0)
        It return to the parent QTreeWidgetITem the fullname attr :
            |nClothShape.(MapName)(TypeOfMap)

        :param node_name: <<str>> nClothShape
        :param map_attr: <<list>> (map_name::str, map_typeIndex::int)
        :param parent: QTreeWidgetItem with a special input attr 'map_to_paint'
        '''
        QtWidgets.QWidget.__init__(self)

        # our basics input stored into self.var
        self.node_name = node_name
        self.map_name = map_attr[0]
        init_index = map_attr[1]

        self.hl_main = QtWidgets.QHBoxLayout()
        self.lb_map_name = QtWidgets.QLabel(self.map_name)

        self.map_type = QtWidgets.QComboBox()
        self.map_type.setObjectName("map_type")
        self.map_type.addItem("None")
        self.map_type.addItem("Vertex")
        self.map_type.addItem("Texture")
        self.map_type.setCurrentIndex(init_index)

        self.label_color()

        # add widget
        self.hl_main.addWidget(self.lb_map_name)
        self.hl_main.addWidget(self.map_type)
        self.setLayout(self.hl_main)

        # add signal
        self.map_type.currentIndexChanged.connect(self.onChange)

    def onChange(self):
        '''
        function triggered by QComboBox signal currentIndexChanged
        :return: <<str>>
        '''
        # change the node map type
        ncloth_cmds.set_vtx_map_type(self.node_name,
                                  '{}MapType'.format(self.map_name),
                                  self.index)
        # visual color of the label
        self.label_color()
        # return our new value to the parent
        self.get_attr_full()

    def label_color(self):
        """ Refresh map_type label color """
        if self.index == 0:
            self.lb_map_name.setStyleSheet("color: rgb(175, 175, 175)") #Grey
        elif self.index == 1:
            self.lb_map_name.setStyleSheet("color: rgb(0, 255, 0)") #Green
        elif self.index == 2:
            self.lb_map_name.setStyleSheet("color: rgb(0, 125, 255)") #Blue

    @property
    def index(self):
        '''
        :return: <<int>>
        '''
        return int(self.map_type.currentIndex())

    def get_attr_full(self):
        '''
        function that create the value with the widget values
        :return: <<str>>
        '''
        if self.index == 0:
            mytype = None
        elif self.index == 1:
            mytype = 'PerVertex'
        elif self.index == 2:
            mytype = 'Map'
        name = '{}.{}{}'.format(self.node_name, self.map_name, mytype)
        return name
