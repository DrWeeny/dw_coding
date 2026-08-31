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

    Both take the same symmetry options: ``mirror`` reflects the copies
    across a world axis (optionally around a pivot node, baking the flip
    into mesh points so nothing ends up inside-out), and the copies are
    renamed by swapping their left/right token - ``L_arm`` -> ``R_arm``,
    ``armLeft`` -> ``armRight`` - which is how one side of a setup becomes
    the other.

Functions:
    duplicate_nodes: hybrid cmds.duplicate + preset replay of the graph.
    mn_duplicate_nodes: rebuild copies purely from the captured preset.
    swap_side_name: swap the left/right token in a node name.

Example:
    >>> from dw_maya.dw_duplication import duplicate_nodes
    >>> dups = duplicate_nodes()  # selected collider -> copy + its constraint
    >>> # the other side of a symmetrical setup, mirrored across X:
    >>> dups = duplicate_nodes(["L_shoulder_collider"], mirror="x")

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


#: World axis a mirror reflects across, as an index into a 4x4 row-major list.
_MIRROR_AXES = {"x": 0, "y": 1, "z": 2}

#: Transform channels a mirror has to write. Driven ones make it impossible.
_MIRROR_CHANNELS = ("translate", "rotate", "scale")


#: Side tokens swapped when a copy is renamed for symmetry. Each pair is
#: swapped both ways and matched case-insensitively; extend this tuple to
#: teach the swap a studio's own convention.
SIDE_PAIRS = (("l", "r"),
              ("lf", "rt"),
              ("lft", "rgt"),
              ("left", "right"))

#: One-character tokens are only recognised when a delimiter isolates them
#: (``L_arm``, ``arm_L``, ``arm_L_end``) - never inside a word, or every
#: name holding an 'l' would flip.
_SIDE_MAP = {}
for _a, _b in SIDE_PAIRS:
    _SIDE_MAP[_a] = _b
    _SIDE_MAP[_b] = _a

_LONG_TOKENS = sorted((t for t in _SIDE_MAP if len(t) > 1), key=len,
                      reverse=True)
_ALL_TOKENS = sorted(_SIDE_MAP, key=len, reverse=True)

#: Delimited token: start/end of the name or an underscore on both sides.
_SIDE_DELIMITED = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(_ALL_TOKENS) +
                             r")(?![A-Za-z0-9])", re.IGNORECASE)

#: Camel-case token: 'armLeft', 'meshRight_geo'. Multi-letter only - a bare
#: capital in 'armR' is too easily a version letter or an acronym tail.
_SIDE_CAMEL = re.compile(r"(?<=[a-z0-9])(" + "|".join(_LONG_TOKENS) +
                         r")(?![a-z])", re.IGNORECASE)


def _match_case(source: str = "", target: str = "") -> str:
    """Return ``target`` wearing ``source``'s capitalisation."""
    if source.isupper():
        return target.upper()
    if source.islower():
        return target.lower()
    if source[:1].isupper():
        return target.capitalize()
    return target


def _swap_token(match) -> str:
    token = match.group(1)
    return _match_case(token, _SIDE_MAP[token.lower()])


def swap_side_name(name: str = "") -> str:
    """Swap the left/right token in a node's short name.

    Recognises the :data:`SIDE_PAIRS` tokens delimited by underscores or by
    the ends of the name (``L_arm``, ``arm_R``, ``arm_left_low``), and the
    multi-letter ones in camel case (``armLeft``, ``meshRight_geo``). Case
    is preserved (``L`` -> ``R``, ``Left`` -> ``Right``, ``LEFT`` ->
    ``RIGHT``), every occurrence is swapped, and a name with no side token
    comes back unchanged - the caller uniquifies it instead.

    Args:
        name: Node name; a dag path or namespace is kept as it is, only the
            short name is rewritten.

    Returns:
        The swapped short name.
    """
    short = name.split("|")[-1]
    namespace, sep, base = short.rpartition(":")
    swapped = _SIDE_DELIMITED.sub(_swap_token, base)
    swapped = _SIDE_CAMEL.sub(_swap_token, swapped)
    return f"{namespace}{sep}{swapped}"


