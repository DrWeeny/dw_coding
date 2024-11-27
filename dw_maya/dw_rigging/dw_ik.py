"""
Utility functions for creating stretchy IK setups in Maya.

This module provides functions for creating various types of stretchy IK systems,
including spline IK and conditional stretch setups. These setups can be used for
character limbs, tentacles, ropes, or any other deformable elements that need
stretching behavior.

Main Features:
    - Spline IK with automatic stretch
    - Conditional stretch based on curve length
    - Support for multiple joints
    - Automatic node connection setup
    - Length-based scaling

Example Usage:

1. Creating a basic stretchy spline IK:
    ```python
    # Create a joint chain
    joints = ['shoulder_jnt', 'elbow_jnt', 'wrist_jnt']

    # Create stretchy IK using existing curve
    try:
        nodes = create_stretchy_spline_ik(
            joint_chain=joints,
            curve='arm_curve'
        )
        print(f"Created IK handle: {nodes['ikHandle']}")

    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}")
    ```

2. Setting up conditional stretch:
    ```python
    # Setup stretch with greater than condition
    try:
        nodes = setup_stretch_ik(
            name="arm_stretch",
            curve="arm_curve",
            joint_chain="shoulder_jnt",
            operation=2  # Greater than
        )

        # Access created nodes
        curve_info = nodes['curveInfo']
        divide_node = nodes['divide']
        condition = nodes['condition']

    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}")
    ```

3. Creating spline IK with selected curve:
    ```python
    # Select your curve in Maya, then run:
    try:
        nodes = create_stretchy_spline_ik(
            joint_chain=['spine1_jnt', 'spine2_jnt', 'spine3_jnt']
        )

    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}")
    ```

4. Setting up leg stretch with custom condition:
    ```python
    # Setup stretch that only works when leg is extended
    try:
        nodes = setup_stretch_ik(
            name="leg_stretch",
            curve="leg_curve",
            joint_chain="hip_jnt",
            operation=4  # Less than
        )

    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}")
    ```

Note:
    - Always ensure your joints and curves exist before running these functions
    - Joint chains should be properly oriented (aimed down X-axis for standard setup)
    - Curves should be properly positioned relative to the joint chain
    - Consider using try/except blocks to handle potential errors
"""

from maya import cmds
from typing import List, Tuple, Optional, Dict
from dw_logger import get_logger

logger = get_logger()


def setup_stretch_ik(
        name: str,
        curve: str,
        joint_chain: str,
        operation: int = 2) -> Dict[str, str]:
    """
    Create a stretchy IK setup with conditional stretching based on curve length.

    Args:
        name: Base name for created nodes
        curve: Name of the curve transform node
        joint_chain: Root joint name (will affect all child joints)
        operation: Condition node operation (default 2: Greater Than)
            0: Equal, 1: Not Equal, 2: Greater, 3: Greater or Equal,
            4: Less Than, 5: Less or Equal

    Returns:
        Dictionary of created node names:
        {
            'curveInfo': Curve info node name,
            'divide': Multiply/divide node name,
            'condition': Condition node name
        }

    Raises:
        ValueError: If inputs are invalid
        RuntimeError: If setup fails
    """
    if not cmds.objExists(curve):
        raise ValueError(f"Curve '{curve}' does not exist")

    if not cmds.objExists(joint_chain):
        raise ValueError(f"Joint '{joint_chain}' does not exist")

    try:
        # Get curve shape
        curve_shapes = cmds.listRelatives(curve, shapes=True)
        if not curve_shapes:
            raise ValueError(f"No shape found for curve '{curve}'")
        curve_shape = curve_shapes[0]

        # Create nodes
        nodes = {}

        # Create curveInfo node
        nodes['curveInfo'] = cmds.createNode('curveInfo',
                                             name=f'{name}_info')

        # Connect curve to curveInfo
        cmds.connectAttr(f'{curve_shape}.worldSpace[0]',
                         f'{nodes["curveInfo"]}.inputCurve',
                         force=True)

        # Create multiply/divide node
        nodes['divide'] = cmds.createNode('multiplyDivide',
                                          name=f'{name}_divide')
        cmds.setAttr(f'{nodes["divide"]}.operation', 2)  # Division

        # Connect curveInfo to divide node
        cmds.connectAttr(f'{nodes["curveInfo"]}.arcLength',
                         f'{nodes["divide"]}.input1X',
                         force=True)

        # Get initial curve length
        curve_length = cmds.getAttr(f'{nodes["curveInfo"]}.arcLength')
        if curve_length <= 0:
            raise ValueError("Invalid curve length")

        # Set initial length as division factor
        cmds.setAttr(f'{nodes["divide"]}.input2X', curve_length)

        # Create condition node
        nodes['condition'] = cmds.createNode('condition',
                                             name=f'{name}_condition')
        cmds.setAttr(f'{nodes["condition"]}.operation', operation)
        cmds.setAttr(f'{nodes["condition"]}.secondTerm', curve_length)

        # Connect nodes to condition
        cmds.connectAttr(f'{nodes["curveInfo"]}.arcLength',
                         f'{nodes["condition"]}.firstTerm',
                         force=True)
        cmds.connectAttr(f'{nodes["divide"]}.outputX',
                         f'{nodes["condition"]}.colorIfTrueR',
                         force=True)
        cmds.setAttr(f'{nodes["condition"]}.colorIfFalseR', 1.0)

        # Connect to all joints in chain
        joints = cmds.ls(joint_chain, dag=True, type='joint')
        for joint in joints:
            cmds.connectAttr(f'{nodes["condition"]}.outColorR',
                             f'{joint}.scaleX',
                             force=True)

        logger.info(f"Successfully created conditional stretch setup for {name}")
        return nodes

    except Exception as e:
        raise RuntimeError(f"Failed to create stretch setup: {e}")

