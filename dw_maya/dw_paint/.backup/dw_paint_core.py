from maya import cmds, mel
from dw_maya.dw_maya_utils import get_vtx_pos
from dw_logger import get_logger
import math
import maya.api.OpenMaya as om
from dw_maya.dw_decorators import acceptString
from . import modify_weights, guess_if_component_sel
from dw_maya.dw_constants.node_re_mappings import COMPONENT_PATTERN

import numpy as np
from functools import lru_cache
from typing import List, Dict, Optional, Tuple, Literal, Union
from dw_maya.dw_decorators import timeIt
from dataclasses import dataclass

logger = get_logger()

# Type alias for weight list
WeightList = List[float]
OperationType = Literal['multiply', 'add', 'replace']


@acceptString("meshes")
def flood_value_on_sel(meshes: List[str],
                       weights: WeightList,
                       value: float,
                       operation: OperationType = "replace",
                       clamp_min: Optional[float] = None,
                       clamp_max: Optional[float] = None) -> WeightList:
    """
    Flood a value on selected components in Maya for deformers or weightLists.
    If components are selected, only those weights will be modified.
    If no components are selected or selection doesn't match input meshes,
    the operation will be applied to all weights.

    Args:
        meshes: List of mesh names to check against selection
        weights: Original weight values to modify
        value: Value to apply (multiply, add, or replace)
        operation: Type of operation ('multiply', 'add', 'replace')
        clamp_min: Optional minimum value for clamping
        clamp_max: Optional maximum value for clamping

    Returns:
        Modified list of weights

    Raises:
        ValueError: If operation is invalid or if weights list is empty
    """
    if not weights:
        raise ValueError("Weights list cannot be empty")

    if operation not in ['multiply', 'add', 'replace']:
        raise ValueError(f"Invalid operation: {operation}. Must be 'multiply', 'add', or 'replace'")

    # Initialize empty mask (no components selected case)
    mask = []

    # Get current selection and check for components, if it correspond to mesh, use it as mask
    sel_compo = guess_if_component_sel(meshes)
    logger.debug(f"flood_value_on_sel : component check : {sel_compo}")


    # TODO: check how component react when there is multiple meshes
    if sel_compo:
        try:
            # Extract component indices from selection
            for component in sel_compo:
                match = COMPONENT_PATTERN.match(component)
                if match:
                    start_idx = int(match.group(3))
                    end_idx = match.group(4)

                    if end_idx:
                        mask.append([start_idx, int(end_idx)+1])
                    else:
                        mask.append([start_idx])

        except (AttributeError, ValueError) as e:
            logger.warning(f"Error parsing component selection: {e}")
            mask = []  # Reset mask on error

    # Apply modification with or without mask
    try:
        new_weights = modify_weights(
            weights,
            value,
            operation,
            mask if mask else None,
            clamp_min,
            clamp_max
        )
        return new_weights

    except Exception as e:
        logger.error(f"Error modifying weights: {e}")
        return weights  # Return original weights on error


def apply_falloff(weights: np.ndarray, falloff: str) -> np.ndarray:
    """Vectorized falloff application"""
    if falloff == 'linear':
        return weights
    elif falloff == 'quadratic':
        return np.square(weights)
    elif falloff == 'smooth':
        return weights * weights * (3 - 2 * weights)
    elif falloff == 'smooth2':
        return weights * weights * weights * (weights * (6 * weights - 15) + 10)
    return weights

def select_vtx_info_on_mesh(data_list: WeightList,
                            mesh: str,
                            sel_mode: str,
                            value: Optional[float] = None,
                            _min: Optional[float] = None,
                            _max: Optional[float] = None) -> None:
    """Select vertices on a mesh based on their map values.

    Args:
        data_list: a list of weight from a vertex map
        mesh: which has a vertex map from nucleus, deformer or anything
        sel_mode: Selection mode ('range' or 'value')
        value: Specific value to select (used when sel_mode='value')
        _min: Minimum value for range selection
        _max: Maximum value for range selection
    """
    # Get map data
    if data_list is None:
        cmds.select(cl=True)
        return

    vtx_sel = []
    if mesh is not None:
        for n, val in enumerate(data_list):
            if sel_mode == 'range' and _min is not None and _max is not None:
                if _min <= val <= _max:
                    vtx_sel.append(f"{mesh}.vtx[{n}]")
            elif sel_mode == 'value' and value is not None:
                if value == val:
                    vtx_sel.append(f"{mesh}.vtx[{n}]")

    # Select vertices or clear selection
    if vtx_sel:
        cmds.select(vtx_sel, r=True)
    else:
        cmds.select(cl=True)


