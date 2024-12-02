import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.utils as mu
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Lock
import multiprocessing
from typing import List, Tuple, Optional
import queue  # Import the module
from dw_maya.dw_decorators import timeIt



class AdvancedHybridSmoother:
    """
    An advanced weight smoothing system that incorporates adaptive chunk sizing,
    work stealing, and memory prefetching for optimal performance.
    """

    def __init__(self, mesh_name: str, cloth_node: str):
        self.mesh_name = mesh_name
        self.cloth_node = cloth_node
        # Calculate optimal chunk size based on CPU cache size
        self.l3_cache_size = self._estimate_cache_size()
        self._initialize_topology_cache()

    def _estimate_cache_size(self) -> int:
        """
        Estimate the L3 cache size to optimize chunk sizing.
        This helps us avoid cache thrashing when processing vertex data.
        """
        # Most modern CPUs have at least 4MB L3 cache per core
        cpu_count = multiprocessing.cpu_count()
        default_l3_size = 4 * 1024 * 1024  # 4MB in bytes
        return default_l3_size * cpu_count

    def _calculate_optimal_chunk_size(self, total_vertices: int,
                                      num_threads: int) -> int:
        """
        Calculate the optimal chunk size based on mesh size, thread count,
        and CPU cache characteristics.
        """
        # Each vertex needs space for its data and its neighbors
        avg_neighbors = np.mean(self.neighbor_counts)
        bytes_per_vertex = (4 * 3 +  # Position (3 floats)
                            4 * avg_neighbors +  # Neighbor indices
                            4 * 2)  # Weight and temporary data

        # Target chunk size that fits in L3 cache with some headroom
        cache_target = self.l3_cache_size // (num_threads * 2)
        vertices_per_chunk = cache_target // bytes_per_vertex

        # Ensure chunks are neither too small nor too large
        min_chunk = 1000  # Minimum to avoid thread overhead
        max_chunk = total_vertices // (num_threads * 2)  # Allow work stealing

        return int(np.clip(vertices_per_chunk, min_chunk, max_chunk))

    def _create_work_queue(self, total_vertices: int, chunk_size: int) -> Queue:
        """
        Create a queue of work items that threads can steal from.
        Chunks are created with consideration for vertex complexity.
        """
        work_queue = Queue()

        # Calculate vertex complexity based on neighbor count
        complexity = self.neighbor_counts / np.mean(self.neighbor_counts)

        # Create chunks, adjusting size based on local complexity
        current_pos = 0
        while current_pos < total_vertices:
            # Adjust chunk size based on local complexity
            local_complexity = np.mean(complexity[current_pos:current_pos + chunk_size])
            adjusted_size = int(chunk_size / local_complexity)

            end_pos = min(current_pos + adjusted_size, total_vertices)
            work_queue.put((current_pos, end_pos))
            current_pos = end_pos

        return work_queue

    def _process_chunk_with_prefetch(self, chunk_data: Tuple[int, int],
                                     weights: np.ndarray,
                                     smooth_factor: float) -> np.ndarray:
        """
        Process a chunk of vertices with memory prefetching.
        This reduces memory access latency by preparing data before it's needed.
        """
        start_idx, end_idx = chunk_data
        chunk_size = end_idx - start_idx

        # Prefetch neighbor data for this chunk
        neighbor_indices = np.ascontiguousarray(
            self.neighbor_indices[start_idx:end_idx]
        )
        neighbor_counts = np.ascontiguousarray(
            self.neighbor_counts[start_idx:end_idx]
        )

        # Allocate result array
        chunk_sums = np.zeros(chunk_size, dtype=np.float32)

        # Process vertices with prefetched data
        for i in range(chunk_size):
            if neighbor_counts[i] > 0:
                valid_neighbors = neighbor_indices[i, :neighbor_counts[i]]
                # Prefetch next iteration's weight data
                if i < chunk_size - 1:
                    next_neighbors = neighbor_indices[i + 1, :neighbor_counts[i + 1]]
                    np.ascontiguousarray(weights[next_neighbors])

                chunk_sums[i] = np.sum(weights[valid_neighbors])

        return chunk_sums

    @timeIt
    def smooth_weights(self,
                       weights: np.ndarray,
                       iterations: int = 2,
                       smooth_factor: float = 0.5,
                       maintain_bounds: bool = True,
                       num_threads: int = 4) -> np.ndarray:
        """
        Perform advanced parallel weight smoothing with all optimizations enabled.
        """
        if len(weights) != self.vertex_count:
            raise ValueError("Weight count doesn't match vertex count")

        # Calculate optimal chunk size for this mesh and thread count
        chunk_size = self._calculate_optimal_chunk_size(self.vertex_count, num_threads)
        current_weights = weights.copy()
        inverse_smooth = 1.0 - smooth_factor
        results_lock = Lock()

        def worker(work_queue: queue.Queue) -> List[Tuple[int, np.ndarray]]:
            """
            Worker function that processes chunks and can steal work from the queue.
            Uses proper exception handling for empty queue conditions.

            Args:
                work_queue: Queue containing chunks of work to be processed

            Returns:
                List of tuples containing start indices and processed chunk results
            """
            results = []
            while True:
                try:
                    chunk_data = work_queue.get_nowait()
                    chunk_result = self._process_chunk_with_prefetch(
                        chunk_data, current_weights, smooth_factor
                    )
                    results.append((chunk_data[0], chunk_result))
                except queue.Empty:  # Correct exception class reference
                    break  # No more work available
            return results

        # Perform smoothing iterations
        for iteration in range(iterations):
            # Create work queue for this iteration
            work_queue = self._create_work_queue(self.vertex_count, chunk_size)

            # Process chunks in parallel with work stealing
            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                future_results = [
                    executor.submit(worker, work_queue)
                    for _ in range(num_threads)
                ]

                # Combine results in order
                all_results = []
                for future in future_results:
                    all_results.extend(future.result())

            # Sort results by start index and combine
            all_results.sort(key=lambda x: x[0])
            neighbor_sums = np.concatenate([r[1] for r in all_results])

            # Calculate new weights
            new_weights = (current_weights * inverse_smooth +
                           (neighbor_sums / np.maximum(self.neighbor_counts, 1)) *
                           smooth_factor)

            if maintain_bounds:
                orig_min, orig_max = weights.min(), weights.max()
                if orig_min != orig_max:
                    new_weights = np.interp(new_weights,
                                            (new_weights.min(), new_weights.max()),
                                            (orig_min, orig_max))

            current_weights = new_weights

        return current_weights

    def _initialize_topology_cache(self):
        """
        Initialize the mesh topology data structures needed for smoothing operations.
        This method creates efficient array-based storage of vertex connectivity
        that will be used by our parallel processing system.
        """
        # Access the mesh through Maya's API
        sel = om.MSelectionList()
        sel.add(self.mesh_name)
        self.mesh_dag = sel.getDagPath(0)
        self.mesh_fn = om.MFnMesh(self.mesh_dag)

        # Store the total number of vertices
        self.vertex_count = self.mesh_fn.numVertices

        # First, we'll scan the mesh to find out the maximum number of neighbors
        # any vertex has. This helps us allocate our arrays efficiently.
        vertex_iter = om.MItMeshVertex(self.mesh_dag)
        max_neighbors = 0
        while not vertex_iter.isDone():
            max_neighbors = max(max_neighbors, len(vertex_iter.getConnectedVertices()))
            vertex_iter.next()

        # Now we can create our optimized data structures
        # neighbor_indices stores the indices of connected vertices
        self.neighbor_indices = np.zeros((self.vertex_count, max_neighbors), dtype=np.int32)
        # neighbor_counts stores how many neighbors each vertex has
        self.neighbor_counts = np.zeros(self.vertex_count, dtype=np.int32)

        # Second pass: fill our arrays with the actual connectivity data
        vertex_iter.reset()
        while not vertex_iter.isDone():
            vertex_id = vertex_iter.index()
            neighbors = vertex_iter.getConnectedVertices()
            self.neighbor_counts[vertex_id] = len(neighbors)
            self.neighbor_indices[vertex_id, :len(neighbors)] = neighbors
            vertex_iter.next()


def test_advanced_smooth(mesh_name: str = "bake_pSphere1_018_v1",
                         cloth_node: str = "nClothShape1"):
    print("\nTesting Advanced Hybrid Smoothing")
    print("=" * 60)

    initial_weights = np.array(cmds.getAttr(f"{cloth_node}.bendPerVertex"))
    smoother = AdvancedHybridSmoother(mesh_name, cloth_node)

    # Test with different thread counts
    for num_threads in [2]:
        print(f"\nTesting with {num_threads} threads:")
        result = smoother.smooth_weights(
            initial_weights.copy(),
            iterations=5,
            smooth_factor=0.5,
            maintain_bounds=True,
            num_threads=num_threads
        )

        # Print statistics
        stats = {
            'min': float(np.min(result)),
            'max': float(np.max(result)),
            'mean': float(np.mean(result)),
            'std': float(np.std(result)),
            'non_zero': float(np.sum(result > 0.001)) / len(result)
        }

        print("\nResults:")
        for key, value in stats.items():
            print(f"{key:>10}: {value:.4f}")

        return result

result = test_advanced_smooth("pSphere3", "nClothShape3")
cmds.setAttr("nClothShape3.bendPerVertex", result.tolist())
