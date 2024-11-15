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
from .dw_lsTr import lsTr


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

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


def test_if_inside_mesh(point: Tuple[float, float, float] = (0.0, 0.0, 0.0),
                        dir: Tuple[float, float, float] = (0.0, 0.0, 1.0),
                        mesh_name: str = "pTorusShape1",
                        accelerator: Optional[om.MMeshIsectAccelParams] = None) -> bool:
    """
    Check if a point is inside a given mesh by casting a ray and checking how many intersections it makes.

    Args:
        point (tuple of float): The starting point for the ray.
        dir (tuple of float): The direction of the ray.
        mesh_name (str): The name of the mesh to test against.
        accelerator (Optional[om.MMeshIsectAccelParams]): Optional mesh lookup accelerator for performance.

    Returns:
        bool: True if the point is inside the mesh (odd number of intersections), False otherwise.
    """
    # https://stackoverflow.com/questions/18135614/querying-of-a-point-is-within-a-mesh-maya-python-api

    # Create a selection list and get the mesh's DAG path
    sel = om.MSelectionList()
    dag = om.MDagPath()

    # Add the specified mesh
    sel.add(mesh_name)
    sel.getDagPath(0, dag)

    # Create MFnMesh object to interact with the mesh
    mesh = om.MFnMesh(dag)

    # Create the point and direction for raycasting
    point = om.MFloatPoint(*point)
    dir = om.MFloatVector(*dir)
    farray = om.MFloatPointArray()

    mesh.allIntersections(
        point, dir, # Ray origin and direction
        None, None, # No face/vertex exclusions
        False, om.MSpace.kWorld, # Not want backface culling and World space
        10000, # Maximum distance to search for intersections
        False,  # Test both directions of the ray
        accelerator,  # Optional mesh lookup accelerator
        False,  # Don't want to sort intersections
        farray,  # Output array for intersection points
        None, None,  # Not interested in the details (normals, ray params, etc.)
        None, None,
        None
    )
    return farray.length() % 2 == 1


def test(meshSrc, meshTarget):
    """
    Project the vertices from the source mesh onto the target mesh by casting rays
    from the source vertices in the direction of their normals to find the nearest intersection.
    http://www.fevrierdorian.com/blog/post/2011/07/31/Project-a-mesh-to-another-with-Maya-API-%28English-Translation%29#c3024

    Args:
        meshSrc (MDagPath): The DAG path of the source mesh.
        meshTarget (MDagPath): The DAG path of the target mesh.

    Returns:
        None: The function modifies the position of the source mesh vertices in-place.
    """
    # Initialize the mesh function sets for source and target meshes
    mFnMeshSrc = om.MFnMesh(meshSrc)
    mFnMeshTarget = om.MFnMesh(meshTarget)

    outMeshMPointArray = om.MPointArray()  # create an array of vertex wich will contain the outputMesh vertex
    mFnMeshSrc.getPoints(outMeshMPointArray)  # get the point in the space

    # get MDagPath of the MMesh to get the matrix and multiply vertex to it.
    # If I don't do that, all combined mesh will go to the origin
    inMeshSrcMDagPath = mFnMeshSrc.dagPath()  # return MDagPath object
    inMeshSrcInclusiveMMatrix = inMeshSrcMDagPath.inclusiveMatrix()  # return MMatrix

    # Loop through each vertex of the source mesh
    for i in range(outMeshMPointArray.length()):
        # Transform the source vertex into world space
        inMeshMPointTmp = outMeshMPointArray[i] * inMeshSrcInclusiveMMatrix

        # Ray source and direction
        raySource = om.MFloatPoint(inMeshMPointTmp.x, inMeshMPointTmp.y,
                                   inMeshMPointTmp.z)
        rayDirection = om.MVector()
        mFnMeshSrc.getVertexNormal(i, False, rayDirection)
        rayDirection *= inMeshSrcInclusiveMMatrix
        rayDirection = om.MFloatVector(rayDirection.x, rayDirection.y,
                                       rayDirection.z)

        # Set up intersection data
        hitPoint = om.MFloatPoint()

        # rest of the args
        hitFacePtr = om.MScriptUtil().asIntPtr() # This will store the face index hit by the ray
        idsSorted = False
        testBothDirections = False
        faceIds = None
        triIds = None
        accelParams = om.MMeshIsectAccelParams()  # Optional acceleration parameters added by ChatGPT
        hitRayParam = None
        hitTriangle = None
        hitBary1 = None
        hitBary2 = None
        maxParamPtr = 99999999 # Max distance for the ray intersection

        # http://zoomy.net/2009/07/31/fastidious-python-shrub/
        # Perform the intersection test
        hit = mFnMeshTarget.closestIntersection(
            raySource,
            rayDirection,
            None,  # No face or triangle exclusions
            None,
            idsSorted,
            om.MSpace.kWorld,
            maxParamPtr,
            testBothDirections,
            accelParams,
            hitPoint,
            None,  # Don't need the ray parameter for now
            hitFacePtr,
            None, None, None
        )

        # If a hit is found, update the source vertex position to the intersection point
        if hit:
            outMeshMPointArray[i] = om.MPoint(hitPoint.x, hitPoint.y, hitPoint.z)

        # Set the updated vertex positions back to the source mesh
        mFnMeshSrc.setPoints(outMeshMPointArray, om.MSpace.kWorld)