def mirror_vertex_map(
    data_list: WeightList,
    mesh: str,
    axis: Literal['x', 'y', 'z'] = 'x',
    world_space: bool = True) -> Optional[WeightList]:
    """Mirror vertex map values across a specified axis.

    Args:
        data_list: list of weight
        mesh: mesh which will be used to define the symmetry
        axis: Axis to mirror across ('x', 'y', or 'z')
        world_space: Coordinate space to use ('world' or 'object')

    Returns:
        True if successful, False otherwise

    """
    try:

        # Get vertex positions
        vertex_count = cmds.polyEvaluate(mesh, vertex=True)
        positions = get_vtx_pos(mesh, world_space)

        # Create vertex pairs based on positions
        axis_idx = {'x': 0, 'y': 1, 'z': 2}[axis.lower()]
        tolerance = 0.001
        pairs = {}

        # Find mirror pairs
        for i in range(vertex_count):
            pos = positions[i]
            for j in range(i + 1, vertex_count):
                mirror_pos = positions[j]

                # Check mirror conditions
                if (abs(pos[axis_idx] + mirror_pos[axis_idx]) < tolerance and
                        abs(pos[(axis_idx + 1) % 3] - mirror_pos[(axis_idx + 1) % 3]) < tolerance and
                        abs(pos[(axis_idx + 2) % 3] - mirror_pos[(axis_idx + 2) % 3]) < tolerance):
                    pairs[i] = j
                    pairs[j] = i
                    break

        new_data = list(data_list)
        for i, j in pairs.items():
            new_data[j] = data_list[i]

        return new_data

    except Exception as e:
        logger.error(f"Failed to mirror vertex map: {str(e)}")
        return None


@dataclass
class MeshCache:
    """Cache for mesh data"""
    mesh_name: str = ""
    vertex_count: int = 0
    last_dag_path: Optional[om.MDagPath] = None
    cache_hits: int = 0
    cache_misses: int = 0


# Global cache instance
MESH_CACHE = MeshCache()


def check_cache_memory(mesh_name: str = None) -> bool:
    """Check cache memory and mesh state.
    Returns True if cache was cleared or needs refresh.
    """
    cache_info = _get_mesh_data.cache_info()
    estimated_mb = cache_info.currsize * 5  # rough estimate in MB

    # Check memory threshold
    if estimated_mb > 50:  # 50MB threshold
        logger.warning("Cache size exceeded threshold, clearing...")
        clear_mesh_cache()
        return True

    # Check if mesh needs refresh
    if mesh_name and mesh_name != MESH_CACHE.mesh_name:
        return True

    # Check if mesh exists and hasn't been deleted
    if mesh_name:
        try:
            sel = om.MSelectionList()
            sel.add(mesh_name)
            current_dag = sel.getDagPath(0)
            mesh_fn = om.MFnMesh(current_dag)

            # Check for topology changes
            if (MESH_CACHE.last_dag_path is None or
                    mesh_fn.numVertices != MESH_CACHE.vertex_count):
                return True

        except Exception:
            return True

    return False


@lru_cache(maxsize=32)
def _get_mesh_data(mesh_name: str) -> Tuple[np.ndarray, Dict[int, List[int]], int]:
    """Cache mesh topology data, with memory optimization."""
    try:
        MESH_CACHE.cache_misses += 1

        sel = om.MSelectionList()
        sel.add(mesh_name)
        mesh_dag = sel.getDagPath(0)
        mesh_fn = om.MFnMesh(mesh_dag)

        # Get vertex positions using float32
        points = mesh_fn.getPoints(om.MSpace.kWorld)
        vertex_positions = np.array([(p.x, p.y, p.z) for p in points], dtype=np.float32)

        # Build neighbor map
        vertex_count = mesh_fn.numVertices
        vertex_iter = om.MItMeshVertex(mesh_dag)
        neighbors = {}

        while not vertex_iter.isDone():
            connected_vertices = vertex_iter.getConnectedVertices()
            neighbors[vertex_iter.index()] = list(connected_vertices)
            vertex_iter.next()

        # Update cache state
        MESH_CACHE.mesh_name = mesh_name
        MESH_CACHE.last_dag_path = mesh_dag
        MESH_CACHE.vertex_count = vertex_count

        return vertex_positions, neighbors, vertex_count

    except Exception as e:
        logger.error(f"Error caching mesh data for {mesh_name}: {e}")
        return None


