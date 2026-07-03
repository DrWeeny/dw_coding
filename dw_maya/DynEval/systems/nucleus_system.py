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

    # If a transform was passed, try to find a child shape with a known sim
    # node type (nCloth, hairSystem, nRigid). Maya often reports the transform
    # when listConnections/listRelatives are used; handle that case transparently.
    if node_type == 'transform':
        try:
            shapes = cmds.listRelatives(node, s=True, f=True) or []
            for shape in shapes:
                try:
                    st = cmds.nodeType(shape)
                except Exception:
                    continue
                if st == 'nucleus':
                    return NucleusStandardItem(shape)
                cls = _ITEM_CLASSES.get(st)
                if cls:
                    return cls(shape)
        except Exception as e:
            logger.warning(f"_make_nucleus_item: failed to resolve shapes for transform {node!r}: {e}")

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
# RIGID -> CLOTH LINKS
# ============================================================================

def _get_rigid_links(solver_node: str) -> dict[str, str]:
    """
    Map each nRigid to the nCloth it is linked to, for tree nesting.

    Maya has no direct nCloth<->nRigid connection — both plug independently
    into the nucleus. Two associations, strongest first:

    1. A shared dynamicConstraint (e.g. pointToSurface between cloth
       vertices and the rigid surface):
       nBase.nucleusId -> nComponent.objectId -> dynamicConstraint.componentIds[i]
    2. Fallback for plain colliders (no constraint): when the solver drives
       exactly one nCloth, every unmapped rigid nests under it — the common
       character setup (one garment sim + body colliders). With several
       cloths there is no way to pick, so unmapped rigids stay under the
       solver.

    build_solver_item ignores links to nodes that are not children of this
    solver, so no solver filtering is needed for the constraint walk.
    """
    links: dict[str, str] = {}

    for constraint in cmds.ls(type='dynamicConstraint') or []:
        components = cmds.listConnections(
            f'{constraint}.componentIds',
            source=True,
            destination=False,
        ) or []

        cloths, rigids = [], []
        for component in set(components):
            nbases = cmds.listConnections(
                f'{component}.objectId',
                source=True,
                destination=False,
                shapes=True,
            ) or []
            for nbase in nbases:
                try:
                    nbase_type = cmds.nodeType(nbase)
                except Exception:
                    continue
                if nbase_type == 'nCloth':
                    cloths.append(nbase)
                elif nbase_type == 'nRigid':
                    rigids.append(nbase)

        for rigid in rigids:
            key = rigid.split('|')[-1]
            if cloths and key not in links:
                links[key] = cloths[0].split('|')[-1]
                logger.debug(
                    f"rigid link (constraint {constraint}): "
                    f"{key} -> {links[key]}"
                )

    # Fallback: single-cloth solver adopts its unmapped rigids.
    active = cmds.listConnections(
        f'{solver_node}.inputActive',
        source=True,
        destination=False,
        shapes=True,
    ) or []
    solver_cloths = sorted({n.split('|')[-1] for n in cmds.ls(active, type='nCloth')})
    if len(solver_cloths) == 1:
        passive = cmds.listConnections(
            f'{solver_node}.inputPassive',
            source=True,
            destination=False,
            shapes=True,
        ) or []
        for rigid in sorted({n.split('|')[-1] for n in cmds.ls(passive, type='nRigid')}):
            if rigid not in links:
                links[rigid] = solver_cloths[0]
                logger.debug(
                    f"rigid link (single-cloth fallback): "
                    f"{rigid} -> {solver_cloths[0]}"
                )

    return links


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
    get_links      = _get_rigid_links,
))