import re
from typing import List, Optional, Union, Dict, Tuple, Literal
import numpy as np
from dw_logger import get_logger
from .mesh_data import MeshDataFactory

logger = get_logger()

# Type Aliases
WeightList = List[float]
WeightArray = np.ndarray
ComponentMask = List[Union[List[int], Tuple[int, int]]]
OperationType = Literal['multiply', 'add', 'replace']


class WeightData:
    """Class to handle vertex weight operations"""

    def __init__(self, weights: Union[WeightList, WeightArray], mesh_name: str):
        self.mesh_name = mesh_name
        self._weights = np.array(weights, dtype=np.float32)
        self._mesh_data = MeshDataFactory.get(mesh_name)

        # Validate weights length matches vertex count
        if len(self._weights) != self._mesh_data.vertex_count:
            raise ValueError(
                f"Weight count ({len(self._weights)}) doesn't match vertex count ({self._mesh_data.vertex_count})")

    @property
    def weights(self) -> WeightArray:
        """Get weights as numpy array"""
        return self._weights

    @property
    def as_list(self) -> WeightList:
        """Get weights as Python list"""
        return self._weights.tolist()

    def modify(self,
               value: float,
               operation: OperationType = "replace",
               mask: Optional[ComponentMask] = None,
               clamp_min: Optional[float] = None,
               clamp_max: Optional[float] = None) -> 'WeightData':
        """Modify weights with value based on operation.

        Args:
            value: Value to apply
            operation: Type of operation
            mask: Optional component mask for selective modification
            clamp_min: Optional minimum clamp value
            clamp_max: Optional maximum clamp value

        Returns:
            Self for method chaining
        """
        # Create mask array if provided
        if mask:
            mask_array = np.zeros(len(self._weights), dtype=bool)
            for m in mask:
                if isinstance(m, (list, tuple)) and len(m) == 2:
                    mask_array[m[0]:m[1]] = True
                else:
                    mask_array[m] = True
        else:
            mask_array = np.ones(len(self._weights), dtype=bool)

        # Apply operation
        if operation == "multiply":
            self._weights[mask_array] *= value
        elif operation == "add":
            self._weights[mask_array] += value
        else:  # replace
            self._weights[mask_array] = value

        # Apply clamping if specified
        if clamp_min is not None:
            self._weights = np.maximum(self._weights, clamp_min)
        if clamp_max is not None:
            self._weights = np.minimum(self._weights, clamp_max)

        return self

    def mirror(self,
               axis: Literal['x', 'y', 'z'] = 'x',
               tolerance: float = 0.001) -> 'WeightData':
        """Mirror weights across specified axis"""
        positions = self._mesh_data.vertex_positions
        axis_idx = {'x': 0, 'y': 1, 'z': 2}[axis.lower()]

        # Find mirror pairs
        pairs: Dict[int, int] = {}
        for i in range(len(positions)):
            if i in pairs:
                continue
            for j in range(i + 1, len(positions)):
                if j in pairs:
                    continue

                # Check mirror conditions
                pos1, pos2 = positions[i], positions[j]
                if (abs(pos1[axis_idx] + pos2[axis_idx]) < tolerance and
                        abs(pos1[(axis_idx + 1) % 3] - pos2[(axis_idx + 1) % 3]) < tolerance and
                        abs(pos1[(axis_idx + 2) % 3] - pos2[(axis_idx + 2) % 3]) < tolerance):
                    pairs[i] = j
                    pairs[j] = i
                    break

        # Apply mirroring
        new_weights = self._weights.copy()
        for i, j in pairs.items():
            new_weights[j] = self._weights[i]

        self._weights = new_weights
        return self

    def normalize(self, min_val: float = 0.0, max_val: float = 1.0) -> 'WeightData':
        """Normalize weights to specified range"""
        if np.all(self._weights == self._weights[0]):
            self._weights[:] = min_val
        else:
            self._weights = min_val + (max_val - min_val) * (
                    (self._weights - np.min(self._weights)) /
                    (np.max(self._weights) - np.min(self._weights))
            )
        return self

    def invert(self) -> 'WeightData':
        """Invert weight values"""
        self._weights = 1.0 - self._weights
        return self

    def smooth(self, iterations: int = 1, factor: float = 0.5) -> 'WeightData':
        """Smooth weights based on topology"""
        neighbors = self._mesh_data.neighbors
        current = self._weights.copy()

        for _ in range(iterations):
            neighbor_avg = np.zeros_like(current)
            for i, neighbor_indices in neighbors.items():
                if neighbor_indices:
                    neighbor_avg[i] = np.mean(current[neighbor_indices])

            self._weights = current * (1.0 - factor) + neighbor_avg * factor
            current = self._weights.copy()

        return self

    def get_selected_weights(self) -> WeightArray:
        """Get weights for selected components"""
        selected = self._mesh_data.get_selected_components()
        if not selected:
            return np.array([])

        indices = []
        for comp in selected:
            if match := re.search(r'\[(\d+)(?::(\d+))?\]', comp):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else start
                indices.extend(range(start, end + 1))

        return self._weights[indices]

    def get_stats(self) -> Dict[str, float]:
        """Get weight statistics"""
        return {
            "min": float(np.min(self._weights)),
            "max": float(np.max(self._weights)),
            "mean": float(np.mean(self._weights)),
            "std": float(np.std(self._weights)),
            "non_zero": int(np.count_nonzero(self._weights))
        }


