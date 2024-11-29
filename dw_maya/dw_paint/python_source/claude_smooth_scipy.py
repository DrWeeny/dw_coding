import numpy as np
from maya.api import OpenMaya as om
from functools import lru_cache
from typing import List, Dict, Optional, Tuple

WeightList = List[float]


@lru_cache(maxsize=128)
def _get_mesh_data(mesh_name: str) -> Tuple[np.ndarray, Dict[int, List[int]], int]:
    """Cache and return mesh connectivity data using Maya API.

    Args:
        mesh_name: Name of the mesh

    Returns:
        Tuple of (vertex positions, neighbor dict, vertex count)
    """
    # Get mesh using API
    sel = om.MSelectionList()
    sel.add(mesh_name)
    mesh_dag = sel.getDagPath(0)
    mesh_fn = om.MFnMesh(mesh_dag)

    # Get vertex positions
    points = mesh_fn.getPoints(om.MSpace.kWorld)
    vertex_positions = np.array([(p.x, p.y, p.z) for p in points])

    # Build neighbor map using API for faster access
    vertex_count = mesh_fn.numVertices
    vertex_iter = om.MItMeshVertex(mesh_dag)
    neighbors = {}

    while not vertex_iter.isDone():
        # Get connected vertices
        connected_vertices = vertex_iter.getConnectedVertices()
        neighbors[vertex_iter.index()] = list(connected_vertices)
        vertex_iter.next()

    return vertex_positions, neighbors, vertex_count


def interpolate_vertex_map(
        data_list: WeightList,
        mesh: str,
        smooth_iterations: int = 1,
        smooth_factor: float = 0.5) -> Optional[WeightList]:
    """Interpolate vertex map values using vectorized operations.

    Args:
        data_list: Weight list of a deformer or nucleus map
        mesh: Name of the mesh
        smooth_iterations: Number of smoothing iterations
        smooth_factor: Strength of smoothing (0-1)

    Returns:
        Smoothed weight list
    """
    try:
        # Get cached mesh data
        _, neighbors, vertex_count = _get_mesh_data(mesh)

        # Convert to numpy array for faster operations
        current_data = np.array(data_list, dtype=np.float64)

        # Pre-calculate weights
        inverse_smooth = 1 - smooth_factor

        # Create sparse matrix for neighbor averaging
        from scipy import sparse

        # Build sparse matrix for neighbor relationships
        rows, cols, data = [], [], []
        for i in range(vertex_count):
            if neighbors[i]:
                weight = smooth_factor / len(neighbors[i])
                for j in neighbors[i]:
                    rows.append(i)
                    cols.append(j)
                    data.append(weight)
                # Add self-weight
                rows.append(i)
                cols.append(i)
                data.append(inverse_smooth)

        # Create sparse matrix
        neighbor_matrix = sparse.csr_matrix(
            (data, (rows, cols)),
            shape=(vertex_count, vertex_count)
        )

        # Perform smoothing using matrix multiplication
        current_data = np.asarray(current_data)
        for _ in range(smooth_iterations):
            current_data = neighbor_matrix.dot(current_data)

        return current_data.tolist()

    except Exception as e:
        logger.error(f"Failed to interpolate vertex map: {str(e)}")
        return None


# Optional: Clear cache if mesh topology changes
def clear_mesh_cache(mesh_name: str = None):
    """Clear the mesh data cache for a specific mesh or all meshes."""
    if mesh_name:
        _get_mesh_data.cache_clear()
    else:
        # Clear specific entry
        for key in list(_get_mesh_data.cache_info()[0]):
            if key[0] == mesh_name:
                _get_mesh_data.cache_info()[0].pop(key)