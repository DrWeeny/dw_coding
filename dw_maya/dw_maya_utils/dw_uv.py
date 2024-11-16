#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#

# built-in
import sys, os
from typing import List, Union, Optional, Tuple

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools\\'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

# internal
from maya import cmds, mel
import maya.OpenMaya as om
import maya.OpenMayaUI as omui

# external
from dw_maya.dw_decorators import acceptString, load_plugin
from .dw_maya_components import mag
from .dw_maya_data import Flags

def get_uv_from_vtx(vertex, get_map_index=False):
    """
    Retrieves the UV map information for a given vertex.

    Args:
        vertex (str): The vertex for which the UV map is queried.
        get_map_index (bool, optional): If True, returns the UV map index instead of UV coordinates. Default is False.

    Returns:
        list or str: If get_map_index is True, returns the UV map index; otherwise, returns the UV coordinates.
    """
    # Convert the vertex to its corresponding UV map
    vtx_map = cmds.polyListComponentConversion(vertex, tuv=True)

    # If get_map_index is True, return the map index directly
    if get_map_index:
        return vtx_map
    # Query the UV coordinates
    uv_coords = cmds.polyEditUV(vtx_map, query=True)
    # If more than two UV values are returned, slice to get only the first two (U and V coordinates)
    if len(uv_coords) > 2:
        return uv_coords[:2]
    return uv_coords

@load_plugin('nearestPointOnMesh')
@acceptString('targetMesh', 'points')
def nearest_uv_on_mesh(targetMesh: Union[str, List[str]],
                       points: List[Union[str, List[float]]],
                       **kwargs) -> List:
    """
    Find the nearest UV coordinates, world space positions, face indices, or distances
    between a list of points and the nearest point on a given mesh (or list of meshes).

    Args:
        targetMesh (str or list of str): Mesh or list of meshes to query.
        points (list of str or list of lists): Points to project onto the mesh.
        **kwargs: Additional flags to control output:
                  - uvs or uv: Return nearest UVs.
                  - position or pos: Return nearest world space positions.
                  - face or f: Return the face index of the nearest point.
                  - distance or d: Return the distance to the nearest point.

    Returns:
        list: List of nearest UVs, positions, face indices, or distances depending on the flags.
    """

    # Parse the flags
    ouv = Flags(kwargs, None, 'uvs', 'uv')
    opos = Flags(kwargs, None, 'position', 'pos')
    oface = Flags(kwargs, None, 'face', 'f')
    odist = Flags(kwargs, None, 'distance', 'd')

    # check input is point position
    pos_list = []
    debug = []
    for p in points:
        try:
            pos = cmds.pointPosition(p)
            pos_list.append(pos)
        except:
            # check if p is already an array of 3 points
            if isinstance(p, (list, tuple)):
                if len(p) == 3:
                    if all(isinstance(x, (int, float)) for x in p):
                        pos_list.append(p)
                    else:
                        debug.append(p)
                else:
                    debug.append(p)
            else:
                debug.append(p)
    if debug:
        t = 'bad data detected for `points` variable, '
        t += 'please inputs that can be evaluate :\n'
        t += 'by `cmds.poinPoistion` '
        t += 'or being a <list> of position `[[0,1,0],[1,.1,.5],[0,0,0]]`\n'
        t += 'detected : {}'.format(' '.join(debug))
        cmds.error(t)

    # Create nearestPointOnMesh nodes and connect them to the target meshes
    nearestNodes = []
    for m in targetMesh:
        name = f'nrstPoM_{m}_dwtmp'

        if not cmds.objExists(name):
            if cmds.nodeType(m) == 'transform':
                objShape = cmds.listRelatives(m, ni=True, type='mesh')[0]
            else:
                objShape = m
            node = cmds.createNode('nearestPointOnMesh', name=name)
            nearestNodes.append(node)
            cmds.connectAttr(objShape + ".worldMesh", node + ".inMesh")
        elif cmds.objExists(name):
            nearestNodes.append(name)

    # Process each point and find the nearest details based on the flags
    output = []
    for pos in pos_list:
        u, v, outUV = 0, 0, []
        tmp = 10000000000
        for nPoM in nearestNodes:
            cmds.setAttr(nPoM + ".inPosition", type='double3', *pos)
            target_pos = cmds.getAttr(nPoM + '.position')[0]
            target_u = cmds.getAttr(nPoM + '.u')
            target_v = cmds.getAttr(nPoM + '.v')
            dist = mag(pos, target_pos)
            if dist < tmp:
                u = target_u
                v = target_v
                face = cmds.getAttr(nPoM + ".nearestFaceIndex")
                tmp = dist
                tpos = target_pos
                inmesh = cmds.listConnections(nPoM + '.inMesh')[0]

        if ouv:
            output.append([inmesh, [u, v]])
        elif opos:
            output.append([inmesh, tpos])
        elif oface:
            output.append([inmesh, face])
        elif odist:
            output.append([inmesh, tmp])
        tmp = 10000000000

    # Clean up created nodes
    cmds.delete(nearestNodes)
    return output


def closest_uv_on_mesh(shape: str, position: List[int]):
    """
    Get the UV coordinates closest to a given world position on a mesh.

    Args:
        shape (str): The name of the mesh shape node.
        position (list or MPoint): The world position as [x, y, z] or an MPoint object.

    Returns:
        list: The UV coordinates [u, v] closest to the given position.
    """
    selMSelectionList = om.MSelectionList()
    selMSelectionList.add(shape)
    dagPathMDagPath = om.MDagPath()
    componentMObject = om.MObject()

    # Retrieve the mesh's DAG path
    selMSelectionList.getDagPath(0, dagPathMDagPath, componentMObject)
    meshFn = om.MFnMesh(dagPathMDagPath)

    # Convert the position to MPoint if necessary
    if isinstance(position, om.MPoint):
        posMPoint = position
    else:
        posMPoint = om.MPoint(*position)

    # Create a float2 array to hold the UV values
    util = om.MScriptUtil()
    util.createFromList([0.0, 0.0], 2)
    float2ArrayPtr = util.asFloat2Ptr()

    # Get the UV at the closest point on the mesh
    meshFn.getUVAtPoint(posMPoint, float2ArrayPtr, om.MSpace.kWorld)

    # Extract the UV values from the float2 array
    uVal = om.MScriptUtil.getFloat2ArrayItem(float2ArrayPtr, 0, 0)
    vVal = om.MScriptUtil.getFloat2ArrayItem(float2ArrayPtr, 0, 1)

    # Return UV as a list [u, v]
    return [uVal, vVal]