def create_stretchy_spline_ik(
        joint_chain: List[str],
        curve: Optional[str] = None) -> Dict[str, str]:
    """
    Create a stretchy IK spline setup for a joint chain.

    Args:
        joint_chain: List of joint names in order (start to end)
        curve: Optional curve name. If None, uses selected curve

    Returns:
        Dictionary containing created node names:
        {
            'ikHandle': IK handle name,
            'curveInfo': Curve info node name,
            'multiply': Multiply divide node name
        }

    Raises:
        ValueError: If joint chain is invalid or curve doesn't exist
        RuntimeError: If IK setup fails
    """

    if len(joint_chain) < 2:
        raise ValueError("Joint chain must contain at least 2 joints")

    # Validate joints
    for joint in joint_chain:
        if not cmds.objExists(joint):
            raise ValueError(f"Joint '{joint}' does not exist")
        if cmds.nodeType(joint) != "joint":
            raise ValueError(f"'{joint}' is not a joint")

    try:
        # Get curve if not specified
        if not curve:
            selection = cmds.ls(selection=True, type='transform')
            if not selection:
                raise ValueError("No curve specified and nothing selected")
            curve = selection[0]

        if not cmds.objExists(curve):
            raise ValueError(f"Curve '{curve}' does not exist")

        # Create IK spline handle
        ik_handle, ik_effector = cmds.ikHandle(
            startJoint=joint_chain[0],
            endEffector=joint_chain[-1],
            curve=curve,
            name=f"{curve}_ikHandle",
            solver='ikSplineSolver',
            createCurve=False,
            rootOnCurve=True,
            parentCurve=False
        )

        # Get initial curve length
        curve_length = cmds.arclen(curve)
        joint_count = len(joint_chain)
        segment_length = curve_length / (joint_count - 1)

        # Create nodes for stretch setup
        curve_info = cmds.createNode('curveInfo', name=f"{curve}_curveInfo")
        multiply_divide = cmds.createNode('multiplyDivide', name=f"{curve}_divide")

        # Setup multiply divide node
        cmds.setAttr(f"{multiply_divide}.operation", 2)  # Division
        cmds.setAttr(f"{multiply_divide}.input2X", curve_length)

        # Connect curve to curveInfo
        curve_shape = cmds.listRelatives(curve, shapes=True)
        if not curve_shape:
            raise RuntimeError(f"Cannot find shape node for curve {curve}")

        cmds.connectAttr(f"{curve_shape[0]}.worldSpace[0]", f"{curve_info}.inputCurve")
        cmds.connectAttr(f"{curve_info}.arcLength", f"{multiply_divide}.input1X")

        # Setup joints
        for joint in joint_chain:
            # Set initial translation
            cmds.setAttr(f"{joint}.translateX", segment_length)
            # Connect stretch
            cmds.connectAttr(f"{multiply_divide}.outputX", f"{joint}.scaleX")

        logger.info(f"Successfully created stretchy IK spline for {joint_chain[0]}")

        return {
            'ikHandle': ik_handle,
            'curveInfo': curve_info,
            'multiply': multiply_divide
        }

    except Exception as e:
        raise RuntimeError(f"Failed to create stretchy IK spline: {e}")