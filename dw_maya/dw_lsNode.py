import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

import maya.cmds as cmds

import importlib


def getTypeClass():
    """
    Retrieve a mapping of node types to their corresponding classes.
    This function can be extended by updating the dictionary or by using dynamic imports.

    Returns:
        dict: A dictionary mapping node types (str) to their corresponding classes.
    """
    type_mapping = {
        'nComponent': 'dw_maya.dw_nucleus_utils.nComponent',
        'dynamicConstraint': 'dw_maya.dw_nucleus_utils.nConstraint',
        'default': 'dw_maya.dw_maya_nodes.MayaNode'
    }

    # Dynamically import classes based on the dictionary values
    node_classes = {}
    for node_type, class_path in type_mapping.items():
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        node_classes[node_type] = getattr(module, class_name)

    return node_classes


def lsNode(*args, **kwargs):
    """
    Custom `ls` function that returns Python objects instead of node names.

    Args:
        *args: Arguments to pass to `cmds.ls`.
        **kwargs: Keyword arguments to pass to `cmds.ls`.

    Returns:
        list: A list of instantiated objects corresponding to the Maya nodes.
    """
    output = []
    node_classes = getTypeClass()

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
