# core/interpolation.py
import numpy as np
from typing import List, Optional, Tuple, Dict, Literal
from dataclasses import dataclass
from ..utils.falloff import apply_falloff
from .mesh_data import MeshDataFactory
from .weights import WeightData
from dw_logger import get_logger

logger = get_logger()


@dataclass
class InterpolationSettings:
    """Configuration for interpolation operations"""
    smooth_iterations: int = 1
    smooth_factor: float = 0.5
    maintain_bounds: bool = True
    falloff_type: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear'
    preserve_borders: bool = False
    use_weighted_average: bool = False


class WeightInterpolator:
    """Handle weight interpolation and smoothing operations"""

    def __init__(self, mesh_name: str, settings: Optional[InterpolationSettings] = None):
        self.mesh_name = mesh_name
        self.settings = settings or InterpolationSettings()
        self.mesh_data = MeshDataFactory.get(mesh_name)
        self._original_bounds: Optional[Tuple[float, float]] = None

    def interpolate(self, weights: np.ndarray) -> np.ndarray:
        """Interpolate weights using configured settings"""
        if weights is None or len(weights) == 0:
            return np.array([])

        try:
            # Store original bounds if needed
            if self.settings.maintain_bounds:
                self._original_bounds = (np.min(weights), np.max(weights))

            # Get topology data
            neighbors = self.mesh_data.neighbors

            # Initialize arrays
            current_weights = np.array(weights, dtype=np.float32)

            # Smoothing iterations
            for _ in range(self.settings.smooth_iterations):
                current_weights = self._smooth_iteration(
                    current_weights,
                    neighbors
                )

            # Apply falloff if not linear
            if self.settings.falloff_type != 'linear':
                current_weights = apply_falloff(current_weights, self.settings.falloff_type)

            # Restore original bounds if needed
            if self.settings.maintain_bounds and self._original_bounds:
                current_weights = self._remap_to_bounds(
                    current_weights,
                    self._original_bounds
                )

            return current_weights

        except Exception as e:
            logger.error(f"Interpolation failed: {e}")
            return weights

    def _smooth_iteration(self,
                          weights: np.ndarray,
                          neighbors: Dict[int, List[int]]) -> np.ndarray:
        """Perform one smoothing iteration"""
        new_weights = np.zeros_like(weights)

        # Get border vertices if preserving borders
        border_vertices = set()
        if self.settings.preserve_borders:
            border_vertices = self._get_border_vertices()

        for vertex_id, neighbor_ids in neighbors.items():
            # Skip border vertices if preserving borders
            if self.settings.preserve_borders and vertex_id in border_vertices:
                new_weights[vertex_id] = weights[vertex_id]
                continue

            if not neighbor_ids:
                new_weights[vertex_id] = weights[vertex_id]
                continue

            if self.settings.use_weighted_average:
                # Calculate distance-weighted average
                neighbor_positions = self.mesh_data.vertex_positions[neighbor_ids]
                vertex_position = self.mesh_data.vertex_positions[vertex_id]
                distances = np.linalg.norm(neighbor_positions - vertex_position, axis=1)
                weights_array = 1.0 / (distances + 1e-6)  # Avoid division by zero
                weights_array /= np.sum(weights_array)

                neighbor_values = weights[neighbor_ids]
                average = np.sum(neighbor_values * weights_array)
            else:
                # Simple average
                average = np.mean(weights[neighbor_ids])

            # Apply smooth factor
            new_weights[vertex_id] = (weights[vertex_id] * (1.0 - self.settings.smooth_factor) +
                                      average * self.settings.smooth_factor)

        return new_weights

    def _get_border_vertices(self) -> set:
        """Get vertices on mesh borders"""
        border_edges = self.mesh_data.get_border_edges()
        border_vertices = set()

        for edge in border_edges:
            vertex_indices = self.mesh_data.get_edge_vertices(edge)
            border_vertices.update(vertex_indices)

        return border_vertices

    @staticmethod
    def _remap_to_bounds(weights: np.ndarray,
                         bounds: Tuple[float, float]) -> np.ndarray:
        """Remap weights to original bounds"""
        min_val, max_val = bounds
        if min_val == max_val:
            return np.full_like(weights, min_val)

        current_min = np.min(weights)
        current_max = np.max(weights)

        if current_min == current_max:
            return np.full_like(weights, min_val)

        return min_val + (weights - current_min) * (max_val - min_val) / (current_max - current_min)


def interpolate_vertex_map(
        weights: List[float],
        mesh: str,
        smooth_iterations: int = 1,
        smooth_factor: float = 0.5,
        settings: Optional[InterpolationSettings] = None) -> Optional[List[float]]:
    """High-level function for weight interpolation

    Args:
        weights: Input weight values
        mesh: Mesh name
        smooth_iterations: Number of smoothing iterations
        smooth_factor: Strength of smoothing (0-1)
        settings: Optional custom interpolation settings

    Returns:
        Smoothed weights or None if failed
    """
    try:
        if settings is None:
            settings = InterpolationSettings(
                smooth_iterations=smooth_iterations,
                smooth_factor=smooth_factor
            )

        interpolator = WeightInterpolator(mesh, settings)
        result = interpolator.interpolate(np.array(weights))

        return result.tolist()

    except Exception as e:
        logger.error(f"Failed to interpolate vertex map: {e}")
        return None


if __name__ == '__main__':
    from maya import cmds


    def run_interpolation_tests():
        """Test interpolation functionality"""
        try:
            # Create test sphere
            sphere = cmds.polySphere(radius=1, name='interpTest_sphere')[0]
            vertex_count = cmds.polyEvaluate(sphere, vertex=True)

            # Create test weights (gradient along Y axis)
            test_weights = np.zeros(vertex_count)
            positions = MeshDataFactory.get(sphere).vertex_positions
            test_weights = (positions[:, 1] + 1) / 2  # Normalize Y position to 0-1

            # Test different interpolation settings
            settings_list = [
                InterpolationSettings(smooth_iterations=1, smooth_factor=0.5),
                InterpolationSettings(smooth_iterations=5, smooth_factor=0.5, falloff_type='smooth'),
                InterpolationSettings(smooth_iterations=3, smooth_factor=0.7, preserve_borders=True),
                InterpolationSettings(smooth_iterations=2, smooth_factor=0.5, use_weighted_average=True)
            ]

            for i, settings in enumerate(settings_list):
                interpolator = WeightInterpolator(sphere, settings)
                result = interpolator.interpolate(test_weights)

                # Verify results
                assert len(result) == vertex_count
                assert np.all((result >= 0) & (result <= 1))
                logger.info(f"Test {i + 1} passed: {settings}")

            # Cleanup
            cmds.delete(sphere)
            return True

        except Exception as e:
            logger.error(f"Interpolation tests failed: {e}")
            if cmds.objExists('interpTest_sphere'):
                cmds.delete('interpTest_sphere')
            return False


    # Run tests
    logger.info("Starting interpolation system tests...")
    if run_interpolation_tests():
        logger.info("Interpolation tests completed successfully")
    else:
        logger.error("Interpolation tests failed")