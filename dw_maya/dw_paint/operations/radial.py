# operations/radial.py
import numpy as np
from typing import List, Optional, Tuple, Union, Literal
from maya import cmds

from ..core import (
    WeightData,
    MeshDataFactory,
    WeightList,
    VectorUtils,
    mesh_cache
)
from ..utils.falloff import apply_falloff
from dw_logger import get_logger

logger = get_logger()


class RadialOperation:
    """Handle radial weight operations based on distance from center point"""

    def __init__(self, mesh_name: str):
        self.mesh_name = mesh_name
        self.mesh_data = MeshDataFactory.get(mesh_name)

    def set_weights_radial(self,
                           center: Optional[Tuple[float, float, float]] = None,
                           radius: Optional[float] = None,
                           falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
                           invert: bool = False,
                           use_volume: bool = False) -> Optional[WeightList]:
        """Set weights based on radial distance from center point.

        Args:
            center: Center point for radial calculation (defaults to mesh center)
            radius: Maximum radius (defaults to auto-calculate)
            falloff: Type of falloff curve
            invert: Invert the resulting weights
            use_volume: Use volume-based falloff instead of surface distance

        Returns:
            Weight list or None if failed
        """
        try:
            positions = self.mesh_data.vertex_positions
            if positions is None:
                return None

            # Calculate center if not provided
            if center is None:
                center = self.mesh_data.get_center()
            center = np.array(center)

            # Calculate distances
            if use_volume:
                distances = self._calculate_volume_distances(positions, center)
            else:
                distances = np.linalg.norm(positions - center, axis=1)

            # Use max distance as radius if not provided
            if radius is None:
                radius = np.max(distances)

            # Normalize distances to weights
            weights = np.zeros_like(distances, dtype=np.float32)
            mask = distances <= radius
            weights[mask] = 1.0 - (distances[mask] / radius)

            # Apply falloff
            weights = apply_falloff(weights, falloff)

            # Invert if requested
            if invert:
                weights = 1.0 - weights

            return weights.tolist()

        except Exception as e:
            logger.error(f"Radial weight operation failed: {e}")
            return None

    def set_weights_spherical(self,
                              center: Optional[Tuple[float, float, float]] = None,
                              radius: Optional[float] = None,
                              axis: Literal['x', 'y', 'z'] = 'y',
                              falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
                              angle_range: Tuple[float, float] = (0.0, 360.0)) -> Optional[WeightList]:
        """Set weights based on spherical coordinates.

        Args:
            center: Center point (defaults to mesh center)
            radius: Maximum radius (defaults to auto-calculate)
            axis: Main axis for angular calculation
            falloff: Type of falloff curve
            angle_range: Range of angles in degrees for weight distribution

        Returns:
            Weight list or None if failed
        """
        try:
            positions = self.mesh_data.vertex_positions
            if positions is None:
                return None

            # Calculate center if not provided
            if center is None:
                center = self.mesh_data.get_center()
            center = np.array(center)

            # Convert angle range to radians
            angle_min, angle_max = np.radians(angle_range)

            # Calculate spherical coordinates
            relative_pos = positions - center

            # Get angles based on axis
            if axis == 'y':
                angles = np.arctan2(relative_pos[:, 0], relative_pos[:, 2])
            elif axis == 'x':
                angles = np.arctan2(relative_pos[:, 1], relative_pos[:, 2])
            else:  # z
                angles = np.arctan2(relative_pos[:, 0], relative_pos[:, 1])

            # Normalize angles to 0-1 range based on angle_range
            weights = (angles - angle_min) / (angle_max - angle_min)
            weights = np.clip(weights, 0.0, 1.0)

            # Apply falloff
            weights = apply_falloff(weights, falloff)

            return weights.tolist()

        except Exception as e:
            logger.error(f"Spherical weight operation failed: {e}")
            return None

    def set_weights_cylindrical(self,
                                axis: Literal['x', 'y', 'z'] = 'y',
                                falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
                                center: Optional[Tuple[float, float, float]] = None,
                                radius: Optional[float] = None) -> Optional[WeightList]:
        """Set weights based on cylindrical distance from axis.

        Args:
            axis: Main axis for cylindrical calculation
            falloff: Type of falloff curve
            center: Center point (defaults to mesh center)
            radius: Maximum radius (defaults to auto-calculate)

        Returns:
            Weight list or None if failed
        """
        try:
            positions = self.mesh_data.vertex_positions
            if positions is None:
                return None

            # Calculate center if not provided
            if center is None:
                center = self.mesh_data.get_center()
            center = np.array(center)

            # Calculate distances from axis
            relative_pos = positions - center
            if axis == 'y':
                distances = np.sqrt(relative_pos[:, 0] ** 2 + relative_pos[:, 2] ** 2)
            elif axis == 'x':
                distances = np.sqrt(relative_pos[:, 1] ** 2 + relative_pos[:, 2] ** 2)
            else:  # z
                distances = np.sqrt(relative_pos[:, 0] ** 2 + relative_pos[:, 1] ** 2)

            # Use max distance as radius if not provided
            if radius is None:
                radius = np.max(distances)

            # Normalize distances to weights
            weights = np.zeros_like(distances, dtype=np.float32)
            mask = distances <= radius
            weights[mask] = 1.0 - (distances[mask] / radius)

            # Apply falloff
            weights = apply_falloff(weights, falloff)

            return weights.tolist()

        except Exception as e:
            logger.error(f"Cylindrical weight operation failed: {e}")
            return None

    def _calculate_volume_distances(self, positions: np.ndarray, center: np.ndarray) -> np.ndarray:
        """Calculate volume-based distances"""
        # Get bounding box
        bbox_min, bbox_max = self.mesh_data.get_bounding_box()
        bbox_size = bbox_max - bbox_min

        # Normalize positions relative to bounding box
        normalized_pos = (positions - bbox_min) / bbox_size
        normalized_center = (center - bbox_min) / bbox_size

        # Calculate distances considering volume
        distances = np.linalg.norm(normalized_pos - normalized_center, axis=1)
        return distances