def _renamed(name: str,
             search_replace: Optional[tuple] = None,
             swap_sides: bool = False) -> str:
    """Rename a copy: explicit pair first, else the side-token swap.

    ``search_replace`` is a plain ``("L_", "R_")`` substring pair and wins
    when given - it is the escape hatch for a convention
    :func:`swap_side_name` does not know.
    """
    short = name.split("|")[-1]
    if search_replace:
        namespace, sep, base = short.rpartition(":")
        search, replace = search_replace
        if search and search in base:
            base = base.replace(search, replace)
        else:
            logger.debug(f"duplicate_nodes: '{short}' does not contain "
                         f"'{search}', name left to the uniquifier")
        return f"{namespace}{sep}{base}"
    if swap_sides:
        return swap_side_name(short)
    return short


def _copy_name(original: str,
               search_replace: Optional[tuple] = None,
               swap_sides: bool = False) -> str:
    """Free scene name for a copy of ``original`` (renamed when asked)."""
    return _unique_scene_name(_renamed(original, search_replace, swap_sides))


def _mirror_pivot_point(mirror_pivot: Any = None) -> List[float]:
    """World position the mirror plane passes through (origin by default)."""
    if mirror_pivot is None or mirror_pivot == "":
        return [0.0, 0.0, 0.0]
    target = mirror_pivot if isinstance(mirror_pivot, str) else mirror_pivot.tr
    if not target or not cmds.objExists(target):
        logger.warning(f"duplicate_nodes: mirror_pivot '{target}' not found, "
                       f"mirroring around the world origin")
        return [0.0, 0.0, 0.0]
    return cmds.xform(target, query=True, rotatePivot=True, worldSpace=True)


def _mirror_matrix(axis: str = "x", mirror_pivot: Any = None) -> List[float]:
    """Reflection matrix across the plane normal to ``axis`` at the pivot.

    Row-major, Maya's ``xform -matrix`` layout: reflecting a point across
    ``x = px`` is ``x' = 2 * px - x``, i.e. a -1 on the axis diagonal and
    ``2 * px`` in the translation row.
    """
    index = _MIRROR_AXES[axis]
    matrix = [1.0, 0.0, 0.0, 0.0,
              0.0, 1.0, 0.0, 0.0,
              0.0, 0.0, 1.0, 0.0,
              0.0, 0.0, 0.0, 1.0]
    matrix[index * 4 + index] = -1.0
    matrix[12 + index] = 2.0 * _mirror_pivot_point(mirror_pivot)[index]
    return matrix


def _driven_channels(transform: str) -> List[str]:
    """Transform channels fed by the graph - a mirror cannot write those."""
    driven = []
    for channel in _MIRROR_CHANNELS:
        plug = f"{transform}.{channel}"
        if cmds.listConnections(plug, source=True, destination=False,
                                plugs=False):
            driven.append(channel)
    return driven


def _bake_mirror(transform: str) -> bool:
    """Freeze the negative scale into the points and flip the winding.

    A mirrored transform carries a -1 scale, which leaves every mesh
    inside-out for collisions and shading. Freezing bakes the flip into the
    points (transform back to identity) and ``polyNormal`` puts the winding
    back the right way round. Curves, surfaces and joints are left with the
    negative scale - harmless there, and freezing a joint means something
    else entirely.

    Returns:
        True when the bake ran.
    """
    if cmds.objectType(transform, isAType="joint"):
        return False
    meshes = cmds.listRelatives(transform, shapes=True, type="mesh",
                                fullPath=True) or []
    if not meshes:
        return False
    driven = _driven_channels(transform)
    if driven:
        logger.warning(f"mirror: '{transform}' keeps its negative scale, "
                       f"{', '.join(driven)} driven by the graph")
        return False
    cmds.makeIdentity(transform, apply=True,
                      translate=True, rotate=True, scale=True, normal=0)
    for mesh in meshes:
        cmds.polyNormal(mesh, normalMode=0, userNormalMode=0,
                        constructionHistory=False)
    return True


