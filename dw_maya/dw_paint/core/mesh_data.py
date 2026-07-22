import math
from typing import Dict, List, Optional, Tuple, Union
import numpy as np
from maya.api import OpenMaya as om
from maya import cmds
from dw_logger import get_logger
from . import mesh_cache

logger = get_logger()


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

class MeshData:
    """Class to handle mesh data operations"""

    def __init__(self, mesh_name: str):
        self.mesh_name = mesh_name
        self._vertex_positions: Optional[np.ndarray] = None
        self._vertex_count: Optional[int] = None
        self._neighbors: Optional[Dict[int, List[int]]] = None
        self._vertex_uvs: Optional[np.ndarray] = None
        # Lazy API cache — reset by refresh()
        self._dag_path_obj: Optional[om.MDagPath] = None
        self._fn_mesh_obj: Optional[om.MFnMesh] = None
        self._initialize()

    def _initialize(self) -> None:
        """Initialize mesh data using cache"""
        mesh_data = mesh_cache.get_mesh_data(self.mesh_name)
        if mesh_data:
            self._vertex_positions, self._neighbors, self._vertex_count = mesh_data

    # ------------------------------------------------------------------
    # Cached OpenMaya API objects
    # ------------------------------------------------------------------

    def _init_api(self) -> None:
        """Lazily build and cache the MDagPath + MFnMesh for this mesh."""
        if self._fn_mesh_obj is None:
            sel = om.MSelectionList()
            sel.add(self.mesh_name)
            self._dag_path_obj = sel.getDagPath(0)
            self._fn_mesh_obj = om.MFnMesh(self._dag_path_obj)

    @property
    def _dag(self) -> om.MDagPath:
        """Cached MDagPath for this mesh."""
        self._init_api()
        return self._dag_path_obj

    @property
    def _fn_mesh(self) -> om.MFnMesh:
        """Cached MFnMesh for this mesh."""
        self._init_api()
        return self._fn_mesh_obj


    @property
    def vertex_count(self) -> int:
        """Get number of vertices"""
        return self._vertex_count if self._vertex_count is not None else 0

    @property
    def vertex_positions(self) -> np.ndarray:
        """Get vertex positions"""
        return self._vertex_positions

    @property
    def neighbors(self) -> Dict[int, List[int]]:
        """Get vertex neighbor mapping"""
        return self._neighbors or {}

    @property
    def vertex_uvs(self) -> np.ndarray:
        """Per-vertex UV coordinates (Nx2, columns are U, V).

        A vertex on a UV seam is assigned to more than one UV shell —
        its U and V are averaged across every face-vertex that shares it.
        Vertices with no assigned UVs read as (0.0, 0.0).
        """
        if self._vertex_uvs is None:
            self._compute_vertex_uvs()
        return self._vertex_uvs

    def _compute_vertex_uvs(self) -> None:
        n = self.vertex_count
        uvs = np.zeros((n, 2), dtype=np.float32)
        try:
            it_vtx = om.MItMeshVertex(self._dag)
            while not it_vtx.isDone():
                idx = it_vtx.index()
                try:
                    u_arr, v_arr, _face_ids = it_vtx.getUVs()
                    if len(u_arr):
                        uvs[idx, 0] = float(np.mean(u_arr))
                        uvs[idx, 1] = float(np.mean(v_arr))
                except RuntimeError:
                    pass  # vertex has no UVs assigned on the current UV set
                it_vtx.next()
        except Exception as e:
            logger.warning(f"vertex_uvs computation failed on '{self.mesh_name}': {e}")
        self._vertex_uvs = uvs

    def get_components(self, component_type: str = 'vtx') -> List[str]:
        """Get mesh components of specified type.

        Args:
            component_type: Type of component ('vtx', 'e', 'f')

        Returns:
            List of component names
        """
        return cmds.ls(f"{self.mesh_name}.{component_type}[*]", flatten=True)

    def get_selected_components(self) -> List[str]:
        """Get currently selected components for this mesh"""
        all_sel = cmds.ls(selection=True, flatten=True) or []
        return [x for x in all_sel if x.startswith(f"{self.mesh_name}.")]

    def get_vertex_position(self, vertex_id: int) -> Optional[np.ndarray]:
        """Get position of specific vertex"""
        if self._vertex_positions is not None and 0 <= vertex_id < len(self._vertex_positions):
            return self._vertex_positions[vertex_id]
        return None

    def get_vertex_neighbors(self, vertex_id: int) -> List[int]:
        """Get neighboring vertices for specific vertex"""
        return self._neighbors.get(vertex_id, []) if self._neighbors else []

    def get_bounding_box(self) -> Tuple[np.ndarray, np.ndarray]:
        """Get mesh bounding box min/max points"""
        if self._vertex_positions is not None and len(self._vertex_positions) > 0:
            return (
                np.min(self._vertex_positions, axis=0),
                np.max(self._vertex_positions, axis=0)
            )
        return np.zeros(3), np.zeros(3)

    def get_center(self) -> np.ndarray:
        """Get mesh center point"""
        if self._vertex_positions is not None and len(self._vertex_positions) > 0:
            return np.mean(self._vertex_positions, axis=0)
        return np.zeros(3)

    def get_vertex_normal(self, vertex_id: int) -> Optional[np.ndarray]:
        """Get normal vector for specific vertex"""
        try:
            normal = self._fn_mesh.getVertexNormal(vertex_id, True)
            return np.array([normal.x, normal.y, normal.z])
        except Exception as e:
            logger.error(f"Error getting vertex normal: {e}")
            return None

    def get_vertex_normals(self) -> Optional[np.ndarray]:
        """Get all vertex normals"""
        try:
            normals = self._fn_mesh.getVertexNormals(True)
            return np.array([[n.x, n.y, n.z] for n in normals])
        except Exception as e:
            logger.error(f"Error getting vertex normals: {e}")
            return None

    def get_closest_vertex(self, point: Union[Tuple[float, float, float], np.ndarray]) -> int:
        """Get closest vertex to given point"""
        if self._vertex_positions is not None:
            point = np.array(point)
            distances = np.linalg.norm(self._vertex_positions - point, axis=1)
            return int(np.argmin(distances))
        return 0

    def get_vertex_colors(self) -> Optional[np.ndarray]:
        """Get vertex colors if they exist"""
        try:
            fn = self._fn_mesh
            if fn.numColorSets > 0:
                colors = fn.getVertexColors()
                if colors:
                    return np.array([[c.r, c.g, c.b] for c in colors])
        except Exception as e:
            logger.debug(f"No vertex colors found: {e}")
        return None

    def refresh(self) -> None:
        """Refresh mesh data from cache"""
        # Invalidate API cache so next access rebuilds from scratch
        self._dag_path_obj = None
        self._fn_mesh_obj = None
        mesh_cache.clear_cache()
        self._initialize()

    def get_border_edges(self) -> List[int]:
        """Get indices of border edges (edges connected to only one face).

        A border edge is an edge that is connected to only one face, meaning it lies
        on the boundary of the mesh. This method uses Maya's API to efficiently
        find these edges by:
        1. Creating an edge iterator for the mesh
        2. Checking each edge's connected face count
        3. Collecting edges that have only one connected face

        Returns:
            List of edge indices that are on the mesh border
        """
        try:
            edge_iter = om.MItMeshEdge(self._dag)
            border_edges = []
            while not edge_iter.isDone():
                if edge_iter.onBoundary():
                    border_edges.append(edge_iter.index())
                edge_iter.next()
            return border_edges
        except Exception as e:
            logger.error(f"Error getting border edges: {e}")
            return []

    def get_edge_vertices(self, edge_index: int) -> List[int]:
        """Get vertex indices for a given edge.

        Args:
            edge_index: Index of the edge to query

        Returns:
            List containing the two vertex indices that form the edge
        """
        try:
            edge_iter = om.MItMeshEdge(self._dag)
            edge_iter.setIndex(edge_index)
            return [edge_iter.vertexId(0), edge_iter.vertexId(1)]
        except Exception as e:
            logger.error(f"Error getting edge vertices: {e}")
            return []


