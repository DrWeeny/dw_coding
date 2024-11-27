
from typing import List, Tuple, Optional, Dict, Union, Literal
from maya import cmds
import math
import numpy as np
from dw_logger import get_logger

logger = get_logger()

def compare_two_nodes_list(node_list1,
                           node_list2):
    # Find objects that are in both lists
    matching = [mesh for mesh in node_list1 if mesh in node_list2]

    # Find objects in meshes but not in selection
    not_selected = [mesh for mesh in node_list1 if mesh not in node_list2]

    # Find selected objects that aren't in meshes list
    extra_selected = [obj for obj in node_list2 if obj not in node_list1]

    return matching, not_selected, extra_selected


def modify_weights(weight_list: List[Union[float, int]],
                   value: float,
                   operation: Literal['multiply', 'add', 'replace'] = 'replace',
                   mask: List[Union[List[int], List[float]]] = None,
                   min_value: float = None,
                   max_value: float = None) -> List[float]:
    """
    Modify an array of weights by multiplying, adding or replacing with a value.

    Args:
        weight_list: List of numerical values (float or int)
        value: Value to multiply, add, or replace with
        operation: 'multiply', 'add', or 'replace'
        mask: List of index specifications, where each spec can be:
              - Single index as [i]
              - Range as [start, end] (end is exclusive)
              Example: [[0,5], [9], [100,150]] will affect indices 0-4, 9, and 100-149
        min_value: Optional minimum value to clamp results
        max_value: Optional maximum value to clamp results

    Returns:
        List of modified weights
    """
    if not weight_list:
        return []

    try:
        arr = np.array(weight_list, dtype=float)
    except (ValueError, TypeError):
        raise TypeError("weight_list must contain only numerical values")

    if not isinstance(value, (int, float)):
        raise TypeError("value must be a number")

    if operation not in ['multiply', 'add', 'replace']:
        raise ValueError("operation must be either 'multiply', 'add', or 'replace'")

    if min_value is not None and max_value is not None and min_value > max_value:
        raise ValueError(f"min_value ({min_value}) cannot be greater than max_value ({max_value})")

    if mask is None or not mask:
        # Apply operation to entire array
        if operation == 'multiply':
            arr = arr * value
        elif operation == 'add':
            arr = arr + value
        else:  # replace
            arr[:] = value
    else:
        try:
            mask_arange = []
            for m in mask:
                if not isinstance(m, list):
                    raise TypeError(f"Each mask element must be a list, got {type(m)}")

                if len(m) not in (1, 2):
                    raise ValueError(f"Mask elements must be [index] or [start,end], got {m}")

                if len(m) == 1:
                    if m[0] >= len(arr):
                        raise ValueError(f"Index {m[0]} out of range for array of length {len(arr)}")
                    mask_arange.append(np.array([m[0]]))
                else:
                    start, end = m
                    if end > len(arr):
                        raise ValueError(f"End index {end} out of range for array of length {len(arr)}")
                    if start >= end:
                        raise ValueError(f"Start index {start} must be less than end index {end}")
                    mask_arange.append(np.arange(start, end))

            indices = np.concatenate(mask_arange)
            if operation == 'multiply':
                arr[indices] *= value
            elif operation == 'add':
                arr[indices] += value
            else:  # replace
                arr[indices] = value

        except Exception as e:
            raise ValueError(f"Error processing mask: {str(e)}")

    # Apply clamping if specified
    if min_value is not None:
        arr = np.maximum(arr, min_value)
    if max_value is not None:
        arr = np.minimum(arr, max_value)

    return arr.tolist()


