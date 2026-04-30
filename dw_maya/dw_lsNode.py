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

from dw_maya.dw_node_registry import resolve
# import important pour declencher le registry
import dw_maya.dw_deformers.dw_deformer_class        # noqa: F401
import dw_maya.dw_nucleus_utils.dw_nconstraint_class  # noqa: F401

from dw_logger import get_logger

logger = get_logger()

def lsNode(*args, **kwargs) -> List:
    nodes = cmds.ls(*args, **kwargs)
    if not nodes:
        return []

    result = []
    for node in nodes:
        cls = resolve(node)  # ← tout est délégué ici
        try:
            result.append(cls(node))
        except Exception as e:
            logger.warning(f"Could not instantiate {cls.__name__} for '{node}': {e}")
            try:
                result.append(MayaNode(node))
            except Exception as fallback_err:
                logger.error(f"Fallback also failed for '{node}': {fallback_err}")

    return result