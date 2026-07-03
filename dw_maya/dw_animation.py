from typing import List, Optional, Tuple
from maya import cmds
from dw_maya.dw_decorators import singleUndoChunk
from dw_logger import get_logger

logger = get_logger()


@singleUndoChunk
def offset_animation(value: float,
                     nodes: Optional[List[str]] = None,
                     attributes: Tuple[str, ...] = ('tx', 'ty', 'tz'),
                     time_range: Optional[Tuple[float, float]] = None,
                     relative: bool = True) -> int:
    """Offset (or set) the value of every keyframe on the given attributes.

    Args:
        value: Amount to add to every key (or the absolute value to set
            when relative=False).
        nodes: Nodes to process; defaults to the current selection.
        attributes: Attribute names to edit, defaults to ('tx', 'ty', 'tz').
        time_range: Optional (start, end) to only edit keys in that range;
            defaults to the whole animation.
        relative: True adds value to each key, False sets each key to value.

    Returns:
        Number of node.attr plugs that were edited.

    Example:
        >>> offset_animation(5.0)                            # tx ty tz +5 on selection
        >>> offset_animation(2.5, attributes=('ty',))        # ty only
        >>> offset_animation(0.0, relative=False)            # flatten keys to 0
        >>> offset_animation(1.0, time_range=(1001, 1050))   # only that range
    """
    target_nodes = nodes if nodes else cmds.ls(selection=True)
    if not target_nodes:
        cmds.warning("offset_animation: nothing selected and no nodes given.")
        return 0

    feed = {'edit': True,
            'includeUpperBound': True,
            'valueChange': value,
            'relative': relative,
            'absolute': not relative}
    if time_range:
        feed['time'] = (time_range[0], time_range[1])

    edited = 0
    for node in target_nodes:
        for attr in attributes:
            plug = f"{node}.{attr}"
            if not cmds.objExists(plug):
                logger.warning(f"offset_animation: {plug} does not exist, skipped.")
                continue
            if not cmds.keyframe(plug, query=True, keyframeCount=True):
                logger.debug(f"offset_animation: {plug} has no keys, skipped.")
                continue
            cmds.keyframe(plug, **feed)
            edited += 1

    mode = "offset by" if relative else "set to"
    logger.info(f"offset_animation: {edited} plug(s) {mode} {value}.")
    return edited


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