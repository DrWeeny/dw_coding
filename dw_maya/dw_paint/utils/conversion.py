# utils/conversion.py
from typing import List, Dict, Union, Optional, Any, Tuple
import numpy as np
from maya import cmds, mel
from dw_logger import get_logger

logger = get_logger()

# Type aliases
WeightList = List[float]
WeightArray = np.ndarray
MayaWeightData = Union[List[float], str]  # Maya can return weights as string


def to_weight_list(data: Any) -> Optional[WeightList]:
    """Convert various data types to weight list.

    Args:
        data: Input data (list, array, string, etc.)

    Returns:
        List of float weights or None if conversion fails
    """
    try:
        if isinstance(data, str):
            # Handle Maya string representation
            return [float(x) for x in data.split()]
        elif isinstance(data, np.ndarray):
            return data.tolist()
        elif isinstance(data, (list, tuple)):
            return [float(x) for x in data]
        else:
            raise ValueError(f"Unsupported data type: {type(data)}")

    except Exception as e:
        logger.error(f"Weight list conversion failed: {e}")
        return None


def to_numpy_array(data: Any) -> Optional[WeightArray]:
    """Convert data to numpy array.

    Args:
        data: Input data

    Returns:
        Numpy array of weights or None if conversion fails
    """
    try:
        if isinstance(data, np.ndarray):
            return data

        weights = to_weight_list(data)
        if weights is not None:
            return np.array(weights, dtype=np.float32)

        return None

    except Exception as e:
        logger.error(f"Numpy array conversion failed: {e}")
        return None


def convert_range_to_indices(range_str: str) -> Optional[List[int]]:
    """Convert Maya range notation to list of indices.

    Args:
        range_str: Maya range string (e.g., "0:5", "1,3,5")

    Returns:
        List of indices or None if conversion fails
    """
    try:
        indices = []
        for part in range_str.split(','):
            if ':' in part:
                start, end = map(int, part.split(':'))
                indices.extend(range(start, end + 1))
            else:
                indices.append(int(part))
        return indices

    except Exception as e:
        logger.error(f"Range conversion failed: {e}")
        return None


def indices_to_range_str(indices: List[int]) -> str:
    """Convert list of indices to Maya range notation.

    Args:
        indices: List of indices

    Returns:
        Maya range string
    """
    if not indices:
        return ""

    ranges = []
    start = indices[0]
    prev = start

    for i in indices[1:] + [None]:
        if i != prev + 1:
            if start == prev:
                ranges.append(str(start))
            else:
                ranges.append(f"{start}:{prev}")
            start = i
        prev = i

    return ','.join(ranges)


def normalize_weights(weights: WeightList,
                      min_val: float = 0.0,
                      max_val: float = 1.0) -> WeightList:
    """Normalize weights to specified range.

    Args:
        weights: Input weights
        min_val: Target minimum value
        max_val: Target maximum value

    Returns:
        Normalized weights
    """
    if not weights:
        return []

    arr = np.array(weights)
    curr_min = np.min(arr)
    curr_max = np.max(arr)

    if curr_min == curr_max:
        return [min_val] * len(weights)

    normalized = min_val + (arr - curr_min) * (max_val - min_val) / (curr_max - curr_min)
    return normalized.tolist()


def component_to_mesh_and_index(component: str) -> Optional[Tuple[str, int]]:
    """Convert component name to mesh name and index.

    Args:
        component: Component name (e.g., "pSphere1.vtx[0]")

    Returns:
        Tuple of (mesh_name, index) or None if conversion fails
    """
    try:
        import re
        if match := re.match(r"(.*?)\.vtx\[(\d+)\]", component):
            mesh_name = match.group(1)
            index = int(match.group(2))
            return mesh_name, index
        return None

    except Exception as e:
        logger.error(f"Component conversion failed: {e}")
        return None


