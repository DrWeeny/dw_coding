
from typing import List, Optional, Set, Union
from maya import cmds
from .dw_maya_data import flags
from dw_logger import get_logger
logger = get_logger()

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

def lsTr(*args, **kwargs) -> List[str]:
    """
    Enhanced listing of transform nodes combining cmds.ls and cmds.listRelatives.

    Designed for GUI use: always returns the named transform (what the user sees
    in the outliner), never raw shapes or empty groups — regardless of whether
    the user selected a transform or its underlying shape.

    Args:
        *args: Arguments passed to cmds.ls. Can include:
            - Node names or wildcards
            - Lists of nodes
            - Mix of shapes and transforms
        **kwargs: Supports both long and short flags:
            - long/l (bool): Use long names (auto-detected if input contains '|')
            - unique/u (bool): Remove duplicates (default: True)
            - noIntermediate/ni (bool): Skip intermediate objects (default: True)
            + Any valid cmds.ls flags

    Note:
        'parent/p' is accepted but ignored — lsTr always returns transforms.
        Groups (transforms with no shape children) are always excluded.

    Returns:
        List of transform nodes (never shapes, never empty groups)
    """

    # Detect long names in first arg
    long_name_default = False
    if args and isinstance(args[0], (list, tuple)):
        if any('|' in s for s in args[0]):
            long_name_default = True

    # 'parent/p' has no effect in lsTr — always returns transforms
    if any(k in kwargs for k in ('parent', 'p')):
        logger.warning(
            "lsTr: 'parent/p' flag has no effect and will be ignored. "
            "lsTr always returns transforms, never shapes or parent nodes."
        )

    # Process flags
    parent   = flags(kwargs, None, 'parent', 'p')
    long_name = flags(kwargs, long_name_default, 'long', 'l')
    unique   = flags(kwargs, True, 'unique', 'u')

    for flag in ['parent', 'p', 'long', 'l', 'unique', 'u']:
        kwargs.pop(flag, None)

    # Default intermediate handling
    if not any(key in kwargs for key in ['ni', 'noIntermediate']):
        kwargs['ni'] = True

    # --- type injection ---
    raw_type = kwargs.pop('type', None)
    if raw_type is None:
        type_list = ['transform']
    elif isinstance(raw_type, str):
        type_list = list(dict.fromkeys(['transform', raw_type]))
    else:
        type_list = list(dict.fromkeys(['transform'] + list(raw_type)))
    target_types = [t for t in type_list if t != 'transform']

    # --- assemblies mode ---
    is_assemblies = kwargs.get('assemblies', kwargs.get('ass', False))

    if is_assemblies:
        # Pass 1: real top-level transforms, no type filter
        top_nodes = cmds.ls(*args, assemblies=True, long=True,
                            **{k: v for k, v in kwargs.items()
                               if k not in ('assemblies', 'ass', 'type', 'long', 'l')}) or []

        # Auto long-name: if results contain pipes, keep long form
        if not long_name and any('|' in n for n in top_nodes):
            long_name = True

        # Pass 2: filter top nodes whose DIRECT children match target types
        filtered_results = []
        for node in top_nodes:
            shape_children = cmds.listRelatives(node, shapes=True, f=True) or []
            if not shape_children:
                continue
            if target_types and not any(cmds.nodeType(c) in target_types
                                        for c in shape_children):
                continue
            filtered_results.append(node if long_name else node.split('|')[-1])

        if unique:
            filtered_results = list(dict.fromkeys(filtered_results))
        return filtered_results

    # --- standard (non-assemblies) path ---
    kwargs['type'] = type_list

    # Auto long-name: force internally for unambiguous listRelatives
    ls_kwargs = dict(kwargs)
    if long_name:
        ls_kwargs['long'] = True

    results = cmds.ls(*args, **ls_kwargs) or []

    # Auto-detect long names from results
    if not long_name and any('|' in n for n in results):
        long_name = True

    filtered_results = []
    for node in results:
        base_node = node.split('.')[0]
        node_type = cmds.nodeType(base_node)

        if node_type == 'transform':
            shape_children = cmds.listRelatives(base_node, shapes=True, f=True) or []
            if not shape_children:
                continue
            if target_types and not any(cmds.nodeType(c) in target_types
                                        for c in shape_children):
                continue
            filtered_results.append(node if long_name else base_node.split('|')[-1])
        else:
            try:
                parents = cmds.listRelatives(base_node, p=True, f=True)
                if parents:
                    parent_node = parents[0]
                    # shapes=True → uniquement les shapes directes, jamais les transforms
                    shape_children = cmds.listRelatives(parent_node, shapes=True, f=True) or []
                    if not shape_children:
                        continue
                    # même check que la branche transform
                    if target_types and not any(cmds.nodeType(c) in target_types
                                                for c in shape_children):
                        continue
                    result = parent_node if long_name else parent_node.split('|')[-1]
                    filtered_results.append(result)
            except Exception:
                continue

    if unique:
        filtered_results = list(dict.fromkeys(filtered_results))
    return filtered_results