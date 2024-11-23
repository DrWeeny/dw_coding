from __future__ import annotations
from PySide6 import QtCore, QtGui, QtWidgets
from typing import Optional, List, Dict, Any, Union
import maya.cmds as cmds
from pathlib import Path
from enum import Enum, auto
from dw_logger import get_logger
from dataclasses import dataclass
from dw_ressources import get_resource_path

logger = get_logger()

#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#
class SimulationState(Enum):
    """Enum for possible simulation states"""
    DISABLED = auto()
    ENABLED = auto()
    PENDING = auto()  # For operations in progress

@dataclass
class NodeData:
    """Data container for node information"""
    name: str
    namespace: str
    solver: str
    state_attr: str = 'enable'

class BaseSimulationItem(QtGui.QStandardItem):
    """Modernized base item for simulation nodes with enhanced state management."""

    # Class-level settings
    CUSTOM_ROLES = {
        'NODE_NAME': QtCore.Qt.UserRole + 1,
        'NAMESPACE': QtCore.Qt.UserRole + 2,
        'STATE': QtCore.Qt.UserRole + 3,
        'SOLVER': QtCore.Qt.UserRole + 4,
        'NODE_TYPE': QtCore.Qt.UserRole + 5
    }

    TEXT_COLOR = {'nucleus': (194, 177, 109),
                 'nCloth': (224, 255, 202),
                 'nRigid': (0, 150, 255),
                 'hairSystem': (237, 150, 0),
                 'nConstraint': ''}

    ICON_LIST = {'nucleus': '',
                'nCloth': get_resource_path('pic_files/ncloth.png'),
                'hairSystem': get_resource_path('pic_files/nhair.png'),
                'nRigid': get_resource_path('pic_files/collider.png'),
                'nConstraint': get_resource_path('pic_files/nconstraint.png')}


    def __init__(self, name: str):
        """Initialize simulation item with enhanced data management.

        Args:
            name: Name of the Maya node
        """
        super().__init__(name)
        # logger.info(f"{name} has been appended in tree")
        self._node_data = self._initialize_node_data(name)
        self._setup_item()
        self.set_node_color()

    def _initialize_node_data(self, name: str) -> NodeData:
        """Initialize node data with proper error handling."""
        try:
            if not cmds.objExists(name):
                raise ValueError(f"Node {name} does not exist")

            namespace = self._get_namespace(name)
            solver = self._get_solver(name)

            return NodeData(
                name=name,
                namespace=namespace,
                solver=solver
            )
        except Exception as e:
            logger.error(f"Failed to initialize node data for {name}: {e}")
            raise

    def _setup_item(self):
        """Configure item properties and data."""
        self.setEditable(False)

        # Set display data
        self.setData(self._node_data.name, self.CUSTOM_ROLES['NODE_NAME'])
        self.setData(self._node_data.namespace, self.CUSTOM_ROLES['NAMESPACE'])
        self.setData(self._node_data.solver, self.CUSTOM_ROLES['SOLVER'])
        self.setData(self.node_type, self.CUSTOM_ROLES['NODE_TYPE'])
        self.setData(self.short_name, QtCore.Qt.DisplayRole)

        # Initialize state
        current_state = self._get_current_state()
        self.setData(current_state, self.CUSTOM_ROLES['STATE'])


    def _get_namespace(self, node_name: str) -> str:
        """Extract namespace from node name."""
        return node_name.split(':')[0] if ':' in node_name else ''

    def _get_solver(self, node_name: str) -> str:
        """Get connected solver with error handling."""
        try:
            connections = cmds.listConnections(node_name, type="nucleus") or []
            return connections[0].split(':')[-1] if connections else ''
        except Exception as e:
            logger.warning(f"Failed to get solver for {node_name}: {e}")
            return ''

    def _get_current_state(self) -> bool:
        """Get current state from Maya with error handling."""
        try:
            return bool(cmds.getAttr(f"{self.node}.{self.state_attr}"))
        except Exception as e:
            logger.warning(f"Failed to get state for {self.node}: {e}")
            return False

    def set_state(self, state: bool) -> None:
        """Set node state with proper error handling."""
        try:
            # Update Maya attribute
            cmds.setAttr(f"{self.node}.{self.state_attr}", state)

            # Update item data
            self.setData(state, self.CUSTOM_ROLES['STATE'])

            # Update model (find corresponding state item)
            if self.model():
                # Get parent index, handling root items
                parent_index = self.parent().index() if self.parent() else QtCore.QModelIndex()
                state_index = self.model().index(self.row(), 1, parent_index)
                if state_index.isValid():
                    self.model().setData(state_index, state, QtCore.Qt.UserRole + 3)

            logger.debug(f"Successfully set {self.node} state to {state}")

        except Exception as e:
            logger.error(f"Failed to set state for {self.node}: {e}")
            raise

    def batch_toggle(self, items: List['BaseSimulationItem'], state: bool) -> None:
        """Toggle multiple items at once, respecting hierarchy."""
        try:
            # Store current states for rollback
            original_states = {item.node: item._get_current_state() for item in items}

            # Toggle all items
            for item in items:
                try:
                    item.set_state(state)
                except Exception as e:
                    logger.error(f"Failed to toggle {item.node}: {e}")
                    raise  # Propagate error to trigger rollback

        except Exception as e:
            logger.error(f"Batch toggle failed: {e}")
            # Rollback on failure
            for item in items:
                try:
                    if item.node in original_states:
                        self._safe_set_state(item, original_states[item.node])
                except Exception as rollback_error:
                    logger.error(f"Rollback failed for {item.node}: {rollback_error}")

    def _safe_set_state(self, item: 'BaseSimulationItem', state: bool) -> None:
        """Safely set state without raising exceptions."""
        try:
            cmds.setAttr(f"{item.node}.{item.state_attr}", state)

            if item.model():
                parent_index = item.parent().index() if item.parent() else QtCore.QModelIndex()
                state_index = item.model().index(item.row(), 1, parent_index)
                if state_index.isValid():
                    item.model().setData(state_index, state, QtCore.Qt.UserRole + 3)
        except Exception as e:
            logger.error(f"Safe state set failed for {item.node}: {e}")

    @property
    def node(self):
        """Retrieve a user-friendly, short name for the node."""
        return self._node_data.name

    @property
    def short_name(self):
        """Retrieve a user-friendly, short name for the node."""
        try :
            node = cmds.listRelatives(self.node, parent=True)[0]
        except:
            node = self.node
        return node.split('|')[-1].split(':')[-1].split('_Sim')[0]

    @property
    def state_attr(self):
        """Derived classes should define specific attributes to track the node's state."""
        return 'enable'

    @property
    def node_type(self):
        _nt = "null"
        if cmds.objExists(self.node):
            _nt = cmds.nodeType(self.node)
        return _nt

    def set_node_color(self):
        b = QtGui.QBrush(self.node_color)
        self.setForeground(b)

    @property
    def node_color(self):
        rgb = self.TEXT_COLOR[self.node_type]
        return QtGui.QColor(*rgb)

    @property
    def node_icon(self):
        iconPath = self.ICON_LIST[self.node_type]
        return QtGui.QIcon(str(iconPath))

    @property
    def namespace(self):
        return self.node.split(":")[0] if ":" in self.node else ":"

    @property
    def solver_name(self):
        return self._get_solver(self.node)

    @property
    def state(self):
        value = None
        if cmds.objExists(self.node):
            value = cmds.getAttr(f"{self.node}.{self.state_attr}")
        return value

    @property
    def mesh_transform(self):
        return self.node

    def set_filerule(self):

        fileRule = "fileCache"
        location = "cache/nCache"

        ruleLocation = cmds.workspace(fileRuleEntry=fileRule)
        cmds.workspace(fileRule=[fileRule, location])

    def metadata(self, mode=1):
        '''
        used to store which cache is starred
        used to store comments
        used to set attach ones
        '''

        self.set_filerule()

        directory = cmds.workspace(fileRuleEntry='fileCache')
        directory = cmds.workspace(en=directory)
        if mode == 0:
            return str(Path(directory) / 'dynTmp')

        directory = Path(directory) / f"{self.namespace}/{self.solver_name}/metadata.json"
        return str(directory)