def get_closest_poly_from_transform(geo: str, loc: str):
    """
    Get the closest polygon (vertex) from a mesh based on a given transform or position.

    Args:
        geo (str): The name of the mesh object.
        loc (str or tuple): The name of the transform or a tuple of (x, y, z) coordinates.

    Returns:
        tuple: A tuple containing the closest vertex name and the position as (x, y, z).
    """
    geo = lsTr(geo, type='mesh', p=False)[0]
    name = lsTr(geo)[0]
    output = '{}.vtx[{{}}]'.format(name).format
    if isinstance(loc, str):
        pos = cmds.pointPosition(loc)
    else:
        pos = [loc[0], loc[1], loc[2]]

    # Initialize Maya API objects for working with the mesh
    nodeDagPath = om.MObject()
    try:
        selectionList = om.MSelectionList()
        selectionList.add(name)
        nodeDagPath = om.MDagPath()
        selectionList.getDagPath(0, nodeDagPath)
    except Exception as e:
        raise RuntimeError(f"OpenMaya.MDagPath() failed on {name}. \n {e}")

    # Create MFnMesh object for the mesh
    mfnMesh = om.MFnMesh(nodeDagPath)

    # Create points for querying the closest point
    pointA = om.MPoint(*pos)
    pointB = om.MPoint()
    space = om.MSpace.kWorld

    # Prepare to store the closest polygon index
    util = om.MScriptUtil()
    util.createFromInt(0)
    idPointer = util.asIntPtr()

    # Get the closest point on the mesh
    mfnMesh.getClosestPoint(pointA, pointB, space, idPointer)
    idx = om.MScriptUtil(idPointer).asInt()

    return output(idx), pos


def get_closest_vertex_from_transform(geo: str, loc: str):
    """Get closest vertex from transform
    Arguments:
        geo (dagNode or str): Mesh object
        loc (matrix): location transform
    Returns:
        Closest Vertex
    # >>> v = mn.get_closest_vertex_from_transform(geometry, joint)
    """
    # Ensure we are working with a valid mesh
    geo = lsTr(geo, type='mesh', p=False)[0]
    polygon, pos = get_closest_poly_from_transform(geo, loc)

    faceVerts = [geo.vtx[i] for i in polygon.getVertices()]
    closestVert = None
    minLength = None
    for v in faceVerts:
        thisLength = (pos - v.getPosition(space='world')).length()
        if minLength is None or thisLength < minLength:
            minLength = thisLength
            closestVert = v
    return closestVert


