from __future__ import annotations
from PySide6 import QtCore, QtGui, QtWidget
from typing import Optional, List, Dict, Any, Union
import maya.cmds as cmds
from pathlib import Path
from enum import Enum, auto
from dw_logger import get_logger
from dataclasses import dataclass

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
    }

    def __init__(self, name: str):
        """Initialize simulation item with enhanced data management.

        Args:
            name: Name of the Maya node
        """
        super().__init__(name)
        self._node_data = self._initialize_node_data(name)
        self._setup_item()

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
        """Set node state with proper error handling and signals.

        Args:
            state: True for enabled, False for disabled
        """
        try:
            # Set pending state during operation
            self.setData(SimulationState.PENDING, self.CUSTOM_ROLES['STATE'])

            # Update Maya
            cmds.setAttr(f"{self.node}.{self.state_attr}", state)

            # Update item state
            self.setData(
                SimulationState.ENABLED if state else SimulationState.DISABLED,
                self.CUSTOM_ROLES['STATE']
            )

            logger.debug(f"Successfully set {self.node} state to {state}")

        except Exception as e:
            logger.error(f"Failed to set state for {self.node}: {e}")
            # Revert to previous state on failure
            self.setData(self._get_current_state(), self.CUSTOM_ROLES['STATE'])
            raise

    def batch_toggle(self, items: List[BaseSimulationItem], state: bool) -> None:
        """Toggle multiple items at once, respecting hierarchy.

        Args:
            items: List of items to toggle
            state: Desired state for all items
        """
        try:
            # Store current states for rollback
            original_states = {item.node: item._get_current_state() for item in items}

            # Toggle all items
            for item in items:
                item.set_state(state)

        except Exception as e:
            logger.error(f"Batch toggle failed: {e}")
            # Rollback on failure
            for item in items:
                try:
                    if item.node in original_states:
                        item.set_state(original_states[item.node])
                except Exception as rollback_error:
                    logger.error(f"Rollback failed for {item.node}: {rollback_error}")


    @property
    def node(self):
        """Retrieve a user-friendly, short name for the node."""
        return self._node_data.name

    @property
    def short_name(self):
        """Retrieve a user-friendly, short name for the node."""
        return self.node.split('|')[-1].split(':')[-1].split('_Sim')[0]

    @property
    def state_attr(self):
        """Derived classes should define specific attributes to track the node's state."""
        return 'enable'
