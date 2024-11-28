from typing import List, Optional
from maya import cmds
from dw_logger import get_logger

logger = get_logger()


def delete_redundant_curves(all_nodes: bool = True) -> List[str]:
    """Delete animation curves that have constant values across all keyframes.

    This function finds and removes animation curves where all keyframes have
    the same value, effectively cleaning up redundant animations.

    Args:
        all_nodes: If True, process all nodes in the scene. If False, only
                  process selected nodes.

    Returns:
        List of animation curves that were not processed

    Raises:
        ValueError: If no nodes are selected when all_nodes=False

    Example:
        >>> remaining = delete_redundant_curves()  # Process all nodes
        >>> remaining = delete_redundant_curves(False)  # Process only selection
    """
    # Get all animation curves in the scene
    all_curves = cmds.ls(type=["animCurveTL", "animCurveTA", "animCurveTU"]) or []

    # Get nodes to process
    if all_nodes:
        # Get unique connected nodes for all curves
        connected_nodes = set()
        for curve in all_curves:
            connections = cmds.listConnections(curve)
            if connections:
                connected_nodes.update(connections)
        target_nodes = list(connected_nodes)
    else:
        # Use selected nodes
        target_nodes = cmds.ls(selection=True)
        if not target_nodes:
            raise ValueError("No nodes selected. Please select nodes to process.")

    # Track processed curves
    processed_curves = set()

    # Process each node
    for node in target_nodes:
        # Find all animation curves connected to this node
        anim_curves = cmds.findKeyframe(node, curve=True, controlPoints=True, shape=True) or []

        if anim_curves:
            for curve in anim_curves:
                try:
                    # Get all values on this curve
                    values = cmds.keyframe(curve, query=True, valueChange=True)

                    # Check if all values are the same
                    if values and len(set(values)) == 1:
                        logger.debug(f"Deleting constant curve: {curve}")
                        cmds.delete(curve)

                    processed_curves.add(curve)

                except Exception as e:
                    logger.warning(f"Failed to process curve {curve}: {e}")
                    continue

    # Get remaining unprocessed curves
    remaining_curves = list(set(all_curves) - processed_curves)

    logger.info(f"Processed {len(processed_curves)} curves, "
                f"{len(remaining_curves)} remaining")

    return remaining_curves