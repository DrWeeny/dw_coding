import maya.cmds as cmds
from functools import wraps
from typing import Tuple, List, Any
from dw_logger import get_logger


def returnNodeDiff(func):
    """
    Decorator that returns any new Maya nodes created by the wrapped function.

    Args:
        func: The function to wrap

    Returns:
        Tuple containing (original function result, list of new nodes)
    """
    @wraps(func)
    def wrapper(*args, **kwargs) -> Tuple[Any, List[str]]:
        nodes_before = set(cmds.ls())
        result = func(*args, **kwargs)
        if len(result) < len(nodes_before):
            nodes_after = list(set(nodes_before-cmds.ls()))
            logger = get_logger()
            logger.info(f'# Function "{func.__name__}" has deleted {nodes_after}')
        else:
            nodes_after = list(set(cmds.ls()) - nodes_before)
        return result, nodes_after

    return wrapper