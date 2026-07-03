"""
sim_registry.py — simulation system plugin registry

Each backend (nucleus, ziva, qualoth…) registers a SimSystem once at import
time via register(). The rest of the codebase (SimTreePanel, CacheVersionPanel…)
uses the registry functions without knowing any specific sim system.

Registration is triggered by importing the systems package:
    from .systems import *   # or explicit: from .systems import nucleus_system
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Slot
    from shiboken6 import wrapInstance
except ImportError:
    # Fallback for older Maya versions shipping PySide2
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Slot
    from shiboken2 import wrapInstance
    
import maya.cmds as cmds

from dw_logger import get_logger

logger = get_logger()


# ============================================================================
# PLUGIN DESCRIPTOR
# ============================================================================

@dataclass
class SimSystem:
    """
    Descriptor for one simulation backend.

    Fields
    ------
    name            human-readable key ('nucleus', 'ziva', …)
    solver_types    Maya node types that act as top-level solvers
    sim_node_types  Maya node types for sim objects (nCloth, hairSystem, …);
                    also drives the leaf-type filter checkboxes in the tree panel
    discover        () -> [solver_node, …]  finds solvers currently in the scene
    make_item       (node) -> QStandardItem | None  creates the right tree item
    get_children    (solver_node) -> [child_node, …]  finds nodes owned by a solver
    cache_ops       class that implements create / attach / delete (filled in later)
    get_links       optional (solver_node) -> {child: parent_child} — children
                    mapped here are nested under the other child instead of
                    the solver (e.g. nRigid under the nCloth it constrains)
    """
    name:           str
    solver_types:   list[str]
    sim_node_types: list[str]
    discover:       Callable[[], list[str]]
    make_item:      Callable[[str], QtGui.QStandardItem | None]
    get_children:   Callable[[str], list[str]]
    cache_ops:      type | None = None
    get_links:      Callable[[str], dict[str, str]] | None = None


# ============================================================================
# REGISTRY STORAGE
# ============================================================================

_by_node_type: dict[str, SimSystem] = {}   # for O(1) lookup during tree build
_by_name:      dict[str, SimSystem] = {}   # for system-level queries


def register(system: SimSystem) -> None:
    """
    Register a SimSystem. Called once at module import time from systems/.
    Safe to call multiple times with the same system (idempotent).
    """
    for node_type in system.solver_types + system.sim_node_types:
        _by_node_type[node_type] = system
    _by_name[system.name] = system
    logger.debug(f"SimSystem registered: {system.name!r}")


def get_system(node_type: str) -> SimSystem | None:
    """Lookup by Maya node type string (e.g. 'nCloth', 'nucleus')."""
    return _by_node_type.get(node_type)


def get_system_by_name(name: str) -> SimSystem | None:
    """Lookup by system name (e.g. 'nucleus')."""
    return _by_name.get(name)


def all_sim_node_types() -> list[str]:
    """Every leaf node type across registered systems, registration order.

    Drives the tree panel's per-type filter checkboxes.
    """
    types: list[str] = []
    for system in _by_name.values():
        for node_type in system.sim_node_types:
            if node_type not in types:
                types.append(node_type)
    return types


def discover_all() -> dict[str, list[str]]:
    """
    Ask every registered system to find its solvers in the current scene.

    Returns
    -------
    {system_name: [solver_node, …]}  — only entries with at least one solver.
    Each solver node appears at most once (first-registered system wins).
    """
    result: dict[str, list[str]] = {}
    seen:   set[str] = set()

    # Deduplicate systems while preserving registration order. Using dict.fromkeys
    # previously failed because SimSystem instances are dataclasses and not
    # hashable by default (TypeError: unhashable type: 'SimSystem'). Instead
    # deduplicate by identity (id) which is stable for the lifetime of the
    # interpreter and avoids requiring __hash__ on SimSystem.
    unique_systems = []
    seen_ids: set[int] = set()
    for system in _by_node_type.values():
        sid = id(system)
        if sid not in seen_ids:
            seen_ids.add(sid)
            unique_systems.append(system)

    for system in unique_systems:
        solvers = [n for n in system.discover() if n not in seen]
        seen.update(solvers)
        if solvers:
            result[system.name] = solvers

    return result


# ============================================================================
# TREE CONSTRUCTION
# ============================================================================

def build_solver_item(solver_node: str,
                      visible_types: set[str] | None = None,
                      ) -> list[QtGui.QStandardItem] | None:
    """
    Build a fully populated two-column tree row for solver_node.

    Column 0  solver tree item, with child rows already appended.
    Column 1  state item  (enabled / disabled data at UserRole + 3).

    visible_types, when given, filters which leaf items appear (matched
    against each built item's node_type — the tree panel's checkboxes).
    Children mapped by system.get_links are nested under their linked
    sibling (e.g. nRigid under its constrained nCloth); a hidden or
    missing link parent falls back to the solver.

    Returns None if the node type has no registered system, or if make_item
    returns None (e.g. node no longer exists).

    Usage in SimTreePanel
    ---------------------
        row = build_solver_item(solver_node)
        if row:
            self.tree.model().invisibleRootItem().appendRow(row)
    """
    try:
        node_type = cmds.nodeType(solver_node)
    except Exception:
        logger.warning(f"build_solver_item: could not query type for {solver_node!r}")
        return None

    system = _by_node_type.get(node_type)
    if not system:
        logger.debug(f"build_solver_item: no system registered for {node_type!r}")
        return None

    solver_item = system.make_item(solver_node)
    if not solver_item:
        logger.warning(f"build_solver_item: make_item returned None for {solver_node!r}")
        return None

    try:
        children = system.get_children(solver_node)
    except Exception as e:
        logger.warning(f"build_solver_item: get_children failed for {solver_node!r}: {e}")
        children = []

    links: dict[str, str] = {}
    if system.get_links is not None:
        try:
            links = system.get_links(solver_node) or {}
        except Exception as e:
            logger.warning(f"build_solver_item: get_links failed for {solver_node!r}: {e}")

    # Build items first so filtering and nesting can use the resolved
    # item.node / node_type (get_children may hand out transforms).
    child_items = []
    for child_node in children:
        child_item = system.make_item(child_node)
        if not child_item:
            continue
        if visible_types is not None:
            if getattr(child_item, "node_type", None) not in visible_types:
                continue
        child_items.append(child_item)

    # Nodes may come back short or full-path depending on the query —
    # compare by short name.
    by_short = {
        _short_name(getattr(item, "node", "")): item for item in child_items
    }
    for item in child_items:
        parent_node = links.get(_short_name(getattr(item, "node", "")))
        parent_item = by_short.get(_short_name(parent_node)) if parent_node else None
        if parent_item is not None and parent_item is not item:
            parent_item.appendRow(_make_row(item))
        else:
            solver_item.appendRow(_make_row(item))

    return _make_row(solver_item)


def _short_name(node: str) -> str:
    return node.split("|")[-1] if node else ""


def _make_row(item: QtGui.QStandardItem) -> list[QtGui.QStandardItem]:
    """
    Wrap an item in a two-column row [item, state_item].
    state_item carries the enabled/disabled boolean at UserRole + 3.
    """
    state_item = QtGui.QStandardItem()
    state_item.setEditable(False)
    state = getattr(item, "state", None)
    if state is not None:
        state_item.setData(state, QtCore.Qt.UserRole + 3)
    return [item, state_item]