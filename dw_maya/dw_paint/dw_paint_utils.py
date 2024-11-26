"""
Generated from Claude
"""

from typing import List, Tuple, Optional, Dict
from maya import cmds
import math


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