class MeshDataFactory:
    """Factory for creating and managing MeshData instances"""

    _instances: Dict[str, MeshData] = {}

    @classmethod
    def get(cls, mesh_name: str) -> MeshData:
        """Get MeshData instance for mesh"""
        if mesh_name not in cls._instances:
            cls._instances[mesh_name] = MeshData(mesh_name)
        return cls._instances[mesh_name]

    @classmethod
    def clear(cls) -> None:
        """Clear all instances"""
        cls._instances.clear()

def find_vertex_pairs(
        positions: List[Tuple[float, float, float]],
        tolerance: float = 0.001
) -> Dict[int, int]:
    """Find vertex pairs within tolerance distance.

    Uses a KDTree for O(n log n) performance instead of O(n²) brute force.
    Falls back to brute force if scipy is unavailable.
    """
    try:
        import numpy as np
        from scipy.spatial import KDTree

        pos_array = np.array(positions)
        tree = KDTree(pos_array)
        pairs = {}
        for i, pos in enumerate(pos_array):
            if i in pairs:
                continue
            neighbours = tree.query_ball_point(pos, tolerance)
            for j in neighbours:
                if j != i and j not in pairs:
                    pairs[i] = j
                    pairs[j] = i
                    break
        return pairs

    except ImportError:
        # Brute-force fallback when scipy is not available
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


