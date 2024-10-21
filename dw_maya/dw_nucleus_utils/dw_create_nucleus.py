import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import maya.cmds as cmds


def create_nucleus(name=None, parent=None):
    """
    Create a nucleus node in Maya, connect it to the time node, and set up basic connections.

    Args:
        name (str, optional): Desired name for the nucleus node. Defaults to None.
        parent (str, optional): Parent node for the nucleus. Defaults to None.

    Returns:
        str: The name of the created or existing nucleus node.
    """
    maya_kwargs = {}

    if name:
        maya_kwargs['name'] = name
    else:
        maya_kwargs['name'] = 'nucleus01'  # Default name if none is provided

    if parent:
        maya_kwargs['parent'] = parent

    # Check if the nucleus with the same name already exists
    if cmds.ls(maya_kwargs['name'], type="nucleus"):
        cmds.warning(f"Nucleus node '{maya_kwargs['name']}' already exists.")
        return maya_kwargs['name']

    # Create the nucleus node
    nucleus_node = cmds.createNode('nucleus', **maya_kwargs)

    # Connect the nucleus node to the time1 node
    cmds.connectAttr("time1.outTime", f"{nucleus_node}.currentTime")

    # Connect visibility to enable the nucleus
    cmds.connectAttr(f"{nucleus_node}.visibility", f"{nucleus_node}.enable")

    return nucleus_node
