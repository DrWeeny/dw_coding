# operations/mirror.py
from typing import List, Optional, Tuple, Union, Literal
import numpy as np
from maya import cmds

from ..core import (
    WeightData,
    MeshDataFactory,
    WeightList,
    VectorUtils,
    mesh_cache
)
from dw_logger import get_logger

logger = get_logger()


class MirrorOperation:
    """Handle mirroring of weight values across mesh axes"""

    def __init__(self, mesh_name: str):
        self.mesh_name = mesh_name
        self.mesh_data = MeshDataFactory.get(mesh_name)

    def mirror_weights(self,
                       weights: WeightList,
                       axis: Literal['x', 'y', 'z'] = 'x',
                       tolerance: float = 0.001,
                       world_space: bool = True,
                       direction: Literal['positive', 'negative'] = 'positive',
                       ) -> Optional[WeightList]:
        """Mirror weights across specified axis.

        Args:
            weights: Original weight values
            axis: Axis to mirror across ('x', 'y', 'z')
            tolerance: Position matching tolerance
            world_space: Use world space coordinates
            direction: Direction to mirror from ('positive' or 'negative')

        Returns:
            Mirrored weights or None if failed
        """
        try:
            # Get vertex positions
            positions = self.mesh_data.vertex_positions
            if positions is None:
                logger.error("Failed to get vertex positions")
                return None

            # Create weight data instance
            weight_data = WeightData(weights, self.mesh_name)
            original_weights = weight_data.weights

            # Find mirror pairs
            pairs = self._find_mirror_pairs(positions, axis, tolerance)

            # Apply mirroring based on direction
            new_weights = np.array(original_weights, dtype=np.float32)
            axis_idx = {'x': 0, 'y': 1, 'z': 2}[axis.lower()]

            for i, j in pairs.items():
                if direction == 'positive':
                    if positions[i][axis_idx] > 0:
                        new_weights[j] = original_weights[i]
                    else:
                        new_weights[i] = original_weights[j]
                else:  # negative
                    if positions[i][axis_idx] < 0:
                        new_weights[j] = original_weights[i]
                    else:
                        new_weights[i] = original_weights[j]

            return new_weights.tolist()

        except Exception as e:
            logger.error(f"Mirror operation failed: {e}")
            return None

    def _find_mirror_pairs(self,
                           positions: np.ndarray,
                           axis: str,
                           tolerance: float) -> dict:
        """Find vertex pairs for mirroring"""
        pairs = {}
        axis_idx = {'x': 0, 'y': 1, 'z': 2}[axis.lower()]
        vertex_count = len(positions)

        for i in range(vertex_count):
            if i in pairs:
                continue

            pos1 = positions[i]
            found_pair = False

            for j in range(i + 1, vertex_count):
                if j in pairs:
                    continue

                pos2 = positions[j]

                # Check mirror conditions
                if (abs(pos1[axis_idx] + pos2[axis_idx]) < tolerance and
                        abs(pos1[(axis_idx + 1) % 3] - pos2[(axis_idx + 1) % 3]) < tolerance and
                        abs(pos1[(axis_idx + 2) % 3] - pos2[(axis_idx + 2) % 3]) < tolerance):
                    pairs[i] = j
                    pairs[j] = i
                    found_pair = True
                    break

            # Handle vertices on mirror plane
            if not found_pair and abs(pos1[axis_idx]) < tolerance:
                pairs[i] = i

        return pairs

    def mirror_selected(self,
                        weights: WeightList,
                        axis: Literal['x', 'y', 'z'] = 'x',
                        tolerance: float = 0.001) -> Optional[WeightList]:
        """Mirror weights for selected vertices only"""
        try:
            selected = self.mesh_data.get_selected_components()
            if not selected:
                logger.warning("No components selected")
                return weights

            # Get vertex indices from selection
            selected_indices = set()
            for comp in selected:
                idx = self._parse_component_index(comp)
                if idx is not None:
                    selected_indices.add(idx)

            # Get mirror pairs for selected vertices only
            positions = self.mesh_data.vertex_positions
            pairs = self._find_mirror_pairs(positions, axis, tolerance)

            # Apply mirroring only to selected vertices and their pairs
            new_weights = np.array(weights, dtype=np.float32)
            for idx in selected_indices:
                if idx in pairs:
                    pair_idx = pairs[idx]
                    if positions[idx][{'x': 0, 'y': 1, 'z': 2}[axis.lower()]] > 0:
                        new_weights[pair_idx] = weights[idx]

            return new_weights.tolist()

        except Exception as e:
            logger.error(f"Mirror selected operation failed: {e}")
            return weights

    def _parse_component_index(self, component: str) -> Optional[int]:
        """Extract vertex index from component name"""
        import re
        if match := re.search(r'vtx\[(\d+)\]', component):
            return int(match.group(1))
        return None


def mirror_weights(mesh_name: str,
                   weights: WeightList,
                   axis: Literal['x', 'y', 'z'] = 'x',
                   tolerance: float = 0.001,
                   world_space: bool = True,
                   direction: Literal['positive', 'negative'] = 'positive') -> Optional[WeightList]:
    """High-level function for mirroring weights.

    Args:
        mesh_name: Name of mesh
        weights: Original weight values
        axis: Axis to mirror across
        tolerance: Position matching tolerance
        world_space: Use world space coordinates
        direction: Direction to mirror from

    Returns:
        Mirrored weights or None if failed
    """
    mirror_op = MirrorOperation(mesh_name)
    return mirror_op.mirror_weights(weights, axis, tolerance, world_space, direction)


if __name__ == '__main__':
    def run_mirror_tests():
        """Test mirror operations"""
        try:
            # Create test sphere
            sphere = cmds.polySphere(radius=1, name='mirrorTest_sphere')[0]
            vertex_count = cmds.polyEvaluate(sphere, vertex=True)

            # Create asymmetric test weights
            test_weights = []
            for i in range(vertex_count):
                pos = cmds.xform(f"{sphere}.vtx[{i}]", q=True, ws=True, t=True)
                test_weights.append(1.0 if pos[0] > 0 else 0.0)

            # Test mirror operation
            mirror_op = MirrorOperation(sphere)

            # Test 1: Full mirror X axis
            result1 = mirror_op.mirror_weights(test_weights, 'x')
            logger.info("Full mirror test passed")

            # Test 2: Mirror selected only
            cmds.select(f"{sphere}.vtx[0:10]")
            result2 = mirror_op.mirror_selected(test_weights, 'x')
            logger.info("Mirror selected test passed")

            # Test 3: Mirror with different axes
            for axis in ['y', 'z']:
                result = mirror_op.mirror_weights(test_weights, axis)
                logger.info(f"Mirror {axis} axis test passed")

            # Cleanup
            cmds.delete(sphere)
            return True

        except Exception as e:
            logger.error(f"Mirror tests failed: {e}")
            if cmds.objExists('mirrorTest_sphere'):
                cmds.delete('mirrorTest_sphere')
            return False


    # Run tests
    logger.info("Starting mirror operation tests...")
    if run_mirror_tests():
        logger.info("Mirror tests completed successfully")
    else:
        logger.error("Mirror tests failed")