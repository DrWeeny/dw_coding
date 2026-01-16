import maya.cmds as cmds
from functools import wraps
from typing import Tuple, List, Any, Union
from dw_logger import get_logger

logger = get_logger()

def returnNodeDiff(func):
    """
    Decorator that returns any new Maya nodes created by the wrapped function.

    Args:
        func: The function to wrap

    Returns:
        Tuple containing (original function result, list of new nodes)
    """

    @wraps(func)
    def wrapper(*args, **kwargs) -> Union[List[str], Tuple[Any, List[str]]]:
        nodes_before = set(cmds.ls())
        result = func(*args, **kwargs)
        nodes_current = set(cmds.ls())

        # Calculate new nodes
        nodes_after = list(nodes_current - nodes_before)

        # Log if nodes were deleted
        if len(nodes_current) < len(nodes_before):
            deleted_nodes = nodes_before - nodes_current
            logger.info(f'# Function "{func.__name__}" has deleted {deleted_nodes}')

        # Return based on function result
        if not result:
            return nodes_after
        return result, nodes_after

    return wrapper