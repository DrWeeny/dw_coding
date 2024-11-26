"""
Maya Paint Utilities

A toolkit for manipulating per-vertex weights and maps in Maya with a focus on nCloth
and deformer weights.

Main Features:
    - Vector-Based Weight Distribution:
        * Set weights along any direction vector
        * Predefined directions (x, y, z, etc.)
        * Custom vector support
        * Multiple falloff types

    - Radial Weight Distribution:
        * Center-based weight falloff
        * Auto or custom radius
        * Multiple falloff patterns

    - Point-to-Point Distribution:
        * Weight gradients between two points
        * Linear and non-linear falloffs
        * Distance-based mapping

    - Weight Modification:
        * Mirror weights across axes
        * Smooth/interpolate weights
        * Import/export weight maps
        * Selection based on weight values

Core Functions:
    set_vertex_weights_by_vector: Create weight gradients along vectors
    set_vertex_weights_radial: Create radial weight patterns
    set_vertex_weights_between_points: Create point-to-point gradients
    interpolate_vertex_map: Smooth weight distributions

Common Usage:
    # Set weights increasing along Y axis
    >>> set_vertex_weights_by_vector("clothShape_nCloth", "thicknessPerVertex",
    ...                             "y", remap_range=(0, 1))

    # Radial falloff from mesh center
    >>> set_vertex_weights_radial("clothShape_nCloth", "thicknessPerVertex",
    ...                          falloff='smooth')

    # Gradient between two points
    >>> set_vertex_weights_between_points("clothShape_nCloth", "thicknessPerVertex",
    ...                                  (0, 0, 0), (0, 10, 0))

    # Custom vector with quadratic falloff
    >>> set_vertex_weights_by_vector("clothShape_nCloth", "thicknessPerVertex",
    ...                             (1, 0.5, 0.5), falloff='quadratic')

    # Distance-based weights from Y axis
    >>> set_vertex_weights_by_vector("clothShape_nCloth", "thicknessPerVertex",
    ...                             "y", mode='distance')

Dependencies:
    - Maya 2020+ (maya.cmds)
    - DW Maya Core Toolkit
    - OpenMaya 2.0

Author: DrWeeny
Version: 1.0.0
"""

from maya import cmds, mel
import re
from .dw_core import get_nucx_map_data, get_mesh_from_nucx_node, set_nucx_map_data, get_nucx_map_type
from dw_maya.dw_maya_utils import get_vtx_pos
from typing import List, Optional, Union, Tuple, Literal
from dw_logger import get_logger
import math
import maya.api.OpenMaya as om
import dw_maya.dw_paint as dwpaint


logger = get_logger()

def paint_pervertex_map(nucx_node: str, map_name: str) -> None:
    """Enable Maya's vertex paint tool for a nucleus map.

    Args:
        nucx_node: Name of the nCloth or nRigid node
        map_name: Name of the map to paint

    Example:
        >>> paint_pervertex_map("clothMesh1Shape_nCloth", "thickness")
    """
    if not cmds.objExists(nucx_node) or cmds.nodeType(nucx_node) not in ['nCloth', 'nRigid']:
        logger.error(f"ClothNode not found, or is not a cloth node: {nucx_node}")
        return

    if get_nucx_map_type(nucx_node, f'{map_name}MapType') != 1:
        logger.warning(f"Vertex map '{map_name}' disabled")
        return

    model = get_mesh_from_nucx_node(nucx_node)
    if not model:
        return

    shape = cmds.listRelatives(model, s=True, ni=True)
    re_vtx_pattern = re.compile(f"{model}\\.vtx\\[(\\d+:?\\d+)")

    if not shape:
        logger.warning(f"{nucx_node} has {model} mesh but has not a valid shape")
        return

    obj = cmds.ls(sl=True)
    if obj:
        # Model not selected: select the model
        if cmds.listRelatives(cmds.ls(sl=True, o=True), p=1)[0] != model:
            cmds.select(obj[0])
        # Vertex selection
        elif cmds.listRelatives(cmds.ls(sl=True, o=True), p=1)[0] == model:
            if any(re_vtx_pattern.search(str(i)) for i in cmds.ls(sl=True)):
                sel = cmds.ls(sl=True)
                cmds.select(obj[0])
            else:
                sel = cmds.polyListComponentConversion(cmds.ls(sl=True), tv=True)
                cmds.select(obj[0])
    else:
        cmds.select(model)

    try:
        mel.eval(f'setNClothMapType("{map_name}","",1);')
        mel.eval(f'artAttrNClothToolScript 3 {map_name};')
    except Exception:
        logger.error('Please activate your nucleus and cloth and/or move to first frame')