def remap_weights(weight_list: List[Union[float, int]],
                  old_min: float,
                  old_max: float,
                  new_min: float,
                  new_max: float,
                  mask: List[Union[List[int], List[float]]] = None,
                  clamp: bool = True) -> List[float]:
    """
    Remap values from one range to another, with optional masking.
    Formula: new_value = (value - old_min) * (new_max - new_min) / (old_max - old_min) + new_min

    Args:
        weight_list: List of numerical values to remap
        old_min: Current minimum value in range
        old_max: Current maximum value in range
        new_min: Target minimum value
        new_max: Target maximum value
        mask: Optional list of index specifications [[0,5], [9], [100,150]]
        clamp: If True, clamp values to new range

    Returns:
        List of remapped values
    """
    if not weight_list:
        return []

    try:
        arr = np.array(weight_list, dtype=float)
    except (ValueError, TypeError):
        raise TypeError("weight_list must contain only numerical values")

    if old_min >= old_max:
        raise ValueError(f"old_min ({old_min}) must be less than old_max ({old_max})")
    if new_min >= new_max:
        raise ValueError(f"new_min ({new_min}) must be less than new_max ({new_max})")

    # Prepare remapping function
    def remap(values):
        remapped = (values - old_min) * (new_max - new_min) / (old_max - old_min) + new_min
        if clamp:
            remapped = np.clip(remapped, new_min, new_max)
        return remapped

    if mask is None or not mask:
        # Remap entire array
        arr = remap(arr)
    else:
        try:
            mask_arange = []
            for m in mask:
                if not isinstance(m, list):
                    raise TypeError(f"Each mask element must be a list, got {type(m)}")

                if len(m) not in (1, 2):
                    raise ValueError(f"Mask elements must be [index] or [start,end], got {m}")

                if len(m) == 1:
                    if m[0] >= len(arr):
                        raise ValueError(f"Index {m[0]} out of range for array of length {len(arr)}")
                    mask_arange.append(np.array([m[0]]))
                else:
                    start, end = m
                    if end > len(arr):
                        raise ValueError(f"End index {end} out of range for array of length {len(arr)}")
                    if start >= end:
                        raise ValueError(f"Start index {start} must be less than end index {end}")
                    mask_arange.append(np.arange(start, end))

            indices = np.concatenate(mask_arange)
            arr[indices] = remap(arr[indices])

        except Exception as e:
            raise ValueError(f"Error processing mask: {str(e)}")

    return arr.tolist()

def get_connected_vertices(mesh: str, vertex_index: int) -> List[int]:
    """Get indices of vertices connected to the given vertex."""
    edges = cmds.polyListComponentConversion(
        f"{mesh}.vtx[{vertex_index}]",
        fromVertex=True,
        toEdge=True
    )
    connected = cmds.polyListComponentConversion(
        edges,
        fromEdge=True,
        toVertex=True
    )
    return [
        int(v.split('[')[1].split(']')[0])
        for v in cmds.ls(connected, flatten=True)
    ]


def get_vertex_shell(mesh: str, start_vertex: int) -> List[int]:
    """Get all vertices in the same shell as the start vertex."""
    seen = set()
    to_visit = {start_vertex}

    while to_visit:
        current = to_visit.pop()
        if current not in seen:
            seen.add(current)
            connected = get_connected_vertices(mesh, current)
            to_visit.update(v for v in connected if v not in seen)

    return list(seen)


def find_vertex_pairs(
        positions: List[Tuple[float, float, float]],
        tolerance: float = 0.001
) -> Dict[int, int]:
    """Find vertex pairs within tolerance distance."""
    pairs = {}
    for i, pos1 in enumerate(positions):
        if i in pairs:
            continue
        for j, pos2 in enumerate(positions[i + 1:], i + 1):
            if j in pairs:
                continue
            dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(pos1, pos2)))
            if dist <= tolerance:
                pairs[i] = j
                pairs[j] = i
    return pairs


def get_closest_vertex(
        point: Tuple[float, float, float],
        positions: List[Tuple[float, float, float]]
) -> int:
    """Find the closest vertex to a given point."""
    min_dist = float('inf')
    closest_idx = -1

    for i, pos in enumerate(positions):
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(point, pos)))
        if dist < min_dist:
            min_dist = dist
            closest_idx = i

    return closest_idx


def get_vertex_normal(mesh: str, vertex_index: int) -> Tuple[float, float, float]:
    """Get the normal vector at a vertex."""
    normal = cmds.polyNormalPerVertex(
        f"{mesh}.vtx[{vertex_index}]",
        query=True,
        xyz=True
    )
    return tuple(normal[0:3])


def generate_falloff_curve(
        length: int,
        falloff_type: str = 'linear',
        remap_range: Optional[Tuple[float, float]] = None
) -> List[float]:
    """Generate a falloff curve of given length."""
    values = [i / (length - 1) for i in range(length)]

    if remap_range:
        min_val, max_val = remap_range
        values = [v * (max_val - min_val) + min_val for v in values]

    if falloff_type == 'quadratic':
        values = [v * v for v in values]
    elif falloff_type == 'smooth':
        values = [v * v * (3 - 2 * v) for v in values]
    elif falloff_type == 'smooth2':
        values = [v * v * v * (v * (6 * v - 15) + 10) for v in values]

    return values


def blend_weight_lists(
        weights_a: List[float],
        weights_b: List[float],
        blend_factor: float
) -> List[float]:
    """Blend between two weight lists."""
    return [
        a * (1 - blend_factor) + b * blend_factor
        for a, b in zip(weights_a, weights_b)
    ]


def normalize_weights(weights: List[float]) -> List[float]:
    """Normalize weights to sum to 1.0."""
    total = sum(weights)
    if total == 0:
        return [0.0] * len(weights)
    return [w / total for w in weights]

