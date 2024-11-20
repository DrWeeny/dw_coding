"""
Maya Attribute Utilities

A toolkit for managing Maya node attributes with a focus on pipeline integration.

Main Features:
    - Node IO Management:
        * Get input/output attributes
        * Support for common node types (mesh, nurbs, deformers)
        * Multi-attribute handling
        * Index management for array attributes

    - Attribute Creation:
        * All Maya attribute types supported
        * Compound attributes
        * Enum attributes with options
        * Array attributes with auto-indexing
        * Default values and ranges

    - Attribute Management:
        * Locking/Unlocking with states
        * Keyable state control
        * Channel box visibility
        * Batch operations

Functions:
    get_type_io: Get node's input/output attributes
    add_attr: Create or modify node attributes
    lock_attr: Manage attribute states and access


Common Usage:
    >>> # Basic attribute creation
    >>> add_attr('node', 'attrName', 1.0, keyable=True)

    >>> # Enum attribute with options
    >>> add_attr('node', 'enumAttr', 0, 'enum',
    ...          enumName=['Option1', 'Option2'])

    >>> # Get node connections
    >>> outputs = get_type_io('node', io=1)

    >>> # Lock multiple attributes
    >>> lock_attr('node', ['tx', 'ty', 'tz'], lock=True)


Dependencies:
    - Maya 2020+ (maya.cmds)
    - DW Maya Core Toolkit

Author: DrWeeny
Version: 1.0.0
"""

from typing import Union, List, Any, Optional, Literal, Dict
from maya import cmds, mel
from .dw_maya_data import flags
from .dw_maya_components import get_next_free_multi_index
from ..dw_decorators import acceptString
from dw_maya.dw_constants.node_attr_mappings import NODE_IO_MAPPING

# Type aliases
NodeName = AttrName = AttrPath = AttrType = str
AttrValue = Union[str, int, float, bool, List[Any]]



def get_type_io(node: NodeName, **kwargs) -> Union[str, List[str], None]:
    """
    Get main input/output attributes of a node.

    Args:
        node: Node name or type

    Kwargs:
        io (int): Input (0) or output (1) selector
        index/id: Multi attribute index
        multi/m (bool): Include index notation
        join/j (bool): Return full attribute path
        query/q (bool): Print supported node types

    Returns:
        Attribute name(s) or None

    Examples:
        >>> get_type_io('pSphere1', io=0)  # Input attr
        'pSphere1.inMesh'

        >>> get_type_io('wrap1', id=False)  # No index
        'wrap1.outputGeometry'
    """
    # Process flags
    io = flags(kwargs, 1, 'io')
    index = flags(kwargs, None, 'index', 'id')
    multi = flags(kwargs, 1, 'multi', 'm')
    join = flags(kwargs, True, 'join', 'j')
    query = flags(kwargs, False, 'query', 'q')

    # Ignore transforms
    if node == 'transform':
        return None

    if node not in cmds.ls(nt=True) and cmds.objExists(node):
        shapes = cmds.ls(
            node,
            dag=True,
            type='shape',
            ni=True,
            l=bool('|' in node)
        )
        node_type = cmds.nodeType(shapes[0] if shapes else node)
    else:
        node_type = node

    # Query mode
    if query:
        if node_type in NODE_IO_MAPPING:
            return NODE_IO_MAPPING[node_type]
        print("Supported node types:")
        for ntype, attrs in NODE_IO_MAPPING.items():
            print(f"{ntype}: {attrs}")
        raise ValueError(f"Node type '{node_type}' not supported")

    # Get attribute(s)
    try:
        attrs = NODE_IO_MAPPING[node_type][io]
    except KeyError:
        raise ValueError(f"Node type '{node_type}' not supported")

    # Process attributes
    if isinstance(attrs, list):
        if index is not None:
            attrs = attrs[index]

    # Handle multi index
    if not multi:
        if isinstance(attrs, list):
            attrs = [a.split('[')[0] for a in attrs]
        else:
            attrs = attrs.split('[')[0]
    elif '[' in str(attrs):
        if isinstance(attrs, list):
            attrs = [
                a.replace('[0]', f'[{get_next_free_multi_index(node + "." + a)}]')
                if multi == 2 else a.replace('[0]', '[0]')
                for a in attrs
            ]
        else:
            if multi == 2:
                attrs = attrs.replace('[0]',
                    f'[{get_next_free_multi_index(node + "." + attrs)}]'
                )
            else:
                attrs = attrs.replace('[0]', '[0]')

    # Join with node name
    if join:
        if isinstance(attrs, list):
            return [f'{node}.{attr}' for attr in attrs]
        return f'{node}.{attrs}'

    return attrs


# Supported attribute types
AttrType = Literal[
    'bool', 'long', 'short', 'byte', 'char',
    'float', 'double', 'doubleAngle', 'doubleLinear',
    'string', 'enum', 'message',
    'time', 'matrix', 'fltMatrix', 'reflectanceRGB', 'spectrumRGB',
    'float2', 'float3', 'double2', 'double3', 'long2', 'long3',
    'short2', 'short3']


