import maya.cmds as cmds

import importlib
from dw_logger import get_logger

logger = get_logger()


class NodeClassLoadError(Exception):
    """Custom exception for node class loading failures"""
    pass


def getTypeClass():
    """
    Retrieve a mapping of node types to their corresponding classes.
    Includes error logging for failed imports.

    Returns:
        dict: Mapping of node types to their classes

    Raises:
        NodeClassLoadError: If critical classes fail to load
    """
    type_mapping = {
        'nComponent': 'dw_maya.dw_nucleus_utils.nComponent',
        'dynamicConstraint': 'dw_maya.dw_nucleus_utils.nConstraint',
        'default': 'dw_maya.dw_maya_nodes.MayaNode'
    }

    node_classes = {}
    failed_imports = []

    for node_type, class_path in type_mapping.items():
        try:
            module_path, class_name = class_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            node_classes[node_type] = getattr(module, class_name)
            logger.debug(f"Successfully loaded {class_path} for {node_type}")
        except ImportError as e:
            failed_imports.append((node_type, class_path, str(e)))
            logger.error(f"Failed to import {class_path} for {node_type}: {e}")
        except AttributeError as e:
            failed_imports.append((node_type, class_path, str(e)))
            logger.error(f"Class {class_name} not found in {module_path}: {e}")

    # Check if default class loaded
    if 'default' not in node_classes:
        error_msg = f"Failed to load critical default class. Import failures: {failed_imports}"
        logger.critical(error_msg)
        raise NodeClassLoadError(error_msg)

    return node_classes


def lsNode(*args, **kwargs):
    """
    List Maya nodes as Python objects with error logging.

    Args:
        *args: Arguments for cmds.ls
        **kwargs: Keyword arguments for cmds.ls

    Returns:
        list:
    """
    output = []
    try:
        node_classes = getTypeClass()
    except NodeClassLoadError as e:
        logger.critical(f"Failed to initialize node classes: {e}")
        return output

    # Retrieve nodes using Maya cmds.ls
    nodes = cmds.ls(*args, **kwargs)
    if not nodes:
        return output

    # For each node, determine its type and create the appropriate object
    for node in nodes:
        node_type = cmds.nodeType(node)
        node_class = node_classes.get(node_type, node_classes['default'])
        try:
            output.append(node_class(node))
        except Exception as e:
            print(f"Error instantiating {node_class} for node '{node}': {e}")
            output.append(node_classes['default'](node))  # Fallback to default

    return output
