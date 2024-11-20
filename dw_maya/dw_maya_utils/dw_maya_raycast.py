"""Provides utilities for raycasting, mesh intersection, and viewport selection in Maya.

A comprehensive module for performing raycast operations, mesh intersection tests,
and viewport-based selections. Includes utilities for point-in-mesh testing,
mesh projection, and camera frustum queries.

Functions:
    is_point_inside_mesh(): Test if a point is inside a mesh
    project_mesh(): Project vertices from source mesh onto target mesh
    get_closest_polygon(): Get closest polygon to a point or transform
    get_closest_vertex(): Get closest vertex to a point or transform
    get_visible_in_camera(): Get objects visible in camera frustum
    get_mirror_edge(): Find mirror edge across X axis
    get_viewport_size(): Get active viewport dimensions
    select_from_screen_coords(): Select objects from screen coordinates

Main Features:
    - Point in mesh testing using raycasting
    - Mesh-to-mesh vertex projection
    - Closest point/vertex finding on meshes
    - Camera frustum object queries
    - Screen-space selection utilities
    - Viewport dimension queries
    - Edge mirroring detection

Version: 1.0.0

Author:
    DrWeeny
"""

import sys
from typing import List, Union, Optional, Tuple, Any
from dataclasses import dataclass

from maya import cmds, mel
import maya.OpenMaya as om
import maya.OpenMayaUI as omui

from .dw_maya_message import message, warning, error
from .dw_lsTr import lsTr
from dw_logger import get_logger

logger = get_logger()


@dataclass
class Point3D:
    """Represents a 3D point or vector."""
    x: float
    y: float
    z: float

    def to_tuple(self) -> Tuple[float, float, float]:
        """Convert point to tuple."""
        return (self.x, self.y, self.z)

    @classmethod
    def from_transform(cls, transform: str) -> 'Point3D':
        """Create Point3D from Maya transform."""
        pos = cmds.pointPosition(transform)
        return cls(pos[0], pos[1], pos[2])


def is_point_inside_mesh(point: Union[Tuple[float, float, float], Point3D],
                         mesh_name: str,
                         direction: Union[Tuple[float, float, float], Point3D] = (0.0, 0.0, 1.0),
                         accelerator: Optional[om.MMeshIsectAccelParams] = None) -> bool:
    """Test if a point lies inside a mesh using raycasting.

    Source :
    https://stackoverflow.com/questions/18135614/querying-of-a-point-is-within-a-mesh-maya-python-api

    Args:
        point: Point to test
        mesh_name: Target mesh name
        direction: Ray direction for intersection test
        accelerator: Optional acceleration structure for performance

    Returns:
        bool: True if point is inside mesh (odd number of intersections)
    """

    if isinstance(point, Point3D):
        point = point.to_tuple()
    if isinstance(direction, Point3D):
        direction = direction.to_tuple()

    try:
        # Get mesh's DAG path
        sel = om.MSelectionList()
        dag = om.MDagPath()
        sel.add(mesh_name)
        sel.getDagPath(0, dag)

        mesh = om.MFnMesh(dag)
        point = om.MFloatPoint(*point)
        direction = om.MFloatVector(*direction)
        intersections = om.MFloatPointArray()

        mesh.allIntersections(
            point, direction,
            None, None,  # No face/vertex exclusions
            False, om.MSpace.kWorld,
            10000,  # Max distance
            False,  # Test both directions
            accelerator,
            False,  # Don't sort
            intersections,
            None, None, None, None, None
        )

        return intersections.length() % 2 == 1

    except Exception as e:
        logger.error(f"Error testing point inside mesh: {e}")
        return False


def project_mesh(source_mesh: str,
                 target_mesh: str,
                use_vertex_normals: bool = True) -> None:
    """Project vertices from source mesh onto target mesh.

    Source:
    http://www.fevrierdorian.com/blog/post/2011/07/31/Project-a-mesh-to-another-with-Maya-API-%28English-Translation%29#c3024


    Args:
        source_mesh: Mesh to project
        target_mesh: Surface to project onto
        use_vertex_normals: Use vertex normals for projection direction
    """
    try:
        # Get mesh DAG paths
        sel = om.MSelectionList()
        src_dag = om.MDagPath()
        tgt_dag = om.MDagPath()

        sel.add(source_mesh)
        sel.add(target_mesh)
        sel.getDagPath(0, src_dag)
        sel.getDagPath(1, tgt_dag)

        # Initialize function sets
        src_fn = om.MFnMesh(src_dag)
        tgt_fn = om.MFnMesh(tgt_dag)

        # Get source points and transform
        points = om.MPointArray()
        src_fn.getPoints(points)
        src_matrix = src_dag.inclusiveMatrix()

        # Project each vertex
        accel_params = om.MMeshIsectAccelParams()
        for i in range(points.length()):
            # Transform point to world space
            world_point = points[i] * src_matrix

            # Get projection direction
            if use_vertex_normals:
                normal = om.MVector()
                src_fn.getVertexNormal(i, False, normal)
                direction = normal * src_matrix
            else:
                direction = om.MVector(0, 1, 0)  # Default up direction

            # Setup intersection test
            ray_source = om.MFloatPoint(world_point.x, world_point.y, world_point.z)
            ray_direction = om.MFloatVector(direction.x, direction.y, direction.z)
            hit_point = om.MFloatPoint()

            # Find intersection
            hit = tgt_fn.closestIntersection(
                ray_source, ray_direction,
                None, None,  # No face exclusions
                False,  # Unsorted
                om.MSpace.kWorld,
                99999,  # Max distance
                False,  # Single direction
                accel_params,
                hit_point,
                None, None, None, None, None
            )

            if hit:
                points.set(om.MPoint(hit_point.x, hit_point.y, hit_point.z), i)

        # Update source mesh
        src_fn.setPoints(points)
        src_fn.updateSurface()

        logger.info(f"Successfully projected {source_mesh} onto {target_mesh}")

    except Exception as e:
        logger.error(f"Error projecting mesh: {e}")
        raise


