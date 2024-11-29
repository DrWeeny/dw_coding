# operations/flood.py
from typing import List, Optional, Tuple, Union
import numpy as np
from maya import cmds

from ..core import (
    WeightData,
    MeshDataFactory,
    WeightList,
    mesh_cache
)
from ..utils.validation import validate_operation_type
from dw_logger import get_logger

logger = get_logger()


class FloodOperation:
    """Handle flooding weight values on mesh components"""

    def __init__(self, mesh_name: str):
        self.mesh_name = mesh_name
        self.mesh_data = MeshDataFactory.get(mesh_name)

    def flood_selected(self,
                       weights: WeightList,
                       value: float,
                       operation: str = "replace",
                       clamp_min: Optional[float] = None,
                       clamp_max: Optional[float] = None) -> Optional[WeightList]:
        """Flood value on selected components.

        Args:
            weights: Original weight values
            value: Value to apply
            operation: Operation type ('replace', 'add', 'multiply')
            clamp_min: Optional minimum clamp value
            clamp_max: Optional maximum clamp value

        Returns:
            Modified weights or None if failed
        """
        try:
            # Validate : operation exists
            operation = validate_operation_type(operation)

            # Get selected components
            selected = self.mesh_data.get_selected_components()
            if not selected:
                logger.info("No components selected, flooding all vertices")
                return self.flood_all(weights, value, operation, clamp_min, clamp_max)

            # Create weight data instance
            weight_data = WeightData(weights, self.mesh_name)

            # Create component mask from selection
            mask = self._create_mask_from_selection(selected)

            # Apply operation
            result = (weight_data
                      .modify(value, operation, mask, clamp_min, clamp_max)
                      .as_list)

            return result

        except Exception as e:
            logger.error(f"Flood operation failed: {e}")
            return None

    def flood_all(self,
                  weights: WeightList,
                  value: float,
                  operation: str = "replace",
                  clamp_min: Optional[float] = None,
                  clamp_max: Optional[float] = None) -> Optional[WeightList]:
        """Flood value on all vertices.

        Args:
            weights: Original weight values
            value: Value to apply
            operation: Operation type ('replace', 'add', 'multiply')
            clamp_min: Optional minimum clamp value
            clamp_max: Optional maximum clamp value

        Returns:
            Modified weights or None if failed
        """
        try:
            # Validate operation
            operation = validate_operation_type(operation)

            # Create weight data instance
            weight_data = WeightData(weights, self.mesh_name)

            # Apply operation
            result = (weight_data
                      .modify(value, operation, None, clamp_min, clamp_max)
                      .as_list)

            return result

        except Exception as e:
            logger.error(f"Flood operation failed: {e}")
            return None

    def flood_in_range(self,
                       weights: WeightList,
                       value: float,
                       min_weight: float,
                       max_weight: float,
                       operation: str = "replace",
                       clamp_min: Optional[float] = None,
                       clamp_max: Optional[float] = None) -> Optional[WeightList]:
        """Flood value on vertices with weights in specified range.

        Args:
            weights: Original weight values
            value: Value to apply
            min_weight: Minimum weight value to affect
            max_weight: Maximum weight value to affect
            operation: Operation type ('replace', 'add', 'multiply')
            clamp_min: Optional minimum clamp value
            clamp_max: Optional maximum clamp value

        Returns:
            Modified weights or None if failed
        """
        try:
            # Validate operation
            operation = validate_operation_type(operation)

            # Create weight data instance
            weight_data = WeightData(weights, self.mesh_name)

            # Create mask for weights in range
            weight_array = np.array(weights)
            mask = (weight_array >= min_weight) & (weight_array <= max_weight)

            # Apply operation
            result = (weight_data
                      .modify(value, operation, mask.nonzero()[0].tolist(), clamp_min, clamp_max)
                      .as_list)

            return result

        except Exception as e:
            logger.error(f"Flood in range operation failed: {e}")
            return None

    def _create_mask_from_selection(self, selected: List[str]) -> List[Union[int, Tuple[int, int]]]:
        """Create component mask from selected vertices"""
        mask = []
        for comp in selected:
            indices = self._parse_component_indices(comp)
            if indices:
                mask.extend(indices)
        return mask

    def _parse_component_indices(self, component: str) -> List[Union[int, Tuple[int, int]]]:
        """Parse component indices from component name"""
        import re
        if match := re.search(r'\[(\d+)(?::(\d+))?\]', component):
            start = int(match.group(1))
            if match.group(2):  # Range
                end = int(match.group(2))
                return [(start, end + 1)]
            return [start]
        return []


def flood_weights(mesh_name: str,
                  weights: WeightList,
                  value: float,
                  operation: str = "replace",
                  clamp_min: Optional[float] = None,
                  clamp_max: Optional[float] = None) -> Optional[WeightList]:
    """High-level function for flooding weights.

    Args:
        mesh_name: Name of mesh
        weights: Original weight values
        value: Value to apply
        operation: Operation type ('replace', 'add', 'multiply')
        clamp_min: Optional minimum clamp value
        clamp_max: Optional maximum clamp value

    Returns:
        Modified weights or None if failed
    """
    flood_op = FloodOperation(mesh_name)
    return flood_op.flood_selected(weights, value, operation, clamp_min, clamp_max)


if __name__ == '__main__':
    def run_flood_tests():
        """Test flood operations"""
        try:
            # Create test sphere
            sphere = cmds.polySphere(radius=1, name='floodTest_sphere')[0]
            vertex_count = cmds.polyEvaluate(sphere, vertex=True)

            # Create test weights
            test_weights = [0.0] * vertex_count

            # Test flood all
            flood_op = FloodOperation(sphere)

            # Test 1: Flood all vertices
            result1 = flood_op.flood_all(test_weights, 0.5, "replace")
            assert all(w == 0.5 for w in result1)
            logger.info("Flood all test passed")

            # Test 2: Flood with selection
            cmds.select(f"{sphere}.vtx[0:10]")
            result2 = flood_op.flood_selected(test_weights, 1.0, "replace")
            assert all(result2[i] == 1.0 for i in range(11))
            assert all(result2[i] == 0.0 for i in range(11, vertex_count))
            logger.info("Flood selected test passed")

            # Test 3: Flood in range
            test_weights = [i / vertex_count for i in range(vertex_count)]
            result3 = flood_op.flood_in_range(test_weights, 0.5, 0.3, 0.7, "replace")
            logger.info("Flood in range test passed")

            # Cleanup
            cmds.delete(sphere)
            return True

        except Exception as e:
            logger.error(f"Flood tests failed: {e}")
            if cmds.objExists('floodTest_sphere'):
                cmds.delete('floodTest_sphere')
            return False


    # Run tests
    logger.info("Starting flood operation tests...")
    if run_flood_tests():
        logger.info("Flood tests completed successfully")
    else:
        logger.error("Flood tests failed")