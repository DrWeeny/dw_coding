"""Preset-based duplication: settings, inputs and constraints survive.

Summary:
    Maya's duplicate (ctrl+D) drops the incoming graph. ``duplicate_nodes``
    instead captures each node through its preset components
    (``dw_presets_io.preset_components``) and rebuilds it under a unique name
    in the same namespace / under the same parent: attributes, incoming
    connections (the duplicate shares the original's inputs) and the
    constraint nodes driving it - rebuilt through the native command onto the
    duplicate, same drivers, same weights and rest offsets.

Functions:
    duplicate_nodes: duplicate selection / given nodes with their live graph.

Example:
    >>> from dw_maya.dw_duplication import duplicate_nodes
    >>> dups = duplicate_nodes()  # selected collider -> copy + its constraint

Author:
    DrWeeny
"""

import re
from typing import Any, List, Optional

from maya import cmds

import dw_maya.dw_presets_io.preset_components as pcomp
from dw_logger import get_logger

logger = get_logger()


def _unique_scene_name(name: str) -> str:
    """Return ``name`` or its first free numbered variant (namespace kept)."""
    if not cmds.objExists(name):
        return name
    base = re.sub(r"\d+$", "", name)
    i = 1
    while cmds.objExists(f"{base}{i}"):
        i += 1
    return f"{base}{i}"


def duplicate_nodes(nodes: Optional[List[Any]] = None,
                    with_constraints: bool = True,
                    with_outputs: bool = False,
                    skip: Optional[list] = None) -> List[Any]:
    """Preset-based duplicate: settings, inputs and constraints survive.

    Two-pass apply: every copy is created first (connections skipped), then
    connections replay once all remapped names exist - otherwise a pair
    toward a not-yet-created copy would fall back onto the original node.

    Args:
        nodes: MayaNode instances and/or node names. Defaults to selection.
        with_constraints: Also duplicate the constraints driving each node.
        with_outputs: Replay outgoing connections too. Off by default: a
            destination plug takes one incoming connection, so forcing the
            duplicate's outputs would steal them from the original.
        skip: Extra component keys to leave out of the copy.

    Returns:
        The wrapped duplicates (sources first, then their constraints).
    """
    import dw_maya.dw_lsNode as dw_lsNode

    if nodes is None:
        nodes = cmds.ls(selection=True) or []

    def _wrap(item):
        if not isinstance(item, str):
            return item
        found = dw_lsNode.lsNode(item)
        if not found:
            logger.warning(f"duplicate_nodes: '{item}' not found, skipping")
            return None
        return found[0]

    def _specialize(node):
        # Same class map as the rebuild dispatch, so e.g. a plain mesh is
        # captured through Mesh (geometry included), not base MayaNode.
        cls = pcomp.resolve_preset_class(node.nodeType)
        if cls and type(node) is not cls:
            return cls(node.tr or node.node)
        return node

    wrapped = [w for w in (_wrap(n) for n in nodes) if w]
    if not wrapped:
        logger.warning("duplicate_nodes: nothing to duplicate")
        return []

    # Capture sources, then the constraints driving them.
    entries: List[tuple] = []  # (identity, body, original scene name)
    for node in wrapped:
        node = _specialize(node)
        original = node.tr or node.node
        for identity, body in node.createPreset(skip=skip).items():
            entries.append((identity, body, original))
        if with_constraints:
            cons = set(cmds.listConnections(original, source=True,
                                            destination=False,
                                            type="constraint") or [])
            for con in sorted(cons):
                con_node = _wrap(con)
                if not con_node:
                    continue
                for identity, body in con_node.createPreset(skip=skip).items():
                    entries.append((identity, body, con_node.node))

    # Seed every identity with a fresh name (same namespace) so the rebuild
    # creates copies instead of resolving back onto the originals.
    ctx = pcomp.PresetContext(create=True)
    for identity, _, original in entries:
        if identity not in ctx.name_map:
            ctx.name_map[identity] = _unique_scene_name(original.split("|")[-1])

    # Pass 1 - create everything, connections deferred.
    pass1_skip = ["connections"] + list(skip or [])
    created = [pcomp.node_from_preset(identity, body, ctx, skip=pass1_skip)
               for identity, body, _ in entries]

    # Pass 2 - replay connections now that every copy exists.
    if "connections" not in (skip or []):
        for node, (identity, body, _) in zip(created, entries):
            conn = body.get("connections")
            if not conn:
                continue
            if not with_outputs:
                incoming = [p for p in conn.get("pairs", [])
                            if p[1].partition(".")[0]
                            .split("|")[-1].split(":")[-1] == identity]
                if not incoming:
                    continue
                conn = dict(conn, pairs=incoming)
            node.applyPreset({identity: dict(body, connections=conn)},
                             ctx, only=["connections"])
    return created