def find_mirror_pairs(
        positions: List[Tuple[float, float, float]],
        axis: str = 'x',
        tolerance: float = 0.001
) -> Dict[int, int]:
    """Find vertex mirror pairs across the specified axis.

    Mirrors positions along the given axis and finds matching vertices
    within tolerance. Vertices on the mirror plane (coord ≈ 0) map to
    themselves. Uses KDTree for O(n log n) performance.

    Args:
        positions: Vertex positions as list of (x, y, z) tuples or array.
        axis: Axis to mirror across ('x', 'y', 'z').
        tolerance: Maximum distance to consider two vertices a pair.

    Returns:
        Dict mapping vertex index → mirror vertex index.
        Vertices on the plane map to themselves.
    """
    try:
        import numpy as np
        from scipy.spatial import KDTree

        axis_idx = {'x': 0, 'y': 1, 'z': 2}[axis.lower()]
        pos_array = np.array(positions, dtype=np.float32)

        # Build a mirrored copy by flipping the axis coordinate
        mirrored = pos_array.copy()
        mirrored[:, axis_idx] *= -1

        tree = KDTree(pos_array)
        pairs = {}

        for i, m_pos in enumerate(mirrored):
            dist, j = tree.query(m_pos)
            if dist <= tolerance:
                pairs[i] = int(j)

        return pairs

    except ImportError:
        # Brute-force fallback
        axis_idx = {'x': 0, 'y': 1, 'z': 2}[axis.lower()]
        pairs = {}
        for i in range(len(positions)):
            if i in pairs:
                continue
            pos1 = positions[i]
            for j in range(i + 1, len(positions)):
                if j in pairs:
                    continue
                pos2 = positions[j]
                if (abs(pos1[axis_idx] + pos2[axis_idx]) < tolerance
                        and abs(pos1[(axis_idx + 1) % 3] - pos2[(axis_idx + 1) % 3]) < tolerance
                        and abs(pos1[(axis_idx + 2) % 3] - pos2[(axis_idx + 2) % 3]) < tolerance):
                    pairs[i] = j
                    pairs[j] = i
                    break
            if i not in pairs and abs(pos1[axis_idx]) < tolerance:
                pairs[i] = i  # on mirror plane
        return pairs

def get_closest_vertex(
        point: Tuple[float, float, float],
        positions: List[Tuple[float, float, float]]) -> int:
    """Find the closest vertex to a given point.

    Uses numpy for vectorized distance computation.
    Falls back to math.sqrt loop if numpy is unavailable (very old Maya).
    """
    try:
        pos_array = np.array(positions)
        pt = np.array(point)
        return int(np.argmin(np.linalg.norm(pos_array - pt, axis=1)))
    except Exception:
        # math fallback
        min_dist = float('inf')
        closest_idx = -1
        for i, pos in enumerate(positions):
            dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(point, pos)))
            if dist < min_dist:
                min_dist = dist
                closest_idx = i
        return closest_idx