def select_in_cam_frustrum(cam: str) -> List[str]:
    """
    Select all objects within the camera frustum.

    Args:
        cam (str): The name of the camera.

    Returns:
        List[str]: A list of transform node names that are visible in the camera's view.
    """
    # Add camera to MDagPath.
    mdag_path = om.MDagPath()
    sel = om.MSelectionList()
    sel.add(cam)
    sel.getDagPath(0, mdag_path)

    # Create frustum object with camera.
    draw_traversal = omui.MDrawTraversal()
    draw_traversal.setFrustum(mdag_path,
                              cmds.getAttr("defaultResolution.width"),
                              cmds.getAttr(
                                  "defaultResolution.height"))  # Use render's resolution.
    draw_traversal.traverse()  # Traverse scene to get all objects in the camera's view.

    frustum_objs = []

    # Loop through objects within frustum.
    for i in range(draw_traversal.numberOfItems()):
        # It will return shapes at first, so we need to fetch its transform.
        shape_dag_path = om.MDagPath()
        draw_traversal.itemPath(i, shape_dag_path)
        transform_dag_path = om.MDagPath()
        om.MDagPath.getAPathTo(shape_dag_path.transform(), transform_dag_path)

        # Get object's long name and make sure it's a valid transform.
        obj = transform_dag_path.fullPathName()
        if cmds.objExists(obj):
            frustum_objs.append(obj)

    return frustum_objs


def find_mirror_edge(obj: str, edgeIndx: int):
    """Return the mirror edge of an edge
    Args:
        obj (PyNode or str): Mesh object to get the mirror edge
        edge (int): Index of the edge to find the mirror
    Returns:
        PyNode: Mirror edge as a pynode
    """
    obj = lsTr(obj, type='mesh', p=False)[0]
    name = lsTr(obj)[0]

    edge = name + ".e[{}]".format(str(edgeIndx))
    points = cmds.polyListComponentConversion(edge, tv=True)
    points = cmds.ls(points, fl=True)
    v1 = cmds.pointPosition(points[0])
    v2 = cmds.pointPosition(points[1])

    # mirror vectors in X axis
    mv1 = [v1[0] * -1, v1[1], v1[2]]
    mv2 = [v2[0] * -1, v2[1], v2[2]]

    vtx1 = get_closest_vertex_from_transform(obj,
                                             mv1)
    vtx2 = get_closest_vertex_from_transform(obj,
                                             mv2)
    for ee in vtx1.connectedEdges():
        if ee in vtx2.connectedEdges():
            return ee


def active_view_dimension() -> Tuple[int, int]:
    """
    Get the dimensions (width and height) of the active viewport in Maya.

    Returns:
        Tuple[int, int]: A tuple containing the width and height of the active viewport.
    """
    view = omui.M3dView.active3dView()
    width = view.portWidth()
    height = view.portHeight()
    return width, height


def select_from_screen(x: int, y: int, x_rect: Optional[int] = None, y_rect: Optional[int] = None) -> List[str]:
    """
    Find the object under the cursor in Maya's view, or within a rectangular selection area.
    found here: http://nathanhorne.com/maya-python-selectfromscreen/

    Args:
        x (int): Rectangle selection start x or single-point x.
        y (int): Rectangle selection start y or single-point y.
        x_rect (int, optional): Rectangle selection end x. Defaults to None for single-point selection.
        y_rect (int, optional): Rectangle selection end y. Defaults to None for single-point selection.

    Returns:
        List[str]: Names of the objects under the cursor or in the rectangular area.
    """
    # get current selection
    sel = om.MSelectionList()
    om.MGlobal.getActiveSelectionList(sel)

    # select from screen
    if x_rect is not None and y_rect is not None:
        # Rectangular selection
        om.MGlobal.selectFromScreen(
            x, y, x_rect, y_rect, om.MGlobal.kReplaceList)
    else:
        # Single-point selection
        om.MGlobal.selectFromScreen(x, y, om.MGlobal.kReplaceList)

    # Get the selected objects
    objects = om.MSelectionList()
    om.MGlobal.getActiveSelectionList(objects)

    # restore selection
    om.MGlobal.setActiveSelectionList(sel, om.MGlobal.kReplaceList)

    # return the objects as strings
    fromScreen = []
    objects.getSelectionStrings(fromScreen)
    return fromScreen