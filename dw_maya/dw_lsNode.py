"""Pythonic wrapper around cmds.ls — returns typed node objects.

Instead of raw strings, lsNode() returns the richest available Python
class for each node: Cluster, BlendShape, nConstraint… falling back to
MayaNode for anything not explicitly registered.

The type registry is built once at import time from the same
_DEFORMER_CLASSES dict used by make_deformer(), so adding a new deformer
class automatically makes it available here too.

Usage::

    from dw_maya.dw_lsNode import lsNode

    lsNode('cluster1')              # → Cluster
    lsNode(type='blendShape')       # → [BlendShape, BlendShape, …]
    lsNode(type='nComponent')       # → [nComponent, …]
    lsNode('pCube1')                # → MayaNode  (fallback)
    lsNode('*', type='transform')   # → [MayaNode, …]  — same flags as cmds.ls

Author: DrWeeny
"""

from __future__ import annotations

from typing import List, Type

from maya import cmds

from dw_maya.dw_maya_nodes import MayaNode
from dw_maya.dw_deformers.dw_deformer_class import _DEFORMER_CLASSES
from dw_maya.dw_nucleus_utils.dw_nconstraint_class import nConstraint, nComponent
from dw_logger import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Registry — built once at import time
# ---------------------------------------------------------------------------
# _DEFORMER_CLASSES already contains:
#   cluster, softMod, blendShape, wire, skinCluster
# We extend it with nucleus and constraint nodes.

_NODE_CLASSES: dict[str, Type] = {
    **_DEFORMER_CLASSES,
    'nComponent':        nComponent,
    'dynamicConstraint': nConstraint,
}

_DEFAULT_CLASS: Type = MayaNode


def register_node_class(node_type: str, cls: Type) -> None:
    """Register a custom class for a Maya node type.

    Call this from your own module to teach lsNode() about new node types
    without modifying this file.

    Args:
        node_type: Maya node type string (as returned by cmds.nodeType).
        cls:       Class to instantiate for that type.

    Example::

        from dw_maya.dw_lsNode import register_node_class
        from my_module import MyCustomNode

        register_node_class('myCustomNodeType', MyCustomNode)
        lsNode(type='myCustomNodeType')  # → [MyCustomNode, …]
    """
    _NODE_CLASSES[node_type] = cls
    logger.debug(f"Registered {cls.__name__} for node type '{node_type}'")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lsNode(*args, **kwargs) -> List:
    """List Maya nodes as typed Python objects.

    Accepts exactly the same arguments as cmds.ls — all flags are forwarded
    unchanged.  Each node is wrapped in the richest available class:

    - Known deformers   → Cluster / BlendShape / SoftMod / Wire / SkinCluster
    - Nucleus nodes     → nConstraint / nComponent
    - Everything else   → MayaNode

    Args:
        *args:    Positional arguments forwarded to cmds.ls.
        **kwargs: Keyword arguments forwarded to cmds.ls.

    Returns:
        List of typed node objects, empty list if nothing matched.

    Examples::

        lsNode('cluster1')
        # [<Cluster node='cluster1' mesh='pSphere1' map=None vtx=382>]

        lsNode(type='blendShape')
        # [<BlendShape ...>, <BlendShape ...>]

        lsNode('pCube*', type='transform')
        # [<MayaNode ...>, …]

        lsNode('nComp*')
        # [<nComponent ...>, …]
    """
    nodes = cmds.ls(*args, **kwargs)
    if not nodes:
        return []

    result = []
    for node in nodes:
        node_type = cmds.nodeType(node)
        cls = _NODE_CLASSES.get(node_type, _DEFAULT_CLASS)
        try:
            result.append(cls(node))
        except Exception as e:
            logger.warning(
                f"Could not instantiate {cls.__name__} for '{node}' "
                f"(type '{node_type}'): {e} — falling back to MayaNode"
            )
            try:
                result.append(_DEFAULT_CLASS(node))
            except Exception as fallback_err:
                logger.error(f"Fallback also failed for '{node}': {fallback_err}")

    return result
