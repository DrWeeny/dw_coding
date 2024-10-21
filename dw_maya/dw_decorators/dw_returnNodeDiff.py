import maya.cmds as cmds
from functools import wraps


def returnNodeDiff(func):
    """
    Decorator that tracks the difference in Maya nodes before and after
    the execution of the wrapped function, returning any newly created nodes.

    Args:
        func (function): The function to wrap.

    Returns:
        function: The wrapped function with a list of new nodes created.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Get the list of nodes before the function runs
        nodes_before = set(cmds.ls())

        # Execute the wrapped function
        result = func(*args, **kwargs)

        # Get the list of nodes after the function runs
        nodes_after = set(cmds.ls())

        # Calculate the difference (new nodes created)
        node_diff = list(nodes_after - nodes_before)

        # Return both the function result and the list of new nodes
        return result, node_diff

    return wrapper
