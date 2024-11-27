
from typing import List, Optional, Set, Union
from maya import cmds
from .dw_maya_data import flags

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

def lsTr(*args, **kwargs) -> List[str]:
    """
    Enhanced listing of transform nodes combining cmds.ls and cmds.listRelatives.
    Handles Maya-style flags and provides additional functionality for transform queries.

    Args:
        *args: Arguments passed to cmds.ls. Can include:
            - Node names or wildcards
            - Lists of nodes
            - Mix of shapes and transforms
        **kwargs: Supports both long and short flags:
            - parent/p (bool): Get parent transforms (default: True)
            - long/l (bool): Use long names
            - unique/u (bool): Remove duplicates (default: True)
            - noIntermediate/ni (bool): Skip intermediate objects (default: True)
            + Any valid cmds.ls flags

    Returns:
        List of transform nodes or their parents

    Example:
        >>> lsTr(sl=True, type="mesh")  # Selected objects
        ['pSphere1', 'pCube1']

        >>> lsTr(sl=True, l=True)  # Long names
        ['|Scene|pSphere1', '|Scene|pCube1']
    """
    # Check if there are long name inside the first argument
    long_name_default = False
    if args and isinstance(args[0], (list, tuple)):
        if any('|' in s for s in args[0]):
            long_name_default = True

    # Process flags
    parent = flags(kwargs, None, 'parent', 'p')
    long_name = flags(kwargs, long_name_default, 'long', 'l')
    unique = flags(kwargs, True, 'unique', 'u')

    relatives_flags = {'parent': parent if parent else True}
    # Clean up processed flags
    for flag in ['parent', 'p', 'long', 'l', 'unique', 'u']:
        kwargs.pop(flag, None)

    if long_name:
        # this is only for the corresponding flag of listRelatives
        relatives_flags['f'] = True

    # Default intermediate handling
    if not any(key in kwargs for key in ['ni', 'noIntermediate']):
        kwargs['ni'] = True

    def is_shape_transform(node: str) -> bool:
        """Check if node is a transform with only shape children."""
        if cmds.nodeType(node) != 'transform':
            return False

        children = cmds.listRelatives(node, c=True) or []
        if not children:
            return False

        # Check if all children are shapes
        return all(
            cmds.nodeType(child) != 'transform'
            for child in children
        )

    # Standard ls processing
    results = cmds.ls(*args, **kwargs) or []

    # Process all nodes to ensure they're shape transforms
    filtered_results = []
    for node in results:
        if cmds.nodeType(node.split(".")[0]) == 'transform':
            if is_shape_transform(node.split(".")[0]):
                filtered_results.append(node)
        else:
            # For shapes, get parent transform
            try:
                parents = cmds.listRelatives(node, p=True, f=bool(long_name))
                if parents and is_shape_transform(parents[0]):
                    filtered_results.extend(parents)
            except Exception:
                continue

    # Handle unique flag
    if unique and filtered_results:
        filtered_results = list(dict.fromkeys(filtered_results))

    return filtered_results