def interpolate_vertex_map(
        data_list: WeightList,
        mesh: str,
        smooth_iterations: int = 1,
        smooth_factor: float = 0.5) -> Optional[WeightList]:
    """Interpolate vertex map values using vectorized operations."""
    try:
        # Check cache state and memory usage
        if check_cache_memory(mesh):
            _get_mesh_data.cache_clear()

        # Get cached mesh data
        _, neighbors, vertex_count = _get_mesh_data(mesh)

        # Convert input to numpy array
        current_data = np.array(data_list, dtype=np.float64)

        # Pre-calculate weights
        inverse_smooth = 1 - smooth_factor

        # Create neighbor averages array
        neighbor_averages = np.zeros_like(current_data)

        # Perform smoothing iterations
        for _ in range(smooth_iterations):
            # Calculate all neighbor averages
            for i in range(vertex_count):
                if neighbors[i]:
                    neighbor_averages[i] = np.mean(current_data[neighbors[i]])

            # Update all vertices simultaneously
            current_data = (current_data * inverse_smooth +
                            neighbor_averages * smooth_factor)

        return current_data.tolist()

    except Exception as e:
        logger.error(f"Failed to interpolate vertex map: {e}")
        return None


def get_cache_stats():
    """Get current cache statistics"""
    cache_info = _get_mesh_data.cache_info()
    return {
        "hits": cache_info.hits,
        "misses": MESH_CACHE.cache_misses,
        "current_size": cache_info.currsize,
        "max_size": cache_info.maxsize,
        "memory_estimate": f"~{cache_info.currsize * 5}MB (rough estimate)"
    }


def clear_mesh_cache():
    """Clear all mesh caches and reset statistics"""
    _get_mesh_data.cache_clear()
    MESH_CACHE.mesh_name = ""
    MESH_CACHE.last_dag_path = None
    MESH_CACHE.vertex_count = 0
    MESH_CACHE.cache_hits = 0
    MESH_CACHE.cache_misses = 0



def normalize_vector(vector: np.ndarray) -> np.ndarray:
    """Normalize using numpy for better performance"""
    magnitude = np.linalg.norm(vector)
    return np.zeros(3) if magnitude == 0 else vector / magnitude


def get_predefined_vector(direction: str) -> Tuple[float, float, float]:
    """Get a predefined direction vector.

    Args:
        direction: Predefined direction name
            ('x', '-x', 'y', '-y', 'z', '-z',
             'xy', '-xy', 'xz', '-xz', 'yz', '-yz',
             'radial_out', 'radial_in')

    Returns:
        Direction vector as (x, y, z)
    """
    vectors = {
        'x': (1, 0, 0),
        '-x': (-1, 0, 0),
        'y': (0, 1, 0),
        '-y': (0, -1, 0),
        'z': (0, 0, 1),
        '-z': (0, 0, -1),
        'xy': normalize_vector((1, 1, 0)),
        '-xy': normalize_vector((-1, -1, 0)),
        'xz': normalize_vector((1, 0, 1)),
        '-xz': normalize_vector((-1, 0, -1)),
        'yz': normalize_vector((0, 1, 1)),
        '-yz': normalize_vector((0, -1, -1))
    }
    return vectors.get(direction, (1, 0, 0))


def get_distance_along_vector(
        points: np.ndarray,  # Shape: (N, 3)
        vector: np.ndarray,  # Shape: (3,)
        origin: Optional[np.ndarray] = None,
        mode: Literal['projection', 'distance'] = 'projection') -> np.ndarray:
    """Vectorized distance calculation"""
    if origin is None:
        origin = np.zeros(3)

    to_points = points - origin
    if mode == 'projection':
        return np.dot(to_points, vector)
    return np.linalg.norm(to_points, axis=1)


