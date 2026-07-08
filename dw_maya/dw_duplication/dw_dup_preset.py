"""Preset-based duplication: settings, inputs and constraints survive.

Summary:
    Maya's duplicate (ctrl+D) drops the incoming graph. Both entry points
    rebuild it from the preset components (``dw_presets_io.preset_components``);
    they differ in how the copy itself is made:

    - ``duplicate_nodes`` (hybrid, recommended): copies each node with
      ``cmds.duplicate`` - full shape fidelity (nurbsCurve/nurbsSurface,
      creases, color sets, UV sets, per-face shading all survive) - then
      replays the captured incoming connections and rebuilds the driving
      constraints onto the copy. Dead constraint nodes brought along by the
      native duplicate are removed first.
    - ``mn_duplicate_nodes`` (pure preset): recreates every node from its
      preset entry alone (``node_from_preset``), the same machinery as
      loading a preset file. Works without touching cmds.duplicate, but
      geometry is limited to what GeometryComponent rebuilds: meshes only,
      single UV set, no creases - and nothing for curves/surfaces.

Functions:
    duplicate_nodes: hybrid cmds.duplicate + preset replay of the graph.
    mn_duplicate_nodes: rebuild copies purely from the captured preset.

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

#: Component keys the base wrappers own. A class carrying anything else
#: (constraint_network, nconstraint_network, ...) rebuilds state that
#: cmds.duplicate cannot copy, so the hybrid routes it through
#: node_from_preset instead of the native duplicate.
_STD_COMPONENT_KEYS = {"hierarchy", "attributes", "connections",
                       "keyframes", "geometry"}


def _unique_scene_name(name: str) -> str:
    """Return ``name`` or its first free numbered variant (namespace kept)."""
    if not cmds.objExists(name):
        return name
    base = re.sub(r"\d+$", "", name)
    i = 1
    while cmds.objExists(f"{base}{i}"):
        i += 1
    return f"{base}{i}"


def _wrap(item):
    """Return ``item`` as a wrapped node (lsNode), or None when missing."""
    import dw_maya.dw_lsNode as dw_lsNode

    if not isinstance(item, str):
        return item
    found = dw_lsNode.lsNode(item)
    if not found:
        logger.warning(f"duplicate_nodes: '{item}' not found, skipping")
        return None
    return found[0]


def _wrap_nodes(nodes: Optional[List[Any]]) -> List[Any]:
    """Wrap the given nodes (or the selection) through lsNode."""
    if nodes is None:
        nodes = cmds.ls(selection=True) or []
    wrapped = [w for w in (_wrap(n) for n in nodes) if w]
    if not wrapped:
        logger.warning("duplicate_nodes: nothing to duplicate")
    return wrapped


def _specialize(node):
    # Same class map as the rebuild dispatch, so e.g. a plain mesh is
    # captured through Mesh (geometry included), not base MayaNode.
    cls = pcomp.resolve_preset_class(node.nodeType)
    if cls and type(node) is not cls:
        return cls(node.tr or node.node)
    return node


def _needs_preset_build(node) -> bool:
    """True when the wrapper owns a bespoke component (constraint network,
    nucleus constraint network, ...) whose state a native duplicate cannot
    copy - the node must be recreated through node_from_preset instead."""
    keys = {comp.key for comp in type(node).preset_components}
    return bool(keys - _STD_COMPONENT_KEYS)


def _capture_entries(wrapped: List[Any],
                     with_constraints: bool,
                     skip: Optional[list],
                     light_geometry: bool = False) -> List[tuple]:
    """Capture each node, then the constraints driving it.

    Returns ``(identity, body, original scene name, needs_preset)`` tuples.
    ``light_geometry`` drops the geometry slice from natively-duplicated
    entries (the hybrid never applies it, and points are heavy to capture).
    """
    entries: List[tuple] = []
    for node in wrapped:
        node = _specialize(node)
        original = node.tr or node.node
        needs_preset = _needs_preset_build(node)
        node_skip = list(skip or [])
        if light_geometry and not needs_preset:
            node_skip.append("geometry")
        for identity, body in node.createPreset(skip=node_skip).items():
            entries.append((identity, body, original, needs_preset))
        if with_constraints:
            cons = set(cmds.listConnections(original, source=True,
                                            destination=False,
                                            type="constraint") or [])
            for con in sorted(cons):
                con_node = _wrap(con)
                if not con_node:
                    continue
                for identity, body in con_node.createPreset(skip=skip).items():
                    entries.append((identity, body, con_node.node, True))
    return entries


def _local_shorts(original: str, identity: str) -> set:
    """Short names an entry owns (transform + shapes).

    A stored destination plug whose node is in this set is an incoming
    connection of the entry itself - the identity alone is not enough,
    since shape-level inputs (``bodyShape.inMesh``) are stored under the
    shape's short name, not the transform-based identity.
    """
    names = {identity, original.split("|")[-1].split(":")[-1]}
    if cmds.objExists(original):
        try:
            shapes = cmds.listRelatives(original, shapes=True) or []
        except Exception:
            shapes = []
        names.update(s.split("|")[-1].split(":")[-1] for s in shapes)
    return names


def _seed_shape_map(original: str,
                    dup_path: str,
                    ctx: "pcomp.PresetContext") -> None:
    """Map the original's shape short names onto the copy's shapes.

    cmds.duplicate keeps the shape short name, so a stored plug like
    ``bodyShape.inMesh`` resolved by bare name would be ambiguous between
    the original and the copy; an explicit rename-map entry makes
    ``resolve_scene_node`` deterministic.
    """
    try:
        orig_shapes = cmds.listRelatives(original, shapes=True) or []
        dup_shapes = cmds.listRelatives(dup_path, shapes=True,
                                        fullPath=True) or []
    except Exception:
        return
    for o_sh, d_sh in zip(orig_shapes, dup_shapes):
        ctx.name_map[o_sh.split("|")[-1].split(":")[-1]] = d_sh


def _replay_connections(created: List[Any],
                        entries: List[tuple],
                        ctx: "pcomp.PresetContext",
                        with_outputs: bool,
                        skip: Optional[list]) -> None:
    """Pass 2 - replay captured connections once every copy exists."""
    if "connections" in (skip or []):
        return
    for node, (identity, body, original, _needs) in zip(created, entries):
        if node is None:
            continue
        conn = body.get("connections")
        if not conn:
            continue
        if not with_outputs:
            local = _local_shorts(original, identity)
            incoming = [p for p in conn.get("pairs", [])
                        if p[1].partition(".")[0]
                        .split("|")[-1].split(":")[-1] in local]
            if not incoming:
                continue
            conn = dict(conn, pairs=incoming)
        node.applyPreset({identity: dict(body, connections=conn)},
                         ctx, only=["connections"])


def duplicate_nodes(nodes: Optional[List[Any]] = None,
                    with_constraints: bool = True,
                    with_outputs: bool = False,
                    skip: Optional[list] = None) -> List[Any]:
    """Hybrid duplicate: native copy for the content, preset for the graph.

    Each node is copied with ``cmds.duplicate`` (every shape type survives
    with full fidelity - curves, creases, UV sets, shading), then the graph
    is replayed from the captured preset: incoming connections shared with
    the original, driving constraints rebuilt onto the copy through the
    native command. Dead constraint nodes the duplicate drags along as
    children are deleted before the rebuild.

    Args:
        nodes: MayaNode instances and/or node names. Defaults to selection.
        with_constraints: Also duplicate the constraints driving each node.
        with_outputs: Replay outgoing connections too. Off by default: a
            destination plug takes one incoming connection, so forcing the
            duplicate's outputs would steal them from the original.
        skip: Extra component keys to leave out of the replay.

    Returns:
        The wrapped duplicates (sources first, then their constraints).
    """
    wrapped = _wrap_nodes(nodes)
    if not wrapped:
        return []

    entries = _capture_entries(wrapped, with_constraints, skip,
                               light_geometry=True)
    ctx = pcomp.PresetContext(create=True)
    created: List[Any] = [None] * len(entries)

    # Pass 1a - native duplicate, seeding the rename map (transform and
    # shapes) so the connection replay and constraint rebuild target the
    # copies instead of resolving back onto the originals.
    for i, (identity, body, original, needs_preset) in enumerate(entries):
        if needs_preset:
            continue
        mapped = ctx.name_map.get(identity)
        if mapped and cmds.objExists(mapped):
            created[i] = _wrap(mapped)  # same node captured twice
            continue
        if not cmds.objExists(original):
            logger.warning(f"duplicate_nodes: '{original}' vanished before "
                           f"duplication, skipping")
            continue
        dup = cmds.duplicate(original)[0]
        dup_path = cmds.ls(dup, long=True)[0]
        # The duplicate drags constrained children along as dead constraint
        # copies (no targets, but still wired to the copy's channels) - they
        # would fight the proper rebuild in pass 1b.
        try:
            junk = cmds.ls(dup_path, dag=True, type="constraint",
                           long=True) or []
        except Exception:
            junk = []
        if junk:
            cmds.delete(junk)
        ctx.name_map[identity] = dup_path
        _seed_shape_map(original, dup_path, ctx)
        created[i] = _wrap(dup_path)

    # Pass 1b - preset rebuild for nodes a native duplicate cannot copy
    # (constraints and other network-component owners), now that every
    # driven copy is in the rename map.
    pass1_skip = ["connections"] + list(skip or [])
    for i, (identity, body, original, needs_preset) in enumerate(entries):
        if not needs_preset:
            continue
        if identity not in ctx.name_map:
            ctx.name_map[identity] = _unique_scene_name(
                original.split("|")[-1])
        created[i] = pcomp.node_from_preset(identity, body, ctx,
                                            skip=pass1_skip)

    # Pass 2 - replay connections now that every copy exists.
    _replay_connections(created, entries, ctx, with_outputs, skip)
    return [node for node in created if node is not None]


def mn_duplicate_nodes(nodes: Optional[List[Any]] = None,
                       with_constraints: bool = True,
                       with_outputs: bool = False,
                       skip: Optional[list] = None) -> List[Any]:
    """Pure preset duplicate: every copy is rebuilt from its captured entry.

    Same machinery as loading a preset file (``node_from_preset``), so it
    exercises exactly what a saved preset can restore - useful as a
    round-trip check and for DG nodes. For shapes it is limited to what
    GeometryComponent rebuilds (meshes; single UV set, no creases, default
    shading) - prefer :func:`duplicate_nodes` for scene duplication.

    Two-pass apply: every copy is created first (connections skipped), then
    connections replay once all remapped names exist - otherwise a pair
    toward a not-yet-created copy would fall back onto the original node.

    Args:
        nodes: MayaNode instances and/or node names. Defaults to selection.
        with_constraints: Also duplicate the constraints driving each node.
        with_outputs: Replay outgoing connections too (see
            :func:`duplicate_nodes`).
        skip: Extra component keys to leave out of the copy.

    Returns:
        The wrapped duplicates (sources first, then their constraints).
    """
    wrapped = _wrap_nodes(nodes)
    if not wrapped:
        return []

    entries = _capture_entries(wrapped, with_constraints, skip)

    # Seed every identity with a fresh name (same namespace) so the rebuild
    # creates copies instead of resolving back onto the originals.
    ctx = pcomp.PresetContext(create=True)
    for identity, _, original, _ in entries:
        if identity not in ctx.name_map:
            ctx.name_map[identity] = _unique_scene_name(
                original.split("|")[-1])

    # Pass 1 - create everything, connections deferred.
    pass1_skip = ["connections"] + list(skip or [])
    created = [pcomp.node_from_preset(identity, body, ctx, skip=pass1_skip)
               for identity, body, _, _ in entries]

    # Pass 2 - replay connections now that every copy exists.
    _replay_connections(created, entries, ctx, with_outputs, skip)
    return created