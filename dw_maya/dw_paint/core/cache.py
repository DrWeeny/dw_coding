import numpy as np
from maya.api import OpenMaya as om
from functools import lru_cache
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from dw_logger import get_logger

logger = get_logger()


@dataclass
class MeshCache:
    """Cache for mesh data"""
    mesh_name: str = ""
    vertex_count: int = 0
    last_dag_path: Optional[om.MDagPath] = None
    cache_hits: int = 0
    cache_misses: int = 0


class MeshDataCache:
    """Centralized mesh data caching system"""

    def __init__(self, max_size: int = 32, memory_threshold_mb: int = 50):
        self.cache = MeshCache()
        self.max_size = max_size
        self.memory_threshold = memory_threshold_mb
        self._get_mesh_data = lru_cache(maxsize=max_size)(self._get_mesh_data_impl)

    def check_cache_memory(self, mesh_name: str = None) -> bool:
        """Check cache memory and mesh state.
        Returns True if cache was cleared or needs refresh.
        """
        cache_info = self._get_mesh_data.cache_info()
        estimated_mb = cache_info.currsize * 5  # rough estimate in MB

        # Check memory threshold
        if estimated_mb > self.memory_threshold:
            logger.warning("Cache size exceeded threshold, clearing...")
            self.clear_cache()
            return True

        # Check if mesh needs refresh
        if mesh_name and mesh_name != self.cache.mesh_name:
            return True

        # Check if mesh exists and hasn't been deleted
        if mesh_name:
            try:
                sel = om.MSelectionList()
                sel.add(mesh_name)
                current_dag = sel.getDagPath(0)
                mesh_fn = om.MFnMesh(current_dag)

                # Check for topology changes
                if (self.cache.last_dag_path is None or
                        mesh_fn.numVertices != self.cache.vertex_count):
                    return True

            except Exception:
                return True

        return False

    def _get_mesh_data_impl(self, mesh_name: str) -> Tuple[np.ndarray, Dict[int, List[int]], int]:
        """Internal implementation of mesh data retrieval."""
        try:
            self.cache.cache_misses += 1

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
            self.cache.mesh_name = mesh_name
            self.cache.last_dag_path = mesh_dag
            self.cache.vertex_count = vertex_count

            return vertex_positions, neighbors, vertex_count

        except Exception as e:
            logger.error(f"Error caching mesh data for {mesh_name}: {e}")
            return None

    def get_mesh_data(self, mesh_name: str) -> Optional[Tuple[np.ndarray, Dict[int, List[int]], int]]:
        """Get cached mesh data, checking for updates if needed."""
        if self.check_cache_memory(mesh_name):
            self.clear_cache()
        return self._get_mesh_data(mesh_name)

    def clear_cache(self):
        """Clear all mesh caches and reset statistics"""
        self._get_mesh_data.cache_clear()
        self.cache.mesh_name = ""
        self.cache.last_dag_path = None
        self.cache.vertex_count = 0
        self.cache.cache_hits = 0
        self.cache.cache_misses = 0

    def get_stats(self):
        """Get current cache statistics"""
        cache_info = self._get_mesh_data.cache_info()
        return {
            "hits": cache_info.hits,
            "misses": self.cache.cache_misses,
            "current_size": cache_info.currsize,
            "max_size": cache_info.maxsize,
            "memory_estimate": f"~{cache_info.currsize * 5}MB (rough estimate)"
        }