class WeightDataFactory:
    """Factory for creating and managing WeightData instances"""

    _instances: Dict[str, WeightData] = {}

    @classmethod
    def create(cls, weights: Union[WeightList, WeightArray], mesh_name: str) -> WeightData:
        """Create new WeightData instance"""
        instance = WeightData(weights, mesh_name)
        cls._instances[mesh_name] = instance
        return instance

    @classmethod
    def get(cls, mesh_name: str) -> Optional[WeightData]:
        """Get existing WeightData instance"""
        return cls._instances.get(mesh_name)

    @classmethod
    def clear(cls) -> None:
        """Clear all instances"""
        cls._instances.clear()

def modify_weights(weight_list: List[Union[float, int]],
                   value: float,
                   operation: Literal['multiply', 'add', 'replace'] = 'replace',
                   mask: List[Union[List[int], List[float]]] = None,
                   min_value: float = None,
                   max_value: float = None) -> List[float]:
    """
    Modify an array of weights by multiplying, adding or replacing with a value.

    Args:
        weight_list: List of numerical values (float or int)
        value: Value to multiply, add, or replace with
        operation: 'multiply', 'add', or 'replace'
        mask: List of index specifications, where each spec can be:
              - Single index as [i]
              - Range as [start, end] (end is exclusive)
              Example: [[0,5], [9], [100,150]] will affect indices 0-4, 9, and 100-149
        min_value: Optional minimum value to clamp results
        max_value: Optional maximum value to clamp results

    Returns:
        List of modified weights
    """
    if not weight_list:
        return []

    try:
        arr = np.array(weight_list, dtype=float)
    except (ValueError, TypeError):
        raise TypeError("weight_list must contain only numerical values")

    if not isinstance(value, (int, float)):
        raise TypeError("value must be a number")

    if operation not in ['multiply', 'add', 'replace']:
        raise ValueError("operation must be either 'multiply', 'add', or 'replace'")

    if min_value is not None and max_value is not None and min_value > max_value:
        raise ValueError(f"min_value ({min_value}) cannot be greater than max_value ({max_value})")

    if mask is None or not mask:
        # Apply operation to entire array
        if operation == 'multiply':
            arr = arr * value
        elif operation == 'add':
            arr = arr + value
        else:  # replace
            arr[:] = value
    else:
        try:
            mask_arange = []
            for m in mask:
                if not isinstance(m, list):
                    raise TypeError(f"Each mask element must be a list, got {type(m)}")

                if len(m) not in (1, 2):
                    raise ValueError(f"Mask elements must be [index] or [start,end], got {m}")

                if len(m) == 1:
                    if m[0] >= len(arr):
                        raise ValueError(f"Index {m[0]} out of range for array of length {len(arr)}")
                    mask_arange.append(np.array([m[0]]))
                else:
                    start, end = m
                    if end > len(arr):
                        raise ValueError(f"End index {end} out of range for array of length {len(arr)}")
                    if start >= end:
                        raise ValueError(f"Start index {start} must be less than end index {end}")
                    mask_arange.append(np.arange(start, end))

            indices = np.concatenate(mask_arange)
            if operation == 'multiply':
                arr[indices] *= value
            elif operation == 'add':
                arr[indices] += value
            else:  # replace
                arr[indices] = value

        except Exception as e:
            raise ValueError(f"Error processing mask: {str(e)}")

    # Apply clamping if specified
    if min_value is not None:
        arr = np.maximum(arr, min_value)
    if max_value is not None:
        arr = np.minimum(arr, max_value)

    return arr.tolist()

