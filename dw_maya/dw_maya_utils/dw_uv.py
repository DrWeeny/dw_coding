"""Provides utilities for UV coordinate operations in Maya.

A module focused on UV coordinate queries and manipulations, including
nearest point UV lookups and vertex-to-UV conversions.

Functions:
    get_vertex_uvs(): Get UV coordinates for vertices
    find_nearest_uvs(): Find nearest UV points on mesh
    get_closest_uv(): Get closest UV point to world position

Main Features:
    - Vertex to UV mapping
    - Nearest point UV queries
    - World space to UV space conversion
    - Multi-mesh UV point finding
    - Batch UV coordinate processing

Version: 1.0.0

Author:
    DrWeeny
"""

from typing import List, Union, Tuple, Optional, Dict, Any
from dataclasses import dataclass

from maya import cmds
import maya.OpenMaya as om

from dw_maya.dw_decorators import acceptString, load_plugin
from .dw_maya_components import mag
from .dw_maya_data import flags
from dw_logger import get_logger

logger = get_logger()

@dataclass
class UVPoint:
    """Represents a UV coordinate pair."""
    u: float
    v: float

    def to_list(self) -> List[float]:
        """Convert to list format."""
        return [self.u, self.v]


@dataclass
class MeshUVResult:
    """Container for UV query results.

    A dataclass storing UV-related query results with automatic
    value retrieval via __get__ method.

    Args:
        mesh_name: Name of the queried mesh
        uv_coords: UV coordinates as UVPoint
        position: World space position
        face_index: Face index on mesh
        distance: Distance to query point

    Example:
        >>> result = MeshUVResult("pSphere1", UVPoint(0.5, 0.5))
        >>> result()  # Returns UVPoint(0.5, 0.5)
        >>> result = MeshUVResult("pSphere1", None, [0, 1, 0])
        >>> result()  # Returns [0, 1, 0]
    """
    mesh_name: str
    uv_coords: Optional[UVPoint] = None
    position: Optional[List[float]] = None
    face_index: Optional[int] = None
    distance: Optional[float] = None

    def __call__(self) -> Any:
        """Return first non-None value except mesh_name.

        Returns:
            First available value from: uv_coords, position, face_index, or distance

        Raises:
            ValueError: If all values except mesh_name are None
        """
        for attr in ['uv_coords', 'position', 'face_index', 'distance']:
            value = getattr(self, attr)
            if value is not None:
                return value
        raise ValueError("No valid data found in result")


def get_uv_from_vtx(vertex: str,
                    return_map_index: bool = False) -> Union[List[float], List[str]]:
    """Get UV coordinates or map indices for a vertex.

    Args:
        vertex: Vertex to query (e.g., "pSphere1.vtx[0]")
        return_map_index: Return UV map index instead of coordinates

    Returns:
        UV coordinates [u, v] or UV map indices

    Raises:
        RuntimeError: If vertex doesn't exist or has no UVs
    """
    # Convert the vertex to its corresponding UV map
    vtx_map = cmds.polyListComponentConversion(vertex, tuv=True)

    # If get_map_index is True, return the map index directly
    if return_map_index:
        return vtx_map
    # Query the UV coordinates
    uv_coords = cmds.polyEditUV(vtx_map, query=True)
    # If more than two UV values are returned, slice to get only the first two (U and V coordinates)
    return uv_coords[:2] if len(uv_coords) > 2 else uv_coords


