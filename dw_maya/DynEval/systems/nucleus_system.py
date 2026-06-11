"""
systems/nucleus_system.py — Nucleus simulation backend

Registers the nucleus SimSystem on import.
Imported automatically by systems/__init__.py.
"""

from __future__ import annotations

import maya.cmds as cmds
try:
    from PySide6 import QtGui
except ImportError:
    # Fallback for older Maya versions shipping PySide2
    from PySide2 import QtGui

from dw_logger import get_logger

from ..sim_registry import SimSystem, register
from ..dendrology.nucleus_leaf import (
    NucleusStandardItem,
    ClothTreeItem,
    HairTreeItem,
    NRigidTreeItem,
)
from ..sim_cmds import info_management
from ..sim_cmds.nucleus_cache_ops import NucleusCacheOps

logger = get_logger()


# ============================================================================
# ITEM FACTORY
# ============================================================================

_ITEM_CLASSES: dict[str, type[QtGui.QStandardItem]] = {
    'nCloth':     ClothTreeItem,
    'hairSystem': HairTreeItem,
    'nRigid':     NRigidTreeItem,
}


def _make_nucleus_item(node: str) -> QtGui.QStandardItem | None:
    """
    Create the appropriate tree item for any nucleus-system node.

    node_type   → item class
    ──────────────────────────────
    nucleus     → NucleusStandardItem
    nCloth      → ClothTreeItem
    hairSystem  → HairTreeItem
    nRigid      → NRigidTreeItem
    other       → None  (logged at debug level)
    """
    try:
        node_type = cmds.nodeType(node)
    except Exception as e:
        logger.warning(f"_make_nucleus_item: nodeType query failed for {node!r}: {e}")
        return None

    if node_type == 'nucleus':
        try:
            return NucleusStandardItem(node)
        except Exception as e:
            logger.warning(f"NucleusStandardItem({node!r}) failed: {e}")
            return None

    item_class = _ITEM_CLASSES.get(node_type)
    if item_class is None:
        logger.debug(f"_make_nucleus_item: unhandled node type {node_type!r} for {node!r}")
        return None

    try:
        return item_class(node)
    except Exception as e:
        logger.warning(f"{item_class.__name__}({node!r}) failed: {e}")
        return None


# ============================================================================
# CHILDREN DISCOVERY
# ============================================================================

def _get_nucleus_children(solver_node: str) -> list[str]:
    """
    Return all sim nodes connected to solver_node, in outliner order.

    Maya connection topology
    ────────────────────────
    nCloth / hairSystem  →  nucleus.inputActive[i]
    nRigid               →  nucleus.inputPassive[i]

    We query source connections on those compound attrs to retrieve the
    shape nodes that feed this solver.
    """
    seen:     set[str] = set()
    children: list[str] = []

    for attr in ('inputActive', 'inputPassive'):
        nodes = cmds.listConnections(
            f'{solver_node}.{attr}',
            source=True,
            destination=False,
        ) or []
        for n in nodes:
            if n not in seen:
                seen.add(n)
                children.append(n)

    if not children:
        return []

    try:
        return info_management.sort_list_by_outliner(children)
    except Exception as e:
        logger.warning(f"sort_list_by_outliner failed, keeping unsorted: {e}")
        return children


# ============================================================================
# REGISTRATION
# ============================================================================

register(SimSystem(
    name           = 'nucleus',
    solver_types   = ['nucleus'],
    sim_node_types = ['nCloth', 'hairSystem', 'nRigid'],
    discover       = lambda: cmds.ls(type='nucleus') or [],
    make_item      = _make_nucleus_item,
    get_children   = _get_nucleus_children,
    cache_ops      = NucleusCacheOps,
))