def add_attr(node: NodeName,
             long_name: AttrName,
             value=None,
             attr_type: AttrType ='long',
             **kwargs) -> AttrPath:
    """
    Add or set attribute on Maya node.

    Args:
        node: Target node name
        long_name: Attribute long name
        value: Default value
        attr_type: Attribute data type

    Kwargs:
        shortName/sn (str): Attribute short name
        niceName/nn (str): Attribute nice name
        enumName/en (Union[str, List[str]]): Enum values
        minValue/min: Minimum value
        maxValue/max: Maximum value
        keyable/k (bool): Is keyable
        readable/r (bool): Is readable
        storable/s (bool): Is storable
        writable/w (bool): Is writable
        channelBox (bool): Show in channel box

    Returns:
        Full attribute path (node.attr)

    Examples:
        >>> add_attr('pSphere1', 'testFloat', 1.0)
        'pSphere1.testFloat'

        >>> add_attr('pSphere1', 'testEnum', 0, 'enum',
        ...          enumName=['A', 'B', 'C'])
        'pSphere1.testEnum'
    """

    attr_path = f'{node}.{long_name}'

    attr_path = f'{node}.{long_name}'

    # Check if attribute already exists
    if not cmds.attributeQuery(long_name, node=node, exists=True):
        # Initialize attribute data
        attr_data: Dict[str, Any] = {}

        # Process basic flags
        for long, short in [
            ('shortName', 'sn'),
            ('niceName', 'nn'),
            ('minValue', 'min'),
            ('maxValue', 'max'),
            ('keyable', 'k'),
            ('readable', 'r'),
            ('storable', 's'),
            ('writable', 'w')
        ]:
            if value := flags(kwargs, None, long, short):
                attr_data[long] = value

        # Handle attribute type specific setup
        if attr_type == "string":
            attr_data["dataType"] = attr_type

        elif attr_type == "enum":
            attr_data["attributeType"] = attr_type
            enum_value = flags(kwargs, None, 'enumName', 'en')

            if not enum_value:
                raise ValueError(
                    "Enum attributes require 'enumName' or 'en' flag"
                )

            # Process enum names
            if isinstance(enum_value, (list, tuple)):
                enum_str = ':'.join(map(str, enum_value)) + ':'
            elif isinstance(enum_value, str):
                if ':' not in enum_value:
                    raise ValueError(
                        "Enum string must be colon-separated values"
                    )
                enum_str = enum_value.rstrip(':') + ':'
            else:
                raise ValueError(
                    "enumName must be list or colon-separated string"
                )

            attr_data["enumName"] = enum_str

        else:
            attr_data["attributeType"] = attr_type

        # Handle default value
        if value is not None and attr_type != "string":
            attr_data["defaultValue"] = value

        # Create the attribute
        try:
            cmds.addAttr(node, longName=long_name, **attr_data)

            # Handle channelBox for non-keyable attrs
            if (
                    not attr_data.get('keyable', True) and
                    flags(kwargs, False, 'channelBox')
            ):
                cmds.setAttr(
                    attr_path,
                    channelBox=True
                )

        except Exception as e:
            raise RuntimeError(
                f"Failed to add attribute {long_name} to {node}: {str(e)}"
            )

    # Set value on existing attribute
    else:
        try:
            if attr_type == "string":
                cmds.setAttr(attr_path, value, type='string')
            else:
                if not isinstance(value, (list, tuple)):
                    value = [value]
                cmds.setAttr(attr_path, *value)

        except Exception as e:
            raise RuntimeError(
                f"Failed to set value on {attr_path}: {str(e)}"
            )

    return attr_path


@acceptString('attributes')
def lock_attr(
    node: str,
    attributes: Union[str, List[str]],
    lock: bool = True,
    keyable: bool = False,
    channel_box: Optional[bool] = None
) -> None:
    """
    Lock or unlock attributes of a Maya Class Node.

    Arguments:
        node (str): The node with the attributes to lock/unlock.
        attributes (list of str): The list of the attributes to lock/unlock.
        lock (bool): Whether to lock (True) or unlock (False) the attributes. Default is True.
        keyable (bool): Whether the attributes should be keyable (False will hide from channel box). Default is False.
    """
    try:
        # function if it is within dwNode
        for attr_name in attributes:
            node.setAttr(attr_name, lock=lock, keyable=keyable)
    except:
        for attr_name in attributes:
            attr_full = f"{node}.{attr_name}"
            if cmds.objExists(attr_full):
                # Set lock state first
                cmds.setAttr(attr_full, lock=lock)

                # Handle keyable/channelBox states when unlocked
                if not lock:
                    # Set keyable state
                    cmds.setAttr(attr_full, keyable=keyable)

                    # Handle channel box visibility
                    if channel_box is not None:
                        cmds.setAttr(attr_full, channelBox=channel_box)
            else:
                cmds.warning(f"Attribute {attr_full} does not exist on node {node}.")


if __name__ == "__main__":
    """
    Test Module Usage:
        This section contains test functions that run when the module
        is executed directly. Use these for:
        - Development testing
        - Function verification
        - Example demonstrations

    Run tests from Maya:
        import dw_maya.dw_maya_utils.dw_maya_attrs as attrs
        reload(attrs)  # Run tests
    """
    def run_tests():
        """Test function to verify module functionality."""
        try:
            # Create test node
            node = cmds.createNode('transform', name='test_node')

            # Test cases
            test_cases = [
                # (test_name, function, args, expected_result)
                (
                    "Float attr",
                    add_attr,
                    (node, 'testFloat', 1.0),
                    f"{node}.testFloat"
                ),
                (
                    "Enum attr",
                    add_attr,
                    (node, 'testEnum', 0, 'enum'),
                    f"{node}.testEnum"
                )
            ]

            for test_name, func, args, expected in test_cases:
                try:
                    result = func(*args)
                    assert result == expected, f"Expected {expected}, got {result}"
                    print(f"✓ {test_name} passed")
                except Exception as e:
                    print(f"✗ {test_name} failed: {str(e)}")

        finally:
            # Cleanup
            if cmds.objExists(node):
                cmds.delete(node)


    # Only runs when file is executed directly
    print("Running tests for dw_maya_attrs.py")
    run_tests()