def set_radial_weights(mesh_name: str,
                       center: Optional[Tuple[float, float, float]] = None,
                       radius: Optional[float] = None,
                       falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
                       mode: Literal['radial', 'spherical', 'cylindrical'] = 'radial',
                       axis: Literal['x', 'y', 'z'] = 'y') -> Optional[WeightList]:
    """High-level function for setting radial weights.

    Args:
        mesh_name: Name of mesh
        center: Center point (defaults to mesh center)
        radius: Maximum radius (defaults to auto-calculate)
        falloff: Type of falloff curve
        mode: Type of radial calculation
        axis: Main axis for spherical/cylindrical modes

    Returns:
        Weight list or None if failed
    """
    radial_op = RadialOperation(mesh_name)

    if mode == 'radial':
        return radial_op.set_weights_radial(center, radius, falloff)
    elif mode == 'spherical':
        return radial_op.set_weights_spherical(center, radius, axis, falloff)
    else:  # cylindrical
        return radial_op.set_weights_cylindrical(axis, falloff, center, radius)


if __name__ == '__main__':
    def run_radial_tests():
        """Test radial operations"""
        try:
            # Create test sphere
            sphere = cmds.polySphere(radius=1, name='radialTest_sphere')[0]

            # Test radial operation
            radial_op = RadialOperation(sphere)

            # Test 1: Basic radial weights
            result1 = radial_op.set_weights_radial()
            logger.info("Basic radial test passed")

            # Test 2: Spherical weights
            result2 = radial_op.set_weights_spherical()
            logger.info("Spherical weights test passed")

            # Test 3: Cylindrical weights
            result3 = radial_op.set_weights_cylindrical()
            logger.info("Cylindrical weights test passed")

            # Test 4: Different falloff types
            for falloff in ['linear', 'quadratic', 'smooth', 'smooth2']:
                result = radial_op.set_weights_radial(falloff=falloff)
                logger.info(f"Falloff {falloff} test passed")

            # Cleanup
            cmds.delete(sphere)
            return True

        except Exception as e:
            logger.error(f"Radial tests failed: {e}")
            if cmds.objExists('radialTest_sphere'):
                cmds.delete('radialTest_sphere')
            return False


    # Run tests
    logger.info("Starting radial operation tests...")
    if run_radial_tests():
        logger.info("Radial tests completed successfully")
    else:
        logger.error("Radial tests failed")