@load_plugin('nearestPointOnMesh')
@acceptString('targetMesh', 'points')
def nearest_uv_on_mesh(target_mesh: Union[str, List[str]],
                       points: List[Union[str, List[float]]],
                       **kwargs) -> List[MeshUVResult]:
    """Find nearest UV coordinates and related data between points and mesh.

    Args:
        target_mesh: Target mesh(es) for UV queries
        points: Points to find nearest UVs for
        uvs: Include UV coordinates in results
        position: Include world positions in results
        face: Include face indices in results
        distance: Include distances in results

    Returns:
        List of MeshUVResult objects containing requested data

    Web Source:
        Internal algorithm adapted from: http://tech-artists.org/t/fastest-way-to-get-closest-uv-point/5163
    """

    # Parse the flags
    ouv = flags(kwargs, None, 'uvs', 'uv')
    opos = flags(kwargs, None, 'position', 'pos')
    oface = flags(kwargs, None, 'face', 'f')
    odist = flags(kwargs, None, 'distance', 'd')

    # Process input points
    point_positions = []
    for point in points:
        try:
            if isinstance(point, str):
                pos = cmds.pointPosition(point)
            elif isinstance(point, (list, tuple)) and len(point) == 3:
                pos = point
            else:
                raise ValueError(f"Invalid point format: {point}")
            point_positions.append(pos)
        except Exception as e:
            logger.warning(f"Skipping invalid point {point}: {e}")

    # Create temporary nodes
    temp_nodes = []
    mesh_shapes = {}

    for mesh in target_mesh:
        node_name = f'nearestPoint_{mesh}_temp'
        if cmds.objExists(node_name):
            temp_nodes.append(node_name)
            continue

        # Get mesh shape
        if cmds.nodeType(mesh) == 'transform':
            shape = cmds.listRelatives(mesh, noIntermediate=True,
                                       type='mesh')[0]
        else:
            shape = mesh

        mesh_shapes[node_name] = shape

        # Create node
        node = cmds.createNode('nearestPointOnMesh', name=node_name)
        cmds.connectAttr(f"{shape}.worldMesh", f"{node}.inMesh")
        temp_nodes.append(node)

    # Process each point
    results = []
    for pos in point_positions:
        best_result = MeshUVResult(mesh_name="")
        min_distance = float('inf')

        # Check against each mesh
        for node in temp_nodes:
            cmds.setAttr(f"{node}.inPosition", type='double3', *pos)
            curr_pos = cmds.getAttr(f"{node}.position")[0]
            curr_u = cmds.getAttr(f"{node}.u")
            curr_v = cmds.getAttr(f"{node}.v")
            curr_dist = mag(pos, curr_pos)

            if curr_dist < min_distance:
                min_distance = curr_dist
                mesh_name = cmds.listConnections(f"{node}.inMesh")[0]

                best_result = MeshUVResult(
                    mesh_name=mesh_name,
                    uv_coords=UVPoint(curr_u, curr_v) if ouv else None,
                    position=curr_pos if opos else None,
                    face_index=cmds.getAttr(f"{node}.nearestFaceIndex")
                    if oface else None,
                    distance=curr_dist if odist else None
                )

        results.append(best_result)

    # Clean up created nodes
    cmds.delete(temp_nodes)
    return results


def closest_uv_on_mesh(shape: str,
                       position: Union[List[float], om.MPoint]) -> UVPoint:
    """Get UV coordinates closest to world position.

    Args:
        shape: Mesh shape node name
        position: World position to query

    Returns:
        UVPoint containing closest UV coordinates

    Raises:
        RuntimeError: If shape doesn't exist or position is invalid
    """
    sel_list = om.MSelectionList()
    sel_list.add(shape)
    dag_path = om.MDagPath()
    componentMObject = om.MObject()

    # Retrieve the mesh's DAG path
    sel_list.getDagPath(0, dag_path, componentMObject)
    mesh_fn = om.MFnMesh(dag_path)

    # Convert the position to MPoint if necessary
    if isinstance(position, om.MPoint):
        point  = position
    else:
        point  = om.MPoint(*position)

    # Create a float2 array to hold the UV values
    util = om.MScriptUtil()
    util.createFromList([0.0, 0.0], 2)
    uv_ptr = util.asFloat2Ptr()

    # Get the UV at the closest point on the mesh
    mesh_fn.getUVAtPoint(point , uv_ptr, om.MSpace.kWorld)

    # Extract the UV values from the float2 array
    u = om.MScriptUtil.getFloat2ArrayItem(uv_ptr, 0, 0)
    v = om.MScriptUtil.getFloat2ArrayItem(uv_ptr, 0, 1)

    # Return UV as a list [u, v]
    return UVPoint(u, v)

@acceptString("obj")
def move_uv_to_pos(obj:str=None, u:int=None, v:int=None):
    """ polyEditUV doesn't set the uv values to a location but move the coordinate from a value
    In order to set the u and v, we have to calculate the relative current position to move them to the set place

    # https://forums.autodesk.com/t5/maya-programming/change-object-u-v-position-by-python/td-p/10868797"""

    # getting selection
    if not obj:
        obj = cmds.ls(selection=True)
    obj = obj[0]
    if '.' in obj:
        obj = obj.split('.')[0]

    shape = cmds.listRelatives(obj, s=True)
    # get total number of UV's
    num_uv = cmds.polyEvaluate(obj, uv=True)
    # selecting UV's to assure UVPivot position
    cmds.select('{0}.map[0:{1}]'.format(obj, num_uv))
    # getting current uvPivot position
    uvp = cmds.getAttr('{0}.uvPivot'.format(shape[0]))
    # calculating distance that needs to be moved
    u_new = uvp[0][0] - u
    v_ew = uvp[0][1] - v
    # moving UV's and uvPivot
    cmds.polyEditUV('{0}.map[0:{1}]'.format(obj, num_uv), relative=True, u=u_new * (-1), v=v_ew * (-1))
    cmds.setAttr('{0}.uvPivot'.format(shape[0]), u, v)
