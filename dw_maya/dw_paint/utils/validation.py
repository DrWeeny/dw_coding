# utils/validation.py
from typing import Optional, Union, List, Tuple, Literal, Any
import re
from maya import cmds
from dw_logger import get_logger
import dw_maya.dw_maya_utils as dwu

logger = get_logger()

# Type aliases
OperationType = Literal['replace', 'add', 'multiply', 'subtract']
WeightValue = Union[float, int]
ComponentMask = List[Union[int, Tuple[int, int]]]

def compare_two_nodes_list(node_list1,
                           node_list2):
    # Find objects that are in both lists
    matching = [mesh for mesh in node_list1 if mesh in node_list2]

    # Find objects in meshes but not in selection
    not_selected = [mesh for mesh in node_list1 if mesh not in node_list2]

    # Find selected objects that aren't in meshes list
    extra_selected = [obj for obj in node_list2 if obj not in node_list1]

    return matching, not_selected, extra_selected

def guess_if_component_sel(meshes: list):
    sel_mesh = dwu.lsTr(sl=True, dag=True, o=True, type='mesh')
    _check_components = dwu.lsTr(sl=True)
    is_component = dwu.component_in_list(_check_components)
    sel_compo = []
    if not sel_mesh and not meshes:
        cmds.error("No mesh selected and no cloth mesh provided.")
        return
    if is_component:
       match, _, _ = compare_two_nodes_list(meshes, sel_mesh)
       if match:
            for m in match:
                for s in _check_components:
                    if s.startswith(m):
                        sel_compo.append(s)
    return sel_compo

def validate_operation_type(operation: str) -> OperationType:
    """Validate and normalize operation type.

    Args:
        operation: Operation type string

    Returns:
        Normalized operation type

    Raises:
        ValueError: If operation type is invalid
    """
    operation = operation.lower()
    valid_operations = {'replace', 'add', 'multiply', 'subtract'}

    if operation not in valid_operations:
        raise ValueError(
            f"Invalid operation type: {operation}. "
            f"Must be one of: {', '.join(valid_operations)}"
        )

    return operation


def validate_weight_value(value: Any,
                          min_val: float = 0.0,
                          max_val: float = 1.0) -> float:
    """Validate and convert weight value.

    Args:
        value: Value to validate
        min_val: Minimum allowed value
        max_val: Maximum allowed value

    Returns:
        Validated float value

    Raises:
        ValueError: If value is invalid or out of range
    """
    try:
        float_val = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Weight value must be a number, got: {value}")

    if not min_val <= float_val <= max_val:
        raise ValueError(
            f"Weight value {float_val} out of range [{min_val}, {max_val}]"
        )

    return float_val


def validate_mesh(mesh_name: str) -> bool:
    """Validate mesh exists and is valid.

    Args:
        mesh_name: Name of mesh to validate

    Returns:
        True if mesh is valid
    """
    if not cmds.objExists(mesh_name):
        logger.error(f"Mesh does not exist: {mesh_name}")
        return False

    if cmds.objectType(mesh_name) not in ['mesh', 'transform']:
        logger.error(f"Object is not a mesh: {mesh_name}")
        return False

    return True


def validate_component_mask(mask: ComponentMask,
                            vertex_count: int) -> Optional[ComponentMask]:
    """Validate component mask indices.

    Args:
        mask: Component mask to validate
        vertex_count: Total number of vertices

    Returns:
        Validated mask or None if invalid
    """
    try:
        validated_mask = []
        for item in mask:
            if isinstance(item, (tuple, list)) and len(item) == 2:
                start, end = item
                if not (0 <= start < vertex_count and 0 <= end <= vertex_count):
                    raise ValueError(f"Invalid range: [{start}:{end}]")
                validated_mask.append((start, end))
            else:
                idx = int(item)
                if not 0 <= idx < vertex_count:
                    raise ValueError(f"Invalid index: {idx}")
                validated_mask.append(idx)
        return validated_mask

    except Exception as e:
        logger.error(f"Invalid component mask: {e}")
        return None


def validate_component_name(component: str) -> Optional[Tuple[str, int]]:
    """Validate and parse component name.

    Args:
        component: Component name (e.g., "pSphere1.vtx[0]")

    Returns:
        Tuple of (mesh_name, component_index) or None if invalid
    """
    pattern = r"^(.*?)\.vtx\[(\d+)\]$"
    if match := re.match(pattern, component):
        mesh_name = match.group(1)
        index = int(match.group(2))

        if validate_mesh(mesh_name):
            return mesh_name, index

    return None


def validate_falloff_type(falloff: str) -> str:
    """Validate falloff type.

    Args:
        falloff: Falloff type string

    Returns:
        Validated falloff type

    Raises:
        ValueError: If falloff type is invalid
    """
    valid_falloffs = {'linear', 'quadratic', 'smooth', 'smooth2'}
    falloff = falloff.lower()

    if falloff not in valid_falloffs:
        raise ValueError(
            f"Invalid falloff type: {falloff}. "
            f"Must be one of: {', '.join(valid_falloffs)}"
        )

    return falloff


def validate_axis(axis: str) -> str:
    """Validate axis specification.

    Args:
        axis: Axis string ('x', 'y', 'z')

    Returns:
        Validated axis string

    Raises:
        ValueError: If axis is invalid
    """
    axis = axis.lower()
    if axis not in {'x', 'y', 'z'}:
        raise ValueError(f"Invalid axis: {axis}. Must be 'x', 'y', or 'z'")
    return axis


if __name__ == '__main__':
    def run_validation_tests():
        """Test validation functions"""
        try:
            # Test operation type validation
            assert validate_operation_type('replace') == 'replace'
            assert validate_operation_type('ADD') == 'add'
            try:
                validate_operation_type('invalid')
                assert False, "Should raise ValueError"
            except ValueError:
                pass

            # Test weight value validation
            assert validate_weight_value(0.5) == 0.5
            assert validate_weight_value('1.0') == 1.0
            try:
                validate_weight_value('invalid')
                assert False, "Should raise ValueError"
            except ValueError:
                pass

            # Test mesh validation
            sphere = cmds.polySphere(name='validationTest_sphere')[0]
            assert validate_mesh(sphere)
            assert not validate_mesh('nonexistent_mesh')

            # Test component mask validation
            mask = [0, (1, 3), 5]
            validated = validate_component_mask(mask, 10)
            assert validated is not None
            assert len(validated) == 3

            # Test component name validation
            component = f"{sphere}.vtx[0]"
            result = validate_component_name(component)
            assert result is not None
            assert result[0] == sphere
            assert result[1] == 0

            # Cleanup
            cmds.delete(sphere)
            logger.info("All validation tests passed")
            return True

        except Exception as e:
            logger.error(f"Validation tests failed: {e}")
            if cmds.objExists('validationTest_sphere'):
                cmds.delete('validationTest_sphere')
            return False


    # Run tests
    logger.info("Starting validation tests...")
    if run_validation_tests():
        logger.info("Validation tests completed successfully")
    else:
        logger.error("Validation tests failed")