def set_cfx_brush_val(val: float, mod: str = "absolute") -> None:
    """Set the value and mode for the nucleus paint brush.

    Args:
        val: Brush value
        mod: Brush mode ("absolute", "additive", or "scale")

    Example:
        >>> set_cfx_brush_val(0.5, "additive")
    """
    cmds.artAttrCtx('artAttrNClothContext', e=1, value=val)
    cmds.artAttrCtx('artAttrNClothContext', e=1, selectedattroper=mod)

def flood_smooth_vtx_map() -> None:
    """Smooth the currently active vertex map.

    Example:
        >>> flood_smooth_vtx_map()
    """
    cmds.artAttrCtx('artAttrNClothContext', edit=1, selectedattroper="smooth")
    cmds.refresh()
    cmds.artAttrCtx('artAttrNClothContext', edit=1, clear=1)

def select_vtx_info_on_mesh(
    nucx_node: str,
    nucx_map: str,
    sel_mode: str,
    value: Optional[float] = None,
    _min: Optional[float] = None,
    _max: Optional[float] = None) -> None:

    """Select vertices on a mesh based on their map values.

    Args:
        nucx_node: Name of the nCloth or nRigid node
        nucx_map: Name of the map attribute (must end with 'PerVertex')
        sel_mode: Selection mode ('range' or 'value')
        value: Specific value to select (used when sel_mode='value')
        _min: Minimum value for range selection
        _max: Maximum value for range selection

    Examples:
        Select vertices with a specific value:
        >>> select_vtx_info_on_mesh("clothMesh1Shape_nCloth", "thicknessPerVertex",
        ...                        "value", value=1.0)

        Select vertices within a range:
        >>> select_vtx_info_on_mesh("clothMesh1Shape_nCloth", "thicknessPerVertex",
        ...                        "range", _min=0.5, _max=1.0)
    """
    # Get map data
    data = get_nucx_map_data(nucx_node, nucx_map)
    if data is None:
        cmds.select(cl=True)
        return

    vtx_sel = []
    mesh = get_mesh_from_nucx_node(nucx_node)
    if mesh is not None:
        dwpaint.select_vtx_info_on_mesh(data,
                                        mesh,
                                        sel_mode,
                                        value,
                                        _min,
                                        _max)


def mirror_vertex_map(
        nucx_node: str,
        nucx_map: str,
        axis: str = 'x',
        space: bool = True) -> bool:

    """Mirror vertex map values across a specified axis.

    Args:
        nucx_node: Name of the nCloth or nRigid node
        nucx_map: Name of the map attribute (must end with 'PerVertex')
        axis: Axis to mirror across ('x', 'y', or 'z')
        space: Coordinate space to use ('world' or 'object')

    Returns:
        True if successful, False otherwise

    Example:
        >>> mirror_vertex_map("clothMesh1Shape_nCloth", "thicknessPerVertex", "x", "world")
        True
    """
    try:
        # Get mesh and vertex data
        mesh = get_mesh_from_nucx_node(nucx_node)
        if not mesh:
            return False

        data = get_nucx_map_data(nucx_node, nucx_map)
        if not data:
            return False

        weights = dwpaint.mirror_vertex_map(data,
                                  mesh,
                                  axis,
                                  space)

        # Apply new values
        set_nucx_map_data(nucx_node, nucx_map, weights)
        return True

    except Exception as e:
        logger.error(f"Failed to mirror vertex map: {str(e)}")
        return False


def interpolate_vertex_map(
        nucx_node: str,
        nucx_map: str,
        smooth_iterations: int = 1,
        smooth_factor: float = 0.5) -> bool:

    """Interpolate vertex map values based on neighboring vertices.

    Args:
        nucx_node: Name of the nCloth or nRigid node
        nucx_map: Name of the map attribute (must end with 'PerVertex')
        smooth_iterations: Number of smoothing iterations
        smooth_factor: Strength of smoothing (0-1)

    Returns:
        True if successful, False otherwise

    Example:
        >>> interpolate_vertex_map("clothMesh1Shape_nCloth",
        ...                       "thicknessPerVertex",
        ...                       smooth_iterations=2,
        ...                       smooth_factor=0.3)
        True
    """
    try:
        # Get mesh and map data
        mesh = get_mesh_from_nucx_node(nucx_node)
        if not mesh:
            return False

        data = get_nucx_map_data(nucx_node, nucx_map)
        if not data:
            return False

        weights = dwpaint.interpolate_vertex_map(data,
                                                 mesh,
                                                 smooth_iterations,
                                                 smooth_factor)

        # Apply smoothed values
        set_nucx_map_data(nucx_node, nucx_map, weights)
        return True

    except Exception as e:
        logger.error(f"Failed to interpolate vertex map: {str(e)}")
        return False


