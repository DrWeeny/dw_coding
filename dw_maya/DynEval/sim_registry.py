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
    sim_node_types  Maya node types for sim objects (nCloth, hairSystem, …)
    discover        () -> [solver_node, …]  finds solvers currently in the scene
    make_item       (node) -> QStandardItem | None  creates the right tree item
    get_children    (solver_node) -> [child_node, …]  finds nodes owned by a solver
    cache_ops       class that implements create / attach / delete (filled in later)
    """
    name:           str
    solver_types:   list[str]
    sim_node_types: list[str]
    discover:       Callable[[], list[str]]
    make_item:      Callable[[str], QtGui.QStandardItem | None]
    get_children:   Callable[[str], list[str]]
    cache_ops:      type | None = None


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

    for system in dict.fromkeys(_by_node_type.values()):   # deduplicate systems
        solvers = [n for n in system.discover() if n not in seen]
        seen.update(solvers)
        if solvers:
            result[system.name] = solvers

    return result


# ============================================================================
# TREE CONSTRUCTION
# ============================================================================

def build_solver_item(solver_node: str) -> list[QtGui.QStandardItem] | None:
    """
    Build a fully populated two-column tree row for solver_node.

    Column 0  solver tree item, with child rows already appended.
    Column 1  state item  (enabled / disabled data at UserRole + 3).

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

    for child_node in children:
        child_item = system.make_item(child_node)
        if child_item:
            solver_item.appendRow(_make_row(child_item))

    return _make_row(solver_item)


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