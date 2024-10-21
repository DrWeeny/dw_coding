import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
import re
from dw_maya.dw_decorators import load_plugin

import sys
import os
import maya.cmds as cmds
import re
from dw_maya.dw_decorators import load_plugin


@load_plugin("MayaMuscle")
def cMuscleSurfAttachSetup(sels, type='mesh', autoGroup=1):
    """
    Create a rivet using Maya's cMuscleSurfAttach node.

    This function creates a rivet based on the selection of either one face or two edges.
    It creates a 'cMuscleSurfAttach' node and connects it to the selected mesh. The
    function groups the created node automatically if specified.

    Args:
        sels (list): A list of selected components (either one face or two edges).
        type (str): The type of geometry ('mesh' or 'other'). Default is 'mesh'.
        autoGroup (int): If 1, automatically group the created rivets. Default is 1.

    Returns:
        list: The transform nodes created by the cMuscleSurfAttach node.
    """

    # Ensure the input is valid
    sels = cmds.ls(sels, fl=True)
    nSels = len(sels)
    sel = sels[0]

    # Check selection validity
    if nSels == 1:
        myRegFace = '^' + sel.split('.')[0] + r'\.f\[\d+\]$'  # regex to check if it's a face
        if not re.compile(myRegFace).match(sel):
            cmds.error('Select one face or two edges.')
    elif nSels == 2:
        myRegEdge = '^' + sel.split('.')[0] + r'\.e\[\d+\]$'  # regex to check if it's edges
        if not all(re.compile(myRegEdge).match(edge) for edge in sels):
            cmds.error('Select one face or two edges.')
    else:
        cmds.error('Select one face or two edges.')

    # Create the muscle attachment node and apply the relevant logic
    return _create(sels, type, autoGroup)


def _create_unique_node():
    """
    Create a unique cMuscleSurfAttach node with an incrementing suffix if needed.

    Returns:
        str: The name of the created node.
    """
    try:
        existing_nodes = [int(i.replace("cMuscleSurfAttachShape", "")) for i in
                          cmds.ls("cMuscleSurfAttach*", type='cMuscleSurfAttach')]
        existing_nodes.sort()
        nb = existing_nodes[-1]
    except (ValueError, IndexError):
        nb = 0
    node = cmds.createNode("cMuscleSurfAttach", n=f"cMuscleSurfAttachShape{nb + 1}")
    return node


def _create(edges, geometry_type, autoGroup):
    """
    Create a cMuscleSurfAttach node from two edge selections.

    Args:
        edges (list): The selected edges.
        geometry_type (str): The type of geometry.
        autoGroup (int): Whether to group the created nodes.

    Returns:
        list: The transform nodes created.
    """
    obj = edges[0].split('.')[0]
    myRegFace = '^' + obj.split('.')[0] + '.f[[]\d+[]]$'
    if re.compile(myRegFace).match(obj):
        # Get the edges of the selected face
        edges = cmds.polyInfo(obj, faceToEdge=True)[0].split(":")[1].split()
        idx1, idx2 = int(edges[0]), int(edges[2])
    else:
        idx1, idx2 = [int(edge.split('.')[-1].replace('e[', '').replace(']', '')) for edge in edges]

    # Create the muscle attachment node
    node = _create_unique_node()
    xforms = cmds.listRelatives(node, parent=True)
    xform = xforms[0]

    if geometry_type == 'mesh':
        cmds.connectAttr(f"{obj}.worldMesh[0]", f"{node}.inputData.surfIn", force=True)
    else:
        obj = cmds.listConnections(f"{obj}.inMesh", shapes=True)[0]
        cmds.setAttr(f"{xform}.visibility", 0)
        cmds.connectAttr(f"{obj}.outputGeometry[0]", f"{node}.inputData.surfIn", force=True)

    cmds.connectAttr(f"{xform}.rotateOrder", f"{node}.inRotOrder", force=True)

    cmds.setAttr(f"{node}.uLoc", 0.5)
    cmds.setAttr(f"{node}.vLoc", 0.5)
    cmds.setAttr(f"{node}.edgeIdx1", idx1)
    cmds.setAttr(f"{node}.edgeIdx2", idx2)

    cmds.connectAttr(f"{node}.outTranslate", f"{xform}.translate", force=True)
    cmds.connectAttr(f"{node}.outRotate", f"{xform}.rotate", force=True)

    # Group the rivet for rigging
    _group_rivet(xform, autoGroup)

    print("Rivet has been created from edges")
    return xforms


def _group_rivet(xform, autoGroup):
    """
    Group the created rivet under the 'grpSurfAttachRIG' group if specified.

    Args:
        xform (str): The transform node of the rivet.
        autoGroup (int): Whether to group the rivet.
    """
    if not cmds.objExists("grpSurfAttachRIG") and autoGroup:
        cmds.group(name="grpSurfAttachRIG", world=True, empty=True)
        cmds.setAttr("grpSurfAttachRIG.inheritsTransform", 0)

    cmds.setAttr(f"{xform}.inheritsTransform", 0)
    if autoGroup:
        cmds.parent(xform, "grpSurfAttachRIG")