def mel_array_to_python(mel_array: str) -> Optional[List[Any]]:
    """Convert MEL array string to Python list.

    Args:
        mel_array: MEL array string (e.g., "{1,2,3}")

    Returns:
        Python list or None if conversion fails
    """
    try:
        # Remove braces and split
        content = mel_array.strip('{}')
        if not content:
            return []

        # Parse elements
        elements = []
        for item in content.split(','):
            item = item.strip('" ')
            try:
                # Try converting to number
                elements.append(float(item))
            except ValueError:
                # Keep as string if not a number
                elements.append(item)

        return elements

    except Exception as e:
        logger.error(f"MEL array conversion failed: {e}")
        return None

def remap_weights(weight_list: List[Union[float, int]],
                  old_min: float,
                  old_max: float,
                  new_min: float,
                  new_max: float,
                  mask: List[Union[List[int], List[float]]] = None,
                  clamp: bool = True) -> List[float]:
    """
    Remap values from one range to another, with optional masking.
    Formula: new_value = (value - old_min) * (new_max - new_min) / (old_max - old_min) + new_min

    Args:
        weight_list: List of numerical values to remap
        old_min: Current minimum value in range
        old_max: Current maximum value in range
        new_min: Target minimum value
        new_max: Target maximum value
        mask: Optional list of index specifications [[0,5], [9], [100,150]]
        clamp: If True, clamp values to new range

    Returns:
        List of remapped values
    """
    if not weight_list:
        return []

    try:
        arr = np.array(weight_list, dtype=float)
    except (ValueError, TypeError):
        raise TypeError("weight_list must contain only numerical values")

    if old_min >= old_max:
        raise ValueError(f"old_min ({old_min}) must be less than old_max ({old_max})")
    if new_min >= new_max:
        raise ValueError(f"new_min ({new_min}) must be less than new_max ({new_max})")

    # Prepare remapping function
    def remap(values):
        remapped = (values - old_min) * (new_max - new_min) / (old_max - old_min) + new_min
        if clamp:
            remapped = np.clip(remapped, new_min, new_max)
        return remapped

    if mask is None or not mask:
        # Remap entire array
        arr = remap(arr)
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
            arr[indices] = remap(arr[indices])

        except Exception as e:
            raise ValueError(f"Error processing mask: {str(e)}")

    return arr.tolist()

if __name__ == '__main__':
    def run_conversion_tests():
        """Test conversion functionality"""
        try:
            # Test weight list conversion
            data_types = [
                [0.1, 0.2, 0.3],
                np.array([0.1, 0.2, 0.3]),
                "0.1 0.2 0.3"
            ]

            for data in data_types:
                result = to_weight_list(data)
                assert len(result) == 3
                assert all(isinstance(x, float) for x in result)
                logger.info(f"Weight list conversion test passed for {type(data)}")

            # Test range conversion
            indices = list(range(10))
            range_str = indices_to_range_str(indices)
            converted = convert_range_to_indices(range_str)
            assert converted == indices
            logger.info("Range conversion test passed")

            # Test normalization
            weights = [1, 2, 3, 4, 5]
            normalized = normalize_weights(weights, 0, 1)
            assert min(normalized) == 0
            assert max(normalized) == 1
            logger.info("Weight normalization test passed")

            # Test component conversion
            component = "pSphere1.vtx[0]"
            result = component_to_mesh_and_index(component)
            assert result == ("pSphere1", 0)
            logger.info("Component conversion test passed")

            # Test MEL array conversion
            mel_str = "{1,2.5,\"string\"}"
            result = mel_array_to_python(mel_str)
            assert len(result) == 3
            assert isinstance(result[0], float)
            assert isinstance(result[2], str)
            logger.info("MEL array conversion test passed")

            return True

        except Exception as e:
            logger.error(f"Conversion tests failed: {e}")
            return False


    # Run tests
    logger.info("Starting conversion tests...")
    if run_conversion_tests():
        logger.info("Conversion tests completed successfully")
    else:
        logger.error("Conversion tests failed")