import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
import dw_maya.dw_maya_nodes as dwnode
import dw_maya.dw_nucleus_utils as dwnx
import dw_maya.dw_maya_utils as dwu

def getTypeClass():
    myTypes = {'nComponent':dwnx.nComponent,
               'default': dwnode.MayaNode,
               'dynamicConstraint':dwnx.nConstraint}
    return myTypes


def lsNode(*args, **kwargs):
    """
    Custom ls function that returns Python objects instead of node names.
    Args:
        *args: Arguments to pass to cmds.ls.
        **kwargs: Keyword arguments to pass to cmds.ls.

    Returns:
        list: A list of objects corresponding to the node types or default MayaNode objects.
    """
    output = []
    node_classes = getTypeClass()

    # Retrieve nodes using Maya cmds.ls
    nodes = cmds.ls(*args, **kwargs)

    if not nodes:
        return output

    # For each node, determine its type and create the appropriate object
    for node in nodes:
        node_class = node_classes.get(cmds.nodeType(node), node_classes['default'])
        output.append(node_class(node))

    return output