def set_vertex_weights_by_vector(
        nucx_node: str,
        nucx_map: str,
        direction: Union[str, Tuple[float, float, float]],
        remap_range: Optional[Tuple[float, float]] = None,
        falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
        origin: Optional[Tuple[float, float, float]] = None,
        invert: bool = False,
        mode: Literal['projection', 'distance'] = 'projection') -> bool:

    """Set vertex map weights based on position along a vector direction.

    Args:
        nucx_node: Name of the nCloth or nRigid node
        nucx_map: Name of the map attribute (must end with 'PerVertex')
        direction: Either a predefined direction string or custom vector (x, y, z)
        remap_range: Optional (min, max) to remap weights to
        falloff: Type of falloff curve to use
        origin: Optional origin point for distance calculation
        invert: Whether to invert the resulting weights
        mode: 'projection' for along vector or 'distance' for distance from vector

    Returns:
        True if successful, False otherwise

    Example:
        # Set weights increasing along Y axis
        >>> set_vertex_weights_by_vector("clothShape_nCloth", "thicknessPerVertex",
        ...                             "y", remap_range=(0, 1))

        # Set weights based on custom vector with quadratic falloff
        >>> set_vertex_weights_by_vector("clothShape_nCloth", "thicknessPerVertex",
        ...                             (1, 0.5, 0.5), falloff='quadratic')

        # Set weights based on distance from vertical axis
        >>> set_vertex_weights_by_vector("clothShape_nCloth", "thicknessPerVertex",
        ...                             "y", mode='distance')
    """
    try:
        # Get mesh and check it exists
        mesh = get_mesh_from_nucx_node(nucx_node)
        if not mesh:
            logger.error(f"Could not find mesh for {nucx_node}")
            return False

        # Get vertex positions
        positions = get_vtx_pos(mesh)
        if not positions:
            logger.error(f"No vertices found for {mesh}")
            return False

        weights = dwpaint.set_vertex_weights_by_vector(mesh,
                                             direction,
                                             remap_range,
                                             falloff,
                                             origin,
                                             invert,
                                             mode)

        # Set the weights
        set_nucx_map_data(nucx_node, nucx_map, weights)
        return True

    except Exception as e:
        logger.error(f"Error setting vertex weights: {str(e)}")
        return False


def set_vertex_weights_radial(
        nucx_node: str,
        nucx_map: str,
        center: Optional[Tuple[float, float, float]] = None,
        radius: Optional[float] = None,
        falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
        invert: bool = False) -> bool:
    """Set vertex map weights based on radial distance from a center point.

    Args:
        nucx_node: Name of the nCloth or nRigid node
        nucx_map: Name of the map attribute (must end with 'PerVertex')
        center: Center point for radial calculation (defaults to mesh center)
        radius: Maximum radius for weight calculation (defaults to auto-calculate)
        falloff: Type of falloff curve to use
        invert: Whether to invert the resulting weights

    Returns:
        True if successful, False otherwise

    Example:
        # Set weights decreasing from mesh center
        >>> set_vertex_weights_radial("clothShape_nCloth", "thicknessPerVertex")

        # Set weights from specific point with custom radius
        >>> set_vertex_weights_radial("clothShape_nCloth", "thicknessPerVertex",
        ...                          center=(0, 10, 0), radius=5)
    """
    try:
        mesh = get_mesh_from_nucx_node(nucx_node)
        if not mesh:
            return False

        weights = dwpaint.set_vertex_weights_radial(mesh,
                                                    center,
                                                    radius,
                                                    falloff,
                                                    invert)

        set_nucx_map_data(nucx_node, nucx_map, weights)
        return True

    except Exception as e:
        logger.error(f"Error setting radial weights: {str(e)}")
        return False


def set_vertex_weights_between_points(
        nucx_node: str,
        nucx_map: str,
        start_point: Tuple[float, float, float],
        end_point: Tuple[float, float, float],
        falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
        invert: bool = False
) -> bool:
    """Set vertex map weights based on position between two points.

    Args:
        nucx_node: Name of the nCloth or nRigid node
        nucx_map: Name of the map attribute (must end with 'PerVertex')
        start_point: Starting point for weight calculation
        end_point: Ending point for weight calculation
        falloff: Type of falloff curve to use
        invert: Whether to invert the resulting weights

    Returns:
        True if successful, False otherwise

    Example:
        >>> set_vertex_weights_between_points(
        ...     "clothShape_nCloth",
        ...     "thicknessPerVertex",
        ...     (0, 0, 0),
        ...     (0, 10, 0),
        ...     falloff='smooth'
        ... )
    """
    # Calculate direction vector between points
    vector = tuple(b - a for a, b in zip(start_point, end_point))
    vector = dwpaint.normalize_vector(vector)

    return set_vertex_weights_by_vector(
        nucx_node,
        nucx_map,
        vector,
        origin=start_point,
        falloff=falloff,
        invert=invert
    )