def blend_weight_lists(
        weights_a: List[float],
        weights_b: List[float],
        blend_factor: float
) -> List[float]:
    """Blend between two weight lists."""
    return [
        a * (1 - blend_factor) + b * blend_factor
        for a, b in zip(weights_a, weights_b)
    ]


if __name__ == '__main__':
    from maya import cmds


    def run_weight_tests():
        """Run tests for weight operations"""
        try:
            # Create a test sphere
            sphere = cmds.polySphere(radius=1, name='weightTest_sphere')[0]
            logger.info(f"Created test sphere: {sphere}")

            # Get vertex count
            vertex_count = cmds.polyEvaluate(sphere, vertex=True)

            # Create test weights
            test_weights = [0.0] * vertex_count
            for i in range(vertex_count):
                # Create gradient based on height (Y position)
                pos = cmds.xform(f"{sphere}.vtx[{i}]", q=True, ws=True, t=True)
                test_weights[i] = (pos[1] + 1.0) / 2.0  # Normalize Y from [-1,1] to [0,1]

            # Create weight data instance
            weight_data = WeightDataFactory.create(test_weights, sphere)

            # Test various operations
            logger.info("Testing weight operations...")

            # Test smoothing
            smoothed = weight_data.smooth(iterations=2, factor=0.5).as_list
            logger.info("Smoothing completed")

            # Test modification with mask
            mask = [[0, 10], [20, 30]]  # Modify vertices 0-10 and 20-30
            modified = (WeightDataFactory
                        .create(smoothed, sphere)
                        .modify(value=0.8, operation='multiply', mask=mask)
                        .as_list)
            logger.info("Modification with mask completed")

            # Test mirroring
            mirrored = (WeightDataFactory
                        .create(modified, sphere)
                        .mirror(axis='x')
                        .as_list)
            logger.info("Mirroring completed")

            # Get statistics
            stats = weight_data.get_stats()
            logger.info(f"Weight statistics: {stats}")

            # Cleanup
            cmds.delete(sphere)
            WeightDataFactory.clear()
            logger.info("Test cleanup completed")

            return True

        except Exception as e:
            logger.error(f"Test failed: {e}")
            # Cleanup on error
            if cmds.objExists('weightTest_sphere'):
                cmds.delete('weightTest_sphere')
            return False


    def test_performance():
        """Test performance of weight operations"""
        try:
            # Create a high-resolution mesh for performance testing
            dense_sphere = cmds.polySphere(radius=1, subdivisionsX=50, subdivisionsY=50, name='perfTest_sphere')[0]
            vertex_count = cmds.polyEvaluate(dense_sphere, vertex=True)

            # Create test weights
            import time
            from dw_maya.dw_decorators import timeIt

            @timeIt
            def run_operations():
                test_weights = np.random.random(vertex_count)
                weight_data = WeightDataFactory.create(test_weights, dense_sphere)

                # Chain multiple operations
                result = (weight_data
                          .normalize()
                          .smooth(iterations=5)
                          .modify(value=0.5, operation='multiply')
                          .mirror()
                          .as_list)

                return result

            # Run performance test
            result = run_operations()

            # Cleanup
            cmds.delete(dense_sphere)
            WeightDataFactory.clear()

            return True

        except Exception as e:
            logger.error(f"Performance test failed: {e}")
            if cmds.objExists('perfTest_sphere'):
                cmds.delete('perfTest_sphere')
            return False


    # Run tests
    logger.info("Starting weight system tests...")

    if run_weight_tests():
        logger.info("Basic tests completed successfully")
    else:
        logger.error("Basic tests failed")

    if test_performance():
        logger.info("Performance tests completed successfully")
    else:
        logger.error("Performance tests failed")
