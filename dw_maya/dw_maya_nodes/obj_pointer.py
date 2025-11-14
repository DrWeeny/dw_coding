"""Provides low-level Maya API object wrapper functionality.

A module focused on efficient access to Maya's internal object representation
using the OpenMaya API.

Classes:
    NodePath: Data container for node path information
    ObjPointer: Low-level wrapper for Maya API objects

Version: 1.0.0

Author:
    DrWeeny

Web Source:
    Base implementation inspired by: https://www.toadstorm.com/blog/?p=628
"""
import maya.OpenMaya as om
from maya import cmds

from dw_logger import get_logger

logger = get_logger()


class ObjPointer(object):
    """
    A class that wraps around Maya's MObject, MDagPath, and MFnDependencyNode.

    Provides functionality to handle Maya nodes, their paths, and names.

    Derived from: https://www.toadstorm.com/blog/?p=628

    Args:
        node_name (str): The name of the Maya node to wrap.

    Attributes:
        _mobject (om.MObject): The Maya MObject of the node.
        _mdagpath (om.MDagPath): The DAG path to the node.
        _node (om.MFnDependencyNode): A function set for the Maya node.
    """

    def __init__(self, node_name: str, warning: bool = True):
        """
        Initialize the ObjPointer with the given node name.

        Args:
            node_name (str): The name of the Maya node.
        """
        self.__dict__['_mobject'] = om.MObject()
        self.__dict__['_mdagpath'] = om.MDagPath()
        self.__dict__['_node'] = om.MFnDependencyNode()

        if not cmds.objExists(node_name):
            if warning:  # Only log if warning flag is True
                logger.error(f"Node '{node_name}' does not exist")
            return

        selection = om.MSelectionList()
        try:
            selection.add(node_name)
            selection.getDependNode(0, self.__dict__['_mobject'])
            self.__dict__['_node'] = om.MFnDependencyNode(self.__dict__['_mobject'])
            # Only try to get DAG path for DAG nodes
            if cmds.ls(node_name, dag=True):
                selection.getDagPath(0, self.__dict__['_mdagpath'], om.MObject())
        except Exception as e:
            if warning:
                logger.error(f"Failed to initialize {node_name}: {e}")

    def setDAG(self, node_name, warning:bool=True):
        """
        Set the DAG path for the given node name.

        This is used to reset or update the DAG path for the Maya node.

        Args:
            node_name (str): The name of the Maya node.
        """
        self.__dict__['_mobject'] = om.MObject()
        self.__dict__['_mdagpath'] = om.MDagPath()
        self.__dict__['_node'] = om.MFnDependencyNode()
        selection = om.MSelectionList()
        try:
            selection.add(node_name)
            selection.getDependNode(0, self.__dict__['_mobject'])
            self.__dict__['_node'] = om.MFnDependencyNode(self.__dict__['_mobject'])
            selection.getDagPath(0, self.__dict__['_mdagpath'], om.MObject())
        except Exception as e:
            if warning:
                logger.debug(f"Failed to initialize node {node_name}: {e}")

    def name(self, long: bool = False) -> str:
        """
        Get the name of the Maya node.

        Args:
            long (bool): If True, return the full DAG path; otherwise, return the partial path.

        Returns:
            str: The node's name, either as a full DAG path or a partial name.
        """
        if self.__dict__['_mdagpath'].isValid():
            if long:
                return self.__dict__['_mdagpath'].fullPathName()
            return self.__dict__['_mdagpath'].partialPathName()
        else:
            return self.__dict__['_node'].name() if not self.__dict__['_mobject'].isNull() else None