def set_vertex_weights_by_vector(
    mesh: str,
    direction: Union[str, Tuple[float, float, float]],
    remap_range: Optional[Tuple[float, float]] = None,
    falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
    origin: Optional[Tuple[float, float, float]] = None,
    invert: bool = False,
    mode: Literal['projection', 'distance'] = 'projection'
) -> Optional[WeightList]:

    """Set vertex map weights based on position along a vector direction.

    Args:
        mesh: mesh we manipulate
        direction: Either a predefined direction string or custom vector (x, y, z)
        remap_range: Optional (min, max) to remap weights to
        falloff: Type of falloff curve to use
        origin: Optional origin point for distance calculation
        invert: Whether to invert the resulting weights
        mode: 'projection' for along vector or 'distance' for distance from vector

    Returns:
        True if successful, False otherwise

    """
    try:
        # Get vertex positions
        positions = get_vtx_pos(mesh)
        if not positions:
            logger.error(f"No vertices found for {mesh}")
            return None

        # Get direction vector
        if isinstance(direction, str):
            vector = get_predefined_vector(direction)
        else:
            vector = normalize_vector(direction)

        # Calculate distances
        distances = [
            get_distance_along_vector(pos, vector, origin, mode)
            for pos in positions
        ]

        # Find range if not specified
        if remap_range is None:
            min_dist = min(distances)
            max_dist = max(distances)
            remap_range = (min_dist, max_dist)

        # Normalize distances to 0-1 range
        range_min, range_max = remap_range
        range_size = range_max - range_min
        if range_size == 0:
            weights = [0.0] * len(distances)
        else:
            weights = [
                (d - range_min) / range_size
                for d in distances
            ]

        # Apply falloff
        if falloff == 'quadratic':
            weights = [w * w for w in weights]
        elif falloff == 'smooth':
            weights = [w * w * (3 - 2 * w) for w in weights]
        elif falloff == 'smooth2':
            weights = [w * w * w * (w * (6 * w - 15) + 10) for w in weights]

        # Invert if requested
        if invert:
            weights = [1 - w for w in weights]

        # Set the weights
        return weights

    except Exception as e:
        logger.error(f"Error calculating weights: {str(e)}")
        return None


def set_vertex_weights_radial(
        mesh: str,
        center: Optional[Tuple[float, float, float]] = None,
        radius: Optional[float] = None,
        falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
        invert: bool = False) -> list:
    """Set vertex map weights based on radial distance from a center point.

    Args:
        mesh: name
        center: Center point for radial calculation (defaults to mesh center)
        radius: Maximum radius for weight calculation (defaults to auto-calculate)
        falloff: Type of falloff curve to use
        invert: Whether to invert the resulting weights

    Returns:
        List of weights between 0-1, or None if error
    """
    try:

        positions = get_vtx_pos(mesh)
        if not positions:
            logger.error("set_vertex_weights_radial: no vertex detected")
            return None

        # Calculate center if not provided
        if center is None:
            # Use mesh center
            x_avg = sum(p[0] for p in positions) / len(positions)
            y_avg = sum(p[1] for p in positions) / len(positions)
            z_avg = sum(p[2] for p in positions) / len(positions)
            center = (x_avg, y_avg, z_avg)

        # Calculate distances from center
        distances = [
            math.sqrt(sum((a - b) ** 2 for a, b in zip(pos, center)))
            for pos in positions
        ]

        # Use max distance as radius if not provided
        if radius is None:
            radius = max(distances)

        # Normalize distances
        if radius == 0:
            weights = [0.0] * len(distances)
        else:
            weights = [1 - min(d / radius, 1.0) for d in distances]

        # Apply falloff
        weights = apply_falloff(weights, falloff)

        # Apply inversion if requested
        if invert:
            weights = [1 - w for w in weights]

        # Apply falloff and inversion
        return weights

    except Exception as e:
        logger.error(f"Error setting radial weights: {str(e)}")
        return None


def set_vertex_weights_between_points(
        mesh: str,
        start_point: Tuple[float, float, float],
        end_point: Tuple[float, float, float],
        falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
        invert: bool = False) -> list:
    """Set vertex map weights based on position between two points.

    Args:
        mesh: mesh representing a deformer or a nucleus map
        start_point: Starting point for weight calculation
        end_point: Ending point for weight calculation
        falloff: Type of falloff curve to use
        invert: Whether to invert the resulting weights

    Returns:
        True if successful, False otherwise

    """
    # Calculate direction vector between points
    vector = tuple(b - a for a, b in zip(start_point, end_point))
    vector = normalize_vector(vector)

    return set_vertex_weights_by_vector(mesh,
        vector,
        origin=start_point,
        falloff=falloff,
        invert=invert
    )