def get_closest_polygon(
        mesh: str,
        target: Union[str, Tuple[float, float, float], Point3D]
) -> Tuple[str, Point3D]:
    """Get closest polygon on mesh to target position.

    Args:
        mesh: Source mesh name
        target: Target transform name or position

    Returns:
        Tuple containing polygon name and position
    """
    # Convert input position
    if isinstance(target, str):
        position = Point3D.from_transform(target)
    elif isinstance(target, tuple):
        position = Point3D(*target)
    else:
        position = target

    try:
        mesh = lsTr(mesh, type='mesh', p=False)[0]
        mesh_name = lsTr(mesh)[0]

        # Get mesh DAG path
        sel = om.MSelectionList()
        dag = om.MDagPath()
        sel.add(mesh_name)
        sel.getDagPath(0, dag)

        # Find closest point
        mesh_fn = om.MFnMesh(dag)
        point = om.MPoint(*position.to_tuple())
        closest = om.MPoint()

        util = om.MScriptUtil()
        util.createFromInt(0)
        face_idx = util.asIntPtr()

        mesh_fn.getClosestPoint(point, closest, om.MSpace.kWorld, face_idx)
        idx = om.MScriptUtil(face_idx).asInt()

        return f"{mesh_name}.f[{idx}]", position

    except Exception as e:
        logger.error(f"Error finding closest polygon: {e}")
        raise


def get_viewport_size() -> Tuple[int, int]:
    """Get dimensions of active viewport.

    Returns:
        Tuple of viewport width and height
    """
    try:
        view = omui.M3dView.active3dView()
        return view.portWidth(), view.portHeight()
    except Exception as e:
        logger.error(f"Error getting viewport size: {e}")
        raise


def get_visible_in_camera(camera: str) -> List[str]:
    """Get all objects visible in camera frustum.

    Args:
        camera: Camera transform name

    Returns:
        List of visible object names
    """
    try:
        # Get camera DAG path
        sel = om.MSelectionList()
        dag = om.MDagPath()
        sel.add(camera)
        sel.getDagPath(0, dag)

        # Setup frustum traversal
        traversal = omui.MDrawTraversal()
        traversal.setFrustum(
            dag,
            cmds.getAttr("defaultResolution.width"),
            cmds.getAttr("defaultResolution.height")
        )
        traversal.traverse()

        # Collect visible objects
        visible = []
        for i in range(traversal.numberOfItems()):
            shape_path = om.MDagPath()
            traversal.itemPath(i, shape_path)

            transform_path = om.MDagPath()
            om.MDagPath.getAPathTo(shape_path.transform(), transform_path)

            obj = transform_path.fullPathName()
            if cmds.objExists(obj):
                visible.append(obj)

        return visible

    except Exception as e:
        logger.error(f"Error getting visible objects: {e}")
        return []


def select_from_screen(
        x: int,
        y: int,
        x2: Optional[int] = None,
        y2: Optional[int] = None
) -> List[str]:
    """Select objects from screen coordinates.

    Args:
        x: Start X coordinate
        y: Start Y coordinate
        x2: Optional end X for rectangle select
        y2: Optional end Y for rectangle select

    Returns:
        List of selected object names
    """
    try:
        # Store current selection
        orig_sel = om.MSelectionList()
        om.MGlobal.getActiveSelectionList(orig_sel)

        # Perform screen selection
        if x2 is not None and y2 is not None:
            om.MGlobal.selectFromScreen(
                x, y, x2, y2,
                om.MGlobal.kReplaceList
            )
        else:
            om.MGlobal.selectFromScreen(
                x, y,
                om.MGlobal.kReplaceList
            )

        # Get selected objects
        screen_sel = om.MSelectionList()
        om.MGlobal.getActiveSelectionList(screen_sel)

        # Restore original selection
        om.MGlobal.setActiveSelectionList(orig_sel)

        # Convert to strings
        result = []
        screen_sel.getSelectionStrings(result)
        return result

    except Exception as e:
        logger.error(f"Error selecting from screen: {e}")
        return []