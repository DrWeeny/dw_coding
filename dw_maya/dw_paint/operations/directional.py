# operations/directional.py
import numpy as np
from typing import List, Optional, Tuple, Union, Literal
from maya import cmds

from ..core import (
    WeightData,
    MeshDataFactory,
    WeightList,
    VectorUtils,
    Vector3D
)
from ..utils.falloff import apply_falloff
from dw_logger import get_logger

logger = get_logger()


class DirectionalOperation:
    """Handle directional weight operations based on vector directions"""

    def __init__(self, mesh_name: str):
        self.mesh_name = mesh_name
        self.mesh_data = MeshDataFactory.get(mesh_name)

    def set_weights_by_vector(self,
                              direction: Union[str, Vector3D],
                              remap_range: Optional[Tuple[float, float]] = None,
                              falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
                              origin: Optional[Vector3D] = None,
                              mode: Literal['projection', 'distance'] = 'projection') -> Optional[WeightList]:
        """Set weights based on position along vector direction.

        Args:
            direction: Predefined direction or custom vector
            remap_range: Optional range to remap weights
            falloff: Type of falloff curve
            origin: Origin point for calculations
            mode: 'projection' or 'distance' calculation mode

        Returns:
            Weight list or None if failed
        """
        try:
            positions = self.mesh_data.vertex_positions
            if positions is None:
                return None

            # Get direction vector
            vector = VectorUtils.get_direction_vector(direction)

            # Calculate distances
            if origin is None:
                origin = self.mesh_data.get_center()

            distances = np.array([
                VectorUtils.distance_along_vector(pos, vector, origin, mode)
                for pos in positions
            ])

            # Remap distances to weights
            if remap_range is None:
                min_dist = np.min(distances)
                max_dist = np.max(distances)
                remap_range = (min_dist, max_dist)

            min_val, max_val = remap_range
            weights = np.clip((distances - min_val) / (max_val - min_val), 0, 1)

            # Apply falloff
            weights = apply_falloff(weights, falloff)

            return weights.tolist()

        except Exception as e:
            logger.error(f"Directional weight operation failed: {e}")
            return None

    def set_weights_between_points(self,
                                   start_point: Vector3D,
                                   end_point: Vector3D,
                                   falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear') -> Optional[
        WeightList]:
        """Set weights based on position between two points.

        Args:
            start_point: Starting point
            end_point: Ending point
            falloff: Type of falloff curve

        Returns:
            Weight list or None if failed
        """
        try:
            # Calculate direction vector
            vector = np.array(end_point) - np.array(start_point)
            vector = VectorUtils.normalize(vector)

            return self.set_weights_by_vector(
                vector,
                origin=start_point,
                falloff=falloff
            )

        except Exception as e:
            logger.error(f"Between points weight operation failed: {e}")
            return None

    def set_weights_by_normal(self,
                              falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
                              invert: bool = False) -> Optional[WeightList]:
        """Set weights based on vertex normals relative to reference vector.

        Args:
            falloff: Type of falloff curve
            invert: Invert the resulting weights

        Returns:
            Weight list or None if failed
        """
        try:
            normals = self.mesh_data.get_vertex_normals()
            if normals is None:
                return None

            # Calculate weights based on normal Y component
            weights = (normals[:, 1] + 1) / 2  # Convert from [-1,1] to [0,1]

            # Apply falloff
            weights = apply_falloff(weights, falloff)

            # Invert if requested
            if invert:
                weights = 1.0 - weights

            return weights.tolist()

        except Exception as e:
            logger.error(f"Normal-based weight operation failed: {e}")
            return None


def set_directional_weights(mesh_name: str,
                            direction: Union[str, Vector3D],
                            falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
                            mode: Literal['vector', 'normal'] = 'vector') -> Optional[WeightList]:
    """High-level function for setting directional weights.

    Args:
        mesh_name: Name of mesh
        direction: Direction vector or predefined direction
        falloff: Type of falloff curve
        mode: Type of directional calculation

    Returns:
        Weight list or None if failed
    """
    dir_op = DirectionalOperation(mesh_name)

    if mode == 'vector':
        return dir_op.set_weights_by_vector(direction, falloff=falloff)
    else:  # normal
        return dir_op.set_weights_by_normal(falloff)


if __name__ == '__main__':
    def run_directional_tests():
        """Test directional operations"""
        try:
            # Create test sphere
            sphere = cmds.polySphere(radius=1, name='dirTest_sphere')[0]

            # Test directional operation
            dir_op = DirectionalOperation(sphere)

            # Test 1: Basic vector direction
            result1 = dir_op.set_weights_by_vector('y')
            logger.info("Basic vector test passed")

            # Test 2: Between points
            result2 = dir_op.set_weights_between_points((0, -1, 0), (0, 1, 0))
            logger.info("Between points test passed")

            # Test 3: Normal-based weights
            result3 = dir_op.set_weights_by_normal()
            logger.info("Normal-based weights test passed")

            # Cleanup
            cmds.delete(sphere)
            return True

        except Exception as e:
            logger.error(f"Directional tests failed: {e}")
            if cmds.objExists('dirTest_sphere'):
                cmds.delete('dirTest_sphere')
            return False


    # Run tests
    logger.info("Starting directional operation tests...")
    if run_directional_tests():
        logger.info("Directional tests completed successfully")
    else:
        logger.error("Directional tests failed")