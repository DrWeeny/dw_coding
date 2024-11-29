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
        self._initialize()

    def _initialize(self) -> None:
        """Initialize mesh data using cache"""
        mesh_data = mesh_cache.get_mesh_data(self.mesh_name)
        if mesh_data:
            self._vertex_positions, self._neighbors, self._vertex_count = mesh_data

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
            sel = om.MSelectionList()
            sel.add(self.mesh_name)
            mesh_dag = sel.getDagPath(0)
            mesh_fn = om.MFnMesh(mesh_dag)
            normal = mesh_fn.getVertexNormal(vertex_id, True)
            return np.array([normal.x, normal.y, normal.z])
        except Exception as e:
            logger.error(f"Error getting vertex normal: {e}")
            return None

    def get_vertex_normals(self) -> Optional[np.ndarray]:
        """Get all vertex normals"""
        try:
            sel = om.MSelectionList()
            sel.add(self.mesh_name)
            mesh_dag = sel.getDagPath(0)
            mesh_fn = om.MFnMesh(mesh_dag)
            normals = mesh_fn.getVertexNormals(True)
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
            sel = om.MSelectionList()
            sel.add(self.mesh_name)
            mesh_dag = sel.getDagPath(0)
            mesh_fn = om.MFnMesh(mesh_dag)

            if mesh_fn.numColorSets > 0:
                colors = mesh_fn.getVertexColors()
                if colors:
                    return np.array([[c.r, c.g, c.b] for c in colors])
        except Exception as e:
            logger.debug(f"No vertex colors found: {e}")
        return None

    def refresh(self) -> None:
        """Refresh mesh data from cache"""
        mesh_cache.clear_cache()
        self._initialize()


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
        positions: List[Tuple[float, float, float]]) -> int:
    """Find the closest vertex to a given point."""
    min_dist = float('inf')
    closest_idx = -1

    for i, pos in enumerate(positions):
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(point, pos)))
        if dist < min_dist:
            min_dist = dist
            closest_idx = i

    return closest_idx