def _mirror_node(node,
                 axis: str = "x",
                 mirror_pivot: Any = None,
                 mirror_geometry: bool = True) -> bool:
    """Reflect one duplicated node across the world mirror plane.

    Constraints are skipped: their transform is an output of the rebuilt
    network, not a placement to mirror.

    Returns:
        True when the node was mirrored.
    """
    import maya.api.OpenMaya as om

    transform = node.tr if node is not None else None
    if not transform or not cmds.objExists(transform):
        return False
    if cmds.objectType(transform, isAType="constraint"):
        return False
    driven = _driven_channels(transform)
    if driven:
        logger.warning(f"mirror: '{transform}' not mirrored, "
                       f"{', '.join(driven)} driven by the graph")
        return False
    world = om.MMatrix(cmds.xform(transform, query=True, matrix=True,
                                  worldSpace=True))
    mirrored = world * om.MMatrix(_mirror_matrix(axis, mirror_pivot))
    cmds.xform(transform, matrix=list(mirrored), worldSpace=True)
    if mirror_geometry:
        _bake_mirror(transform)
    return True


def _apply_mirror(created: List[Any],
                  mirror: str = "",
                  mirror_pivot: Any = None,
                  mirror_geometry: bool = True) -> None:
    """Mirror every copy, before the connection replay.

    Placement first, graph second: a connection that drives the transform is
    the authority, and ``_mirror_node`` steps aside when it finds one.
    """
    if not mirror:
        return
    axis = mirror.lower()
    if axis not in _MIRROR_AXES:
        logger.warning(f"duplicate_nodes: unknown mirror axis '{mirror}', "
                       f"expected one of {sorted(_MIRROR_AXES)} - skipped")
        return
    done = 0
    for node in created:
        try:
            done += 1 if _mirror_node(node, axis, mirror_pivot,
                                      mirror_geometry) else 0
        except Exception as e:
            name = getattr(node, "node", node)
            logger.warning(f"mirror: '{name}' failed: {e}")
    logger.info(f"mirror: {done} node(s) reflected across {axis}")


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


def _resolve_parent_target(parent_to: Any) -> Optional[str]:
    """Return the parent target as a scene node name, or None when unusable.

    Accepts a node name or a MayaNode instance (its transform is used).
    """
    if parent_to is None or parent_to == "":
        return None
    target = parent_to if isinstance(parent_to, str) else parent_to.tr
    if not target or not cmds.objExists(target):
        logger.warning(f"duplicate_nodes: parent_to '{target}' not found, "
                       f"ignored")
        return None
    return target


def duplicate_nodes(nodes: Optional[List[Any]] = None,
                    with_constraints: bool = True,
                    with_outputs: bool = False,
                    skip: Optional[list] = None,
                    parent_to: Optional[Any] = None,
                    mirror: str = "",
                    mirror_pivot: Optional[Any] = None,
                    mirror_geometry: bool = True,
                    swap_sides: Optional[bool] = None,
                    search_replace: Optional[tuple] = None) -> List[Any]:
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
        parent_to: Node name or MayaNode to parent every duplicated source
            under (world position kept). Constraints are left where the
            native command puts them. Default None keeps the original's
            parent.
        mirror: World axis to reflect the copies across ("x", "y", "z"), for
            building the other side of a symmetrical setup. Empty (default)
            duplicates in place.
        mirror_pivot: Node the mirror plane passes through (its world rotate
            pivot). Default None mirrors around the world origin.
        mirror_geometry: Bake the mirror into the points of meshes (freeze +
            reverse winding) instead of leaving a -1 scale, which would show
            up as inside-out normals in collisions and shading. Curves,
            surfaces and joints keep the negative scale either way.
        swap_sides: Rename each copy by swapping its left/right token
            (:func:`swap_side_name`). Default None follows ``mirror``: on
            when mirroring, off for a plain duplicate.
        search_replace: Explicit ``("L_", "R_")`` substring pair, used
            instead of the side-token swap when the naming convention is one
            it cannot guess.

    Returns:
        The wrapped duplicates (sources first, then their constraints).
    """
    wrapped = _wrap_nodes(nodes)
    if not wrapped:
        return []
    parent_target = _resolve_parent_target(parent_to)
    swap_sides = bool(mirror) if swap_sides is None else swap_sides

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
        # Rename BEFORE the path is recorded, for the same reason as the
        # re-parent below: the rename map stores full paths.
        if swap_sides or search_replace:
            dup = cmds.rename(dup, _copy_name(original, search_replace,
                                              swap_sides))
        dup_path = cmds.ls(dup, long=True)[0]
        # Re-parent BEFORE recording the copy in the rename map: the map
        # stores full paths, and a later cmds.parent would invalidate them.
        if parent_target:
            dup_node = _wrap(dup_path)
            if dup_node and dup_node.tr:
                dup_node.parentTo(parent_target)
                dup_path = cmds.ls(dup_node.tr, long=True)[0]
        # The duplicate drags constrained children along as dead constraint
        # copies (still wired to the copy's channels, still aimed at the
        # ORIGINAL targets) - they would fight the proper rebuild in pass 1b
        # and leave the copy holding two constraints. listRelatives rather
        # than ls(dup_path, dag=True, type="constraint"): both find the same
        # descendants (verified in Maya 2022), but this asks the question
        # directly and can never match the duplicated node itself.
        try:
            junk = cmds.listRelatives(dup_path, allDescendents=True,
                                      type="constraint", fullPath=True) or []
        except Exception:
            junk = []
        if junk:
            logger.debug(f"duplicate_nodes: dropping {len(junk)} constraint "
                         f"copy/copies the native duplicate brought along")
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
            ctx.name_map[identity] = _copy_name(original, search_replace,
                                                swap_sides)
        created[i] = pcomp.node_from_preset(identity, body, ctx,
                                            skip=pass1_skip)

    # Placement pass - reflect the copies before the graph is replayed.
    _apply_mirror(created, mirror, mirror_pivot, mirror_geometry)

    # Pass 2 - replay connections now that every copy exists.
    _replay_connections(created, entries, ctx, with_outputs, skip)
    return [node for node in created if node is not None]


def mn_duplicate_nodes(nodes: Optional[List[Any]] = None,
                       with_constraints: bool = True,
                       with_outputs: bool = False,
                       skip: Optional[list] = None,
                       parent_to: Optional[Any] = None,
                       mirror: str = "",
                       mirror_pivot: Optional[Any] = None,
                       mirror_geometry: bool = True,
                       swap_sides: Optional[bool] = None,
                       search_replace: Optional[tuple] = None) -> List[Any]:
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
        parent_to: Node name or MayaNode to parent every duplicated source
            under (world position kept); wins over the stored hierarchy
            slice. Default None keeps the preset placement.
        mirror / mirror_pivot / mirror_geometry / swap_sides /
        search_replace: Symmetry options - see :func:`duplicate_nodes`.

    Returns:
        The wrapped duplicates (sources first, then their constraints).
    """
    wrapped = _wrap_nodes(nodes)
    if not wrapped:
        return []
    parent_target = _resolve_parent_target(parent_to)
    swap_sides = bool(mirror) if swap_sides is None else swap_sides

    entries = _capture_entries(wrapped, with_constraints, skip)

    # Seed every identity with a fresh name (same namespace) so the rebuild
    # creates copies instead of resolving back onto the originals. With a
    # side swap this is also where the copy gets its mirrored name, rather
    # than a numbered one it would have to be renamed out of afterwards.
    ctx = pcomp.PresetContext(create=True)
    for identity, _, original, _ in entries:
        if identity not in ctx.name_map:
            ctx.name_map[identity] = _copy_name(original, search_replace,
                                                swap_sides)

    # Pass 1 - create everything, connections deferred.
    pass1_skip = ["connections"] + list(skip or [])
    created = [pcomp.node_from_preset(identity, body, ctx, skip=pass1_skip)
               for identity, body, _, _ in entries]

    # Re-parent the source copies (constraints stay where their rebuild put
    # them), refreshing the rename map entries the move invalidates.
    if parent_target:
        for node, (identity, _, _, needs_preset) in zip(created, entries):
            if needs_preset or node is None or not node.tr:
                continue
            node.parentTo(parent_target)
            ctx.name_map[identity] = node.tr or node.node

    # Placement pass - reflect the copies before the graph is replayed.
    _apply_mirror(created, mirror, mirror_pivot, mirror_geometry)

    # Pass 2 - replay connections now that every copy exists.
    _replay_connections(created, entries, ctx, with_outputs, skip)
    return created