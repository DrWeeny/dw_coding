from maya import cmds, mel
from dw_maya.dw_maya_utils import get_vtx_pos
from typing import List, Optional, Union, Tuple, Literal
from dw_logger import get_logger
import math
import maya.api.OpenMaya as om
from dw_maya.dw_maya_utils import component_in_list
from dw_maya.dw_decorators import acceptString

logger = get_logger()

# Type alias for weight list
WeightList = List[float]

@acceptString("mesh")
def flood_value_on_sel(mesh, weights: list):

    # get selection to check if component are in selection
    sel = cmds.ls(sl=True)
    components = component_in_list(sel)
    if components:
        arg_compare = list(set([s.split(".")[0] for s in sel]))




def apply_falloff(weights: List[float],
                  falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear') -> List[float]:
    """Apply falloff function to weight values.

    Args:
        weights: List of weight values between 0-1
        falloff: Type of falloff curve to apply

    Returns:
        Modified weight values
    """
    if falloff == 'linear':
        return weights
    elif falloff == 'quadratic':
        return [w * w for w in weights]
    elif falloff == 'smooth':
        return [w * w * (3 - 2 * w) for w in weights]
    elif falloff == 'smooth2':
        return [w * w * w * (w * (6 * w - 15) + 10) for w in weights]
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


def interpolate_vertex_map(
        data_list: WeightList,
        mesh: str,
        smooth_iterations: int = 1,
        smooth_factor: float = 0.5
) -> Optional[WeightList]:

    """Interpolate vertex map values based on neighboring vertices.

    Args:
        data_list: weight list of a deformer or nucleus map
        mesh: name of the mesh representing this data_list
        smooth_iterations: Number of smoothing iterations
        smooth_factor: Strength of smoothing (0-1)

    Returns:
        weight list

    """
    try:
        # Get mesh connectivity
        vertex_count = cmds.polyEvaluate(mesh, vertex=True)
        neighbors = {}

        # Build neighbor map
        for i in range(vertex_count):
            # Get connected vertices through edges
            edges = cmds.polyListComponentConversion(f"{mesh}.vtx[{i}]",
                                                     fromVertex=True,
                                                     toEdge=True)
            connected_verts = cmds.polyListComponentConversion(edges,
                                                               fromEdge=True,
                                                               toVertex=True)
            # Extract vertex indices
            vert_indices = []
            for vert in cmds.ls(connected_verts, flatten=True):
                idx = int(vert.split('[')[1].split(']')[0])
                if idx != i:  # Exclude self
                    vert_indices.append(idx)
            neighbors[i] = vert_indices

        # Perform smoothing
        current_data = list(data_list)
        for _ in range(smooth_iterations):
            new_data = list(current_data)
            for i in range(vertex_count):
                if not neighbors[i]:
                    continue

                # Calculate average of neighbors
                neighbor_avg = sum(current_data[j] for j in neighbors[i]) / len(neighbors[i])
                # Interpolate between current value and neighbor average
                new_data[i] = current_data[i] * (1 - smooth_factor) + neighbor_avg * smooth_factor

            current_data = new_data

        # return smoothed values
        return current_data

    except Exception as e:
        logger.error(f"Failed to interpolate vertex map: {str(e)}")


def normalize_vector(vector: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Normalize a vector to unit length.

    Args:
        vector: Input vector as (x, y, z)

    Returns:
        Normalized vector as (x, y, z)
    """
    magnitude = math.sqrt(sum(x * x for x in vector))
    if magnitude == 0:
        return (0.0, 0.0, 0.0)
    return tuple(x / magnitude for x in vector)


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
        point: Tuple[float, float, float],
        vector: Tuple[float, float, float],
        origin: Optional[Tuple[float, float, float]] = None,
        mode: Literal['projection', 'distance'] = 'projection') -> float:

    """Calculate the signed distance of a point along a vector.

    Args:
        point: Point to measure from as (x, y, z)
        vector: Direction vector as (x, y, z)
        origin: Origin point for measurement (defaults to world origin)
        mode: 'projection' for dot product or 'distance' for actual distance

    Returns:
        Signed distance along vector
    """
    if origin is None:
        origin = (0, 0, 0)

    # Convert to Maya vectors for easier math
    point_vector = om.MVector(*point)
    direction = om.MVector(*vector)
    origin_vector = om.MVector(*origin)

    # Vector from origin to point
    to_point = point_vector - origin_vector

    if mode == 'projection':
        # Use dot product for projection distance
        return to_point * direction
    else:
        # Use actual distance
        return to_point.length()


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

