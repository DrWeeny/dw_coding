"""Composable preset components for MayaNode save / load.

A preset is a versioned, JSON-portable document describing one or more Maya
nodes well enough to re-apply (or rebuild) them in another session. Instead of
one monolithic save/load routine, each *kind* of data a node carries is a
``PresetComponent`` - a small capture/apply pair. A ``MayaNode`` subclass simply
declares which components it owns (``preset_components``), so adding a new data
kind (geometry points, animation curves, a node network) never means editing the
core save/load code.

This replaces the historical split where capture lived in ``createAttrPreset``
and apply lived far away in ``loadNode`` / ``blend_attr_dic``, and folds the
duplicated numeric-blend helpers down to a single ``apply_attr``.

Envelope (format ``dw_preset``, version 2)::

    {
        "format": "dw_preset",
        "version": 2,
        "namespaces": {"asset": ["man_01"], "external": ["alien_999", ":"]},
        "nodes": {
            "<identity>": {
                "nodeType": "mesh",
                "attributes": {"transform": {...}, "shape": {...}},
                ...one key per component...
            }
        }
    }

Namespace model: a node's own namespace is *the asset* (``man_01``, ``man_02``
are instances of the same preset). Names inside the asset are stored stripped
(relocatable via ``PresetContext.target_ns``); names in *other* namespaces
(another character, a shot collider) are **external** - kept verbatim,
remappable via ``PresetContext.ext_ns_map``, skippable via
``PresetContext.apply_external``, and expected to be missing in shots that
lack the other asset (report them softer than internal misses). The top-level
``namespaces`` summary exists so a remap UI never has to parse the pairs.

Classes:
    PresetContext: shared state threaded through every apply (target namespace,
        name remapping, blend factor, create flag).
    PresetComponent: capture/apply base class.
    AttributeComponent: scalar / string attribute capture + blended apply.

Functions:
    apply_attr: single-source blended setAttr (numeric / enum / string).
    node_from_preset: rebuild a node from a stored entry, dispatching on the
        node registry so the right subclass (and its components) runs.

Author:
    DrWeeny
"""

from typing import Any, Dict, List, Optional, Iterator
from dataclasses import dataclass, field

from maya import cmds

import dw_maya.dw_presets_io.dw_preset as dw_preset
import dw_maya.dw_presets_io.dw_json as dw_json
from dw_logger import get_logger

logger = get_logger()

# Document-format marker for the preset envelope. Named "format" (not "schema")
# on purpose: "schema" is reserved vocabulary for the `das` library (Dictionary
# As Struct - .schema files, SchemaType, get_schema_type()), which these presets
# are meant to interoperate with. Keeping the words distinct avoids the clash -
# the envelope's "format" identifies the dw_preset document; a das "schema type"
# (e.g. validating a component slice) is a separate concept layered on top later.
PRESET_FORMAT = "dw_preset"
PRESET_VERSION = 2

# Maya attribute types that blend numerically.
_INT_LIKE = ("bool", "short", "long", "byte", "char")
_FLOAT_LIKE = ("float", "floatLinear", "double", "doubleLinear", "doubleAngle", "time")


# ---------------------------------------------------------------------------
# Shared apply primitive (replaces blendNumericAttr / applyAttrDirectly / ...)
# ---------------------------------------------------------------------------

def apply_attr(attr_path: str, value: Any, blend: float = 1.0) -> None:
    """Set ``attr_path`` to ``value``, blending numeric values when ``blend < 1``.

    The single source of truth for writing a preset value onto an attribute.
    Handles special tokens, strings (no blend), and per-type numeric blending
    (enum thresholds at 0.5, int-like rounds, float-like lerps).

    Args:
        attr_path: Full ``node.attr`` plug.
        value: Stored value (number, bool, string, or a SPECIAL_TOKENS key).
        blend: 1.0 sets ``value`` outright; < 1.0 blends with the current value.
    """
    if not cmds.objExists(attr_path) or not cmds.getAttr(attr_path, settable=True):
        return

    # Resolve special tokens ($RFSTART / $RFEND / ...).
    from dw_maya.dw_constants import SPECIAL_TOKENS
    if isinstance(value, str) and value in SPECIAL_TOKENS:
        value = SPECIAL_TOKENS[value]()

    if isinstance(value, str):
        cmds.setAttr(attr_path, value, type="string")
        return

    if blend < 0.999 and isinstance(value, (int, float, bool)):
        attr_type = cmds.getAttr(attr_path, type=True)
        current = cmds.getAttr(attr_path)
        if attr_type == "enum":
            value = current if blend < 0.5 else value
        elif attr_type in _INT_LIKE:
            value = int(value * blend + current * (1 - blend))
        elif attr_type in _FLOAT_LIKE:
            value = value * blend + current * (1 - blend)
        cmds.setAttr(attr_path, value)
    else:
        cmds.setAttr(attr_path, value)


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

@dataclass
class PresetContext:
    """State threaded through a whole apply pass.

    Centralizes the namespace / name-remap bookkeeping that used to be
    re-implemented per call site (``stripNamespace`` / ``correspondance`` /
    ``map_identity``). Components share one instance so a network rebuild can
    record the nodes it created in ``name_map`` and later rewire through it.

    Attributes:
        target_ns: Namespace rebuilt / retargeted nodes land in (``:`` = root).
        blend: Blend factor passed to numeric ``apply_attr`` calls.
        create: When True, components may create nodes from scratch rather than
            only modifying an existing target.
        name_map: Source identity -> created/resolved node name.
        apply_external: When False, stored names that were captured as
            *external* (foreign-namespace, kept verbatim - see
            ConnectionComponent) are skipped on apply instead of resolved.
        ext_ns_map: External-namespace remap applied before resolving external
            names, e.g. ``{":": "man_01", "alien_999": "alien01",
            "god_00": ":"}`` (``:`` stands for the root namespace on either
            side). Does not affect internal (asset) names - those follow
            ``target_ns``.
    """
    target_ns: str = ":"
    blend: float = 1.0
    create: bool = False
    name_map: Dict[str, str] = field(default_factory=dict)
    apply_external: bool = True
    ext_ns_map: Dict[str, str] = field(default_factory=dict)

    def resolve_name(self, identity: str) -> str:
        """Return ``identity`` qualified with ``target_ns`` (root-safe)."""
        if self.target_ns in (":", ""):
            return identity
        return f"{self.target_ns}:{identity}"


# ---------------------------------------------------------------------------
# Component base
# ---------------------------------------------------------------------------

class PresetComponent:
    """One kind of node data, as a capture/apply pair.

    Subclasses set ``key`` (the dict key the slice is stored under) and
    implement ``capture`` / ``apply``. Keep components stateless beyond
    configuration so a single instance can be shared on a class ``preset_components``.
    """

    key = ""
    enabled_by_default = True

    def capture(self, node: "Any", ctx: PresetContext) -> Optional[Dict]:
        """Return this component's slice for ``node``, or None to omit it."""
        raise NotImplementedError

    def apply(self, node: "Any", data: Dict, ctx: PresetContext) -> None:
        """Apply a previously captured slice onto ``node``."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Attribute component
# ---------------------------------------------------------------------------

def _flat_attrs(node: str,
                filter_match: Optional[list] = None,
                filter_exclude: Optional[list] = None,
                in_channelbox: bool = False) -> Dict[str, Any]:
    """Capture ``node`` attributes as a flat ``{attr: value}`` dict.

    Reuses the tested scalar / string scan in ``createAttrPreset`` and strips
    its ``{name: {nodeType, ...}}`` wrapper (nodeType lives at entry level here).
    """
    raw = dw_preset.createAttrPreset(node,
                                     filter_match=filter_match,
                                     filter_exclude=filter_exclude,
                                     in_channelbox=in_channelbox)
    if not raw:
        return {}
    body = next(iter(raw.values()))
    body.pop("nodeType", None)
    return body


class AttributeComponent(PresetComponent):
    """Scalar / string attribute capture and blended apply.

    Splits values by role so a transform's attrs and its shape's attrs stay
    distinct: ``{"transform": {...}, "shape": {...}}`` for a DAG pair, or
    ``{"node": {...}}`` for a single (shape-less / DG) node.
    """

    key = "attributes"
    enabled_by_default = True

    def __init__(self,
                 filter_match: Optional[list] = None,
                 filter_exclude: Optional[list] = None,
                 in_channelbox: bool = False):
        self.filter_match = filter_match
        self.filter_exclude = filter_exclude
        self.in_channelbox = in_channelbox

    def _scan(self, node: str) -> Dict[str, Any]:
        return _flat_attrs(node,
                           filter_match=self.filter_match,
                           filter_exclude=self.filter_exclude,
                           in_channelbox=self.in_channelbox)

    def capture(self, node: "Any", ctx: PresetContext) -> Optional[Dict]:
        tr, sh = node.tr, node.sh
        out: Dict[str, Dict[str, Any]] = {}
        if tr and sh and tr != sh:
            out["transform"] = self._scan(tr)
            out["shape"] = self._scan(sh)
        else:
            out["node"] = self._scan(node.node)
        # Drop empty role dicts; omit the whole slice if nothing was captured.
        out = {role: attrs for role, attrs in out.items() if attrs}
        return out or None

    def apply(self, node: "Any", data: Dict, ctx: PresetContext) -> None:
        roles = {"transform": node.tr, "shape": node.sh, "node": node.node}
        for role, attrs in data.items():
            target = roles.get(role)
            if not target:
                continue
            for attr, value in attrs.items():
                apply_attr(f"{target}.{attr}", value, ctx.blend)


# ---------------------------------------------------------------------------
# Connection component
# ---------------------------------------------------------------------------

#: Node types whose connections are never captured (scene-global singletons).
_DEFAULT_SKIP_CONN_TYPES = (
    "nodeGraphEditorInfo",
    "defaultRenderUtilityList",
    "defaultTextureList",
    "defaultShaderList",
    "defaultLightList",
)


def _plug_node(plug: str) -> str:
    """Return the node portion of a ``node.attr`` plug (path/namespace kept)."""
    return plug.split(".", 1)[0]


def _strip_plug(plug: str) -> str:
    """Strip dag path + namespace from a plug's node, keeping the attr part."""
    node_part, sep, attr_part = plug.partition(".")
    short = node_part.split("|")[-1].split(":")[-1]
    return f"{short}{sep}{attr_part}"


def _node_namespace(node: str) -> str:
    """Return the namespace prefix of ``node`` ('' for root, dag path dropped).

    ``'man_01:cfx:body'`` -> ``'man_01:cfx'``; ``'body'`` / ``':body'`` -> ``''``.
    """
    short = node.split("|")[-1].lstrip(":")
    if ":" not in short:
        return ""
    return short.rsplit(":", 1)[0]


def resolve_scene_node(name: str, ctx: PresetContext) -> Optional[str]:
    """Resolve a stored *internal* (asset-relative) node name to a scene node.

    Shared by every component that stores node names. Internal names were
    captured with the asset namespace stripped - either fully (``'body'``) or
    down to a relative sub-namespace (``'cfx:body'`` in recursive-namespace
    captures). Resolution order: rename map -> target-namespace qualified
    (relative name first, then bare short name) -> bare short name -> stored
    name as-is -> any-namespace recursive lookup (unambiguous hits only).

    External (foreign-namespace) names go through
    :func:`resolve_external_node` instead - they are never relocated into
    ``ctx.target_ns``.
    """
    relative = name.split("|")[-1].lstrip(":")
    short = relative.split(":")[-1]
    mapped = ctx.name_map.get(short)
    if mapped:
        if cmds.objExists(mapped):
            return mapped
        # A full-path map entry goes stale when the node (or an ancestor) is
        # re-parented after being recorded - fall through to the name-based
        # lookups and refresh the map with whatever they find.
    candidates = []
    if relative != short:
        candidates.append(ctx.resolve_name(relative))
    candidates.extend((ctx.resolve_name(short), short, name))
    for cand in candidates:
        if cmds.objExists(cand):
            if mapped:
                ctx.name_map[short] = cand
            return cand
    hits = cmds.ls(short, recursive=True) or []
    if len(hits) == 1:
        if mapped:
            ctx.name_map[short] = hits[0]
        return hits[0]
    if hits:
        logger.warning(f"resolve_scene_node: '{short}' is ambiguous across "
                       f"namespaces ({hits}), skipping")
    return None


def resolve_external_node(name: str, ctx: PresetContext) -> Optional[str]:
    """Resolve a stored *external* (foreign-namespace) node name.

    External names are captured verbatim (``'alien_999:sphere'``; a leading
    ``:`` marks an explicit root-namespace node, ``':sphere'``) and are never
    relocated into ``ctx.target_ns``. ``ctx.ext_ns_map`` remaps the namespace
    first (full prefix, then its top-level root, so ``{'alien_999': 'alien01'}``
    also covers ``alien_999:fx:sphere``); the remapped then the stored name are
    tried as-is. No any-namespace fallback: a missing external node usually
    just means the other asset is not in this shot, and callers should report
    it at a lower severity than a missing internal node.
    """
    if not ctx.apply_external:
        return None
    short = name.split("|")[-1]
    leafless_ns = _node_namespace(short) or ":"
    candidates = []
    mapped_ns = ctx.ext_ns_map.get(leafless_ns)
    if mapped_ns is None and ":" in leafless_ns.strip(":"):
        # Root-level remap covering nested categories (alien_999:fx -> ...).
        root, rest = leafless_ns.split(":", 1)
        root_mapped = ctx.ext_ns_map.get(root)
        if root_mapped is not None:
            mapped_ns = rest if root_mapped in (":", "") else f"{root_mapped}:{rest}"
    if mapped_ns is not None:
        leaf = short.split(":")[-1]
        if mapped_ns in (":", ""):
            candidates.append(f":{leaf}")
        else:
            candidates.append(f"{mapped_ns}:{leaf}")
    candidates.append(short)
    for cand in candidates:
        if cmds.objExists(cand):
            return cand
    logger.info(f"resolve_external_node: '{name}' not in scene (expected when "
                f"the external asset is absent from this shot)")
    return None


class ConnectionComponent(PresetComponent):
    """Capture / restore a node's connections as remappable plug pairs.

    Stores directed pairs (``{"pairs": [[src, dst], ...]}``) and replays them
    through :class:`PresetContext` so a rebuilt graph reconnects under a new
    namespace. ``io`` selects the captured directions as ``(incoming,
    outgoing)`` booleans. Incoming-only by default - in a whole-graph rebuild
    every node records its own inputs, so capturing outputs too would just
    duplicate. Use ``io=(True, True)`` for single-node presets that must also
    keep their downstream links (e.g. mesh -> shadingGroup, constraint ->
    driven node).

    Namespace semantics - the captured node's namespace is *the asset*:

    - **internal** plugs (same asset) are namespace-stripped so the preset
      relocates onto ``man_02`` etc. via ``ctx.target_ns``.
    - **external** plugs (another namespace: the other character, a shot
      collider) keep their namespace verbatim when
      ``keep_external_namespace`` is True (default) - a root-namespace
      external node is stored with an explicit leading ``:``. Their top-level
      namespaces are recorded in the slice's ``external_ns`` list so apply /
      report can tell the two classes apart without re-parsing pairs. On
      apply they resolve through :func:`resolve_external_node`
      (``ctx.ext_ns_map`` remap, no relocation) and are skipped wholesale
      when ``ctx.apply_external`` is False. With
      ``keep_external_namespace=False`` everything is stripped (legacy
      behavior, lossy in multi-asset shots).
    - ``recursive_namespace=True`` widens "the asset" from the node's exact
      namespace to its top-level root: with categorising namespaces like
      ``man_01:cfx`` / ``man_01:animation``, sibling categories count as
      internal and are stored relative (``animation:mesh``). Off by default -
      then only plugs in exactly the node's namespace are internal.
    """

    key = "connections"
    enabled_by_default = True

    def __init__(self,
                 io: tuple = (True, False),
                 skip_types: tuple = _DEFAULT_SKIP_CONN_TYPES,
                 keep_external_namespace: bool = True,
                 recursive_namespace: bool = False):
        self.io = (bool(io[0]), bool(io[1]))
        self.skip_types = tuple(skip_types)
        self.keep_external_namespace = keep_external_namespace
        self.recursive_namespace = recursive_namespace

    def _targets(self, node: "Any") -> List[str]:
        """The actual Maya nodes this wrapper owns (transform and/or shape)."""
        out = []
        if node.tr:
            out.append(node.tr)
        if node.sh and node.sh != node.tr:
            out.append(node.sh)
        return out or [node.node]

    def _skip(self, plug: str, local_short: set) -> bool:
        node_part = _plug_node(plug)
        # Drop self (tr <-> sh) links - createNode recreates those.
        if node_part.split("|")[-1].split(":")[-1] in local_short:
            return True
        try:
            return cmds.nodeType(node_part) in self.skip_types
        except Exception:
            return True

    def _store_plug(self,
                    plug: str,
                    asset_ns: str,
                    external_ns: set) -> str:
        """Return the stored form of ``plug``, recording foreign namespaces.

        Internal plugs come out asset-relative (namespace stripped, or stripped
        down to the sub-namespace in recursive mode); external plugs keep their
        namespace, with a leading ``:`` marking explicit root. Top-level
        namespaces of external plugs accumulate into ``external_ns``.
        """
        node_part, sep, attr_part = plug.partition(".")
        short = node_part.split("|")[-1].lstrip(":")
        ns = _node_namespace(short)

        if not self.keep_external_namespace:
            return f"{short.split(':')[-1]}{sep}{attr_part}"

        if (self.recursive_namespace and asset_ns and ns
                and ns.split(":")[0] == asset_ns.split(":")[0]):
            # Same asset root (own or sibling category): store relative to the
            # root so target_ns (the new root) restores the category path.
            stored = short.split(":", 1)[1]
        elif ns == asset_ns:
            stored = short.split(":")[-1]
        elif ns:
            external_ns.add(ns.split(":")[0])
            stored = short
        else:
            # Foreign node sitting in the root namespace (shot-level item).
            external_ns.add(":")
            stored = f":{short}"
        return f"{stored}{sep}{attr_part}"

    def capture(self, node: "Any", ctx: PresetContext) -> Optional[Dict]:
        targets = self._targets(node)
        local_short = {t.split("|")[-1].split(":")[-1] for t in targets}
        asset_ns = _node_namespace(targets[0])
        external_ns: set = set()
        pairs: List[List[str]] = []
        seen = set()

        def _add(src: str, dst: str):
            key = (self._store_plug(src, asset_ns, external_ns),
                   self._store_plug(dst, asset_ns, external_ns))
            if key not in seen:
                seen.add(key)
                pairs.append([key[0], key[1]])

        for target in targets:
            if self.io[0]:
                conns = cmds.listConnections(target, s=True, d=False,
                                             p=True, c=True) or []
                for i in range(0, len(conns), 2):
                    local, other = conns[i], conns[i + 1]
                    if not self._skip(other, local_short):
                        _add(other, local)   # other -> this node
            if self.io[1]:
                conns = cmds.listConnections(target, s=False, d=True,
                                             p=True, c=True) or []
                for i in range(0, len(conns), 2):
                    local, other = conns[i], conns[i + 1]
                    if not self._skip(other, local_short):
                        _add(local, other)   # this node -> other

        if not pairs:
            return None
        data: Dict[str, Any] = {"pairs": pairs}
        if self.keep_external_namespace:
            # Always written (even empty) so apply can tell a new-format slice
            # (relative names may contain ':') from a legacy all-stripped one.
            data["asset_ns"] = asset_ns
            data["external_ns"] = sorted(external_ns)
        return data

    @staticmethod
    def _is_external(stored_node: str, data: Dict) -> bool:
        """True when a stored node name was captured as external.

        Legacy slices (no ``external_ns`` key) are all-internal by
        construction. In new slices a leading ``:`` marks a root-namespace
        external; otherwise the name's top-level namespace is checked against
        the recorded ``external_ns`` list (relative internal names from
        recursive captures may contain ``:`` too, so the colon alone does not
        decide).
        """
        if "external_ns" not in data:
            return False
        if stored_node.startswith(":"):
            return True
        if ":" not in stored_node:
            return False
        return stored_node.split(":")[0] in data["external_ns"]

    def _resolve_plug(self, plug: str, data: Dict, ctx: PresetContext) -> Optional[str]:
        node_part, _, attr_part = plug.partition(".")
        if self._is_external(node_part, data):
            resolved = resolve_external_node(node_part, ctx)
        else:
            resolved = resolve_scene_node(node_part, ctx)
        if not resolved:
            return None
        return f"{resolved}.{attr_part}"

    def apply(self, node: "Any", data: Dict, ctx: PresetContext) -> None:
        skipped_external = 0
        for src, dst in data.get("pairs", []):
            if not ctx.apply_external and (
                    self._is_external(_plug_node(src), data)
                    or self._is_external(_plug_node(dst), data)):
                skipped_external += 1
                continue
            s = self._resolve_plug(src, data, ctx)
            d = self._resolve_plug(dst, data, ctx)
            if not s or not d:
                continue
            try:
                if not cmds.isConnected(s, d):
                    cmds.connectAttr(s, d, force=True)
            except Exception as e:
                logger.warning(f"ConnectionComponent: connect {s} -> {d} failed: {e}")
        if skipped_external:
            logger.info(f"ConnectionComponent: skipped {skipped_external} "
                        f"external connection(s) (ctx.apply_external=False)")


# ---------------------------------------------------------------------------
# Hierarchy component
# ---------------------------------------------------------------------------

class HierarchyComponent(PresetComponent):
    """Capture / restore the transform's parent.

    Stores the namespace-stripped parent name (plus the full ancestor chain
    for context) so a rebuilt node lands back under its group. Apply resolves
    the parent through :func:`resolve_scene_node`; when the parent is missing
    and ``ctx.create`` is set, an empty transform group is created.

    Re-parenting uses ``relative=True`` so the local TRS values written by
    :class:`AttributeComponent` stay valid - which also means this component
    must run *before* attributes in a class ``preset_components`` tuple.
    """

    key = "hierarchy"
    enabled_by_default = True

    def capture(self, node: "Any", ctx: PresetContext) -> Optional[Dict]:
        tr = node.tr
        if not tr:
            return None
        parent = cmds.listRelatives(tr, parent=True, fullPath=True)
        if not parent:
            return None  # world-level node: nothing to restore
        chain = [p.split(":")[-1] for p in parent[0].split("|") if p]
        return {"parent": chain[-1], "path": chain}

    def apply(self, node: "Any", data: Dict, ctx: PresetContext) -> None:
        tr = node.tr
        parent_short = data.get("parent")
        if not tr or not parent_short:
            return
        current = cmds.listRelatives(tr, parent=True) or []
        if current and current[0].split("|")[-1].split(":")[-1] == parent_short:
            return  # already under the right parent
        resolved = resolve_scene_node(parent_short, ctx)
        if not resolved and ctx.create:
            resolved = cmds.createNode("transform",
                                       name=ctx.resolve_name(parent_short),
                                       skipSelect=True)
            logger.info(f"HierarchyComponent: created missing parent group "
                        f"'{resolved}'")
        if not resolved:
            logger.warning(f"HierarchyComponent: parent '{parent_short}' not "
                           f"found, '{tr}' left where it is")
            return
        try:
            cmds.parent(tr, resolved, relative=True)
        except Exception as e:
            logger.warning(f"HierarchyComponent: parent '{tr}' -> "
                           f"'{resolved}' failed: {e}")


# ---------------------------------------------------------------------------
# Geometry component (deform-level point positions)
# ---------------------------------------------------------------------------

class GeometryComponent(PresetComponent):
    """Capture / restore a mesh's geometry ("@P" plus topology).

    Two fidelity levels, chosen automatically on apply:

    - **deform** - the target already has matching topology: the stored point
      array is written back (with optional blend). A vertex-count mismatch is
      skipped with a warning rather than raising.
    - **rebuild** - the target has no geometry yet (e.g. a freshly created empty
      mesh): the full mesh is recreated from stored points + polygon topology via
      ``MFnMesh.create``, UVs are restored, and ``initialShadingGroup`` assigned.

    Points are object space by default - local positions survive transform edits
    and are what re-applying onto the same mesh wants; world space is left to the
    cross-mesh transfer tool. ``with_topology`` / ``with_uvs`` control whether the
    heavier slices are captured (both on by default so rebuild works).

    Caveat: a mesh with live construction history feeding ``inMesh`` recomputes
    its output, so restored points only stick on history-free geometry (cached /
    sculpted meshes) - the usual case for this kind of snapshot.
    """

    key = "geometry"
    enabled_by_default = True

    def __init__(self,
                 space: str = "object",
                 round_ndigits: int = 6,
                 with_topology: bool = True,
                 with_uvs: bool = True):
        self.space = space  # "object" | "world"
        self.round_ndigits = round_ndigits
        self.with_topology = with_topology
        self.with_uvs = with_uvs

    def _mesh_shape(self, node: "Any") -> Optional[str]:
        sh = node.sh
        if sh and cmds.nodeType(sh) == "mesh":
            return sh
        shapes = cmds.listRelatives(node.tr, shapes=True, type="mesh",
                                    noIntermediate=True, fullPath=True) or []
        return shapes[0] if shapes else None

    def _mfn(self, shape: str):
        import maya.api.OpenMaya as om2
        sel = om2.MSelectionList()
        sel.add(shape)
        return om2.MFnMesh(sel.getDagPath(0))

    def _space(self, name: str):
        import maya.api.OpenMaya as om2
        return om2.MSpace.kWorld if name == "world" else om2.MSpace.kObject

    def capture(self, node: "Any", ctx: PresetContext) -> Optional[Dict]:
        shape = self._mesh_shape(node)
        if not shape:
            return None
        fn = self._mfn(shape)
        r = self.round_ndigits
        pts = fn.getPoints(self._space(self.space))
        data = {
            "space": self.space,
            "count": len(pts),
            "points": [[round(p.x, r), round(p.y, r), round(p.z, r)] for p in pts],
        }
        if self.with_topology:
            counts, connects = fn.getVertices()
            data["poly_counts"] = list(counts)
            data["poly_connects"] = list(connects)
        if self.with_uvs and fn.numUVs() > 0:
            us, vs = fn.getUVs()
            uv_counts, uv_ids = fn.getAssignedUVs()
            data["uvs"] = {
                "u": [round(u, r) for u in us],
                "v": [round(v, r) for v in vs],
                "counts": list(uv_counts),
                "ids": list(uv_ids),
            }
        return data

    def apply(self, node: "Any", data: Dict, ctx: PresetContext) -> None:
        import maya.api.OpenMaya as om2

        shape = self._mesh_shape(node)
        counts = data.get("poly_counts")
        connects = data.get("poly_connects")

        # An empty mesh (createNode('mesh') with no geometry) cannot be wrapped
        # by MFnMesh, so probe the vertex count defensively.
        fn = None
        num_verts = 0
        if shape:
            try:
                fn = self._mfn(shape)
                num_verts = fn.numVertices
            except Exception:
                num_verts = 0

        # Rebuild-level: no usable geometry yet but topology is available.
        if (shape is None or num_verts == 0) and counts and connects:
            self._rebuild(node, data)
            return

        if not shape or fn is None:
            logger.warning("GeometryComponent: no mesh shape and no topology to "
                           f"rebuild on '{node.node}'; skipping.")
            return

        stored = data.get("points", [])
        if len(stored) != num_verts:
            logger.warning(f"GeometryComponent: vtx count mismatch on '{shape}' "
                           f"(stored {len(stored)} vs mesh {num_verts}); skipping.")
            return

        space = self._space(data.get("space", self.space))
        if ctx.blend < 0.999:
            current = fn.getPoints(space)
            b = ctx.blend
            new_pts = om2.MPointArray()
            for i, (x, y, z) in enumerate(stored):
                c = current[i]
                new_pts.append(om2.MPoint(x * b + c.x * (1 - b),
                                          y * b + c.y * (1 - b),
                                          z * b + c.z * (1 - b)))
        else:
            new_pts = om2.MPointArray([om2.MPoint(x, y, z) for x, y, z in stored])
        fn.setPoints(new_pts, space)

    def _rebuild(self, node: "Any", data: Dict) -> None:
        """Recreate the mesh from stored points + topology under node.tr.

        Builds the new mesh under the existing transform, removes the empty
        leftover shape (e.g. from a prior ``createNode('mesh')``), restores UVs
        and assigns the default shading group. Points are treated as object
        space relative to the transform.
        """
        import maya.api.OpenMaya as om2

        tr = node.tr
        before = set(cmds.listRelatives(tr, shapes=True, fullPath=True) or [])

        sel = om2.MSelectionList()
        sel.add(tr)
        parent_obj = sel.getDependNode(0)

        verts = om2.MFloatPointArray(
            [om2.MFloatPoint(float(x), float(y), float(z)) for x, y, z in data["points"]])
        counts = om2.MIntArray(data["poly_counts"])
        connects = om2.MIntArray(data["poly_connects"])

        fn = om2.MFnMesh()
        fn.create(verts, counts, connects, parent=parent_obj)

        # Restore UVs while the function set still points at the new mesh.
        uvs = data.get("uvs")
        if uvs:
            try:
                fn.setUVs(om2.MFloatArray([float(u) for u in uvs["u"]]),
                          om2.MFloatArray([float(v) for v in uvs["v"]]))
                fn.assignUVs(om2.MIntArray(uvs["counts"]), om2.MIntArray(uvs["ids"]))
            except Exception as e:
                logger.warning(f"GeometryComponent: UV rebuild failed on '{tr}': {e}")

        after = set(cmds.listRelatives(tr, shapes=True, fullPath=True) or [])
        new_shapes = list(after - before)

        # Drop the empty leftover shape(s) so the transform keeps a single mesh.
        if before:
            cmds.delete(list(before))

        tr_short = tr.split("|")[-1].split(":")[-1]
        for sh in new_shapes:
            try:
                cmds.sets(sh, edit=True, forceElement="initialShadingGroup")
            except Exception:
                pass
        if new_shapes:
            try:
                cmds.rename(new_shapes[0], f"{tr_short}Shape")
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Keyframe component (animCurves)
# ---------------------------------------------------------------------------

def apply_anim_curve(plug: str, cdata: Dict, clear: bool = True) -> None:
    """Write a captured animation curve onto ``plug`` (``node.attr``).

    The reusable primitive behind KeyframeComponent.apply - exposed so a curve
    captured on one node can be retargeted onto a *different* plug (e.g. baking
    a joint's animation onto a control). ``cdata`` is one attr's dict from a
    captured ``keyframes`` slice (``keys`` + ``weighted`` / ``pre`` / ``post``).

    Args:
        plug: Target ``node.attr`` to key.
        cdata: Curve data (keys with t/v/tangents, weighted flag, infinities).
        clear: Remove any existing animation on ``plug`` first (default True).
    """
    keys = cdata.get("keys", [])
    if clear:
        try:
            cmds.cutKey(plug, clear=True)
        except Exception:
            pass
    for k in keys:
        cmds.setKeyframe(plug, time=k["t"], value=k["v"])
    try:
        cmds.keyTangent(plug, edit=True, weightedTangents=cdata.get("weighted", False))
    except Exception:
        pass
    for k in keys:
        t = k["t"]
        try:
            cmds.keyTangent(plug, edit=True, time=(t, t),
                            inTangentType=k.get("itt", "auto"),
                            outTangentType=k.get("ott", "auto"))
        except Exception:
            pass
        # Angles / weights matter for fixed tangents; harmless otherwise.
        try:
            cmds.keyTangent(plug, edit=True, time=(t, t),
                            inAngle=k.get("ia", 0.0), outAngle=k.get("oa", 0.0),
                            inWeight=k.get("iw", 1.0), outWeight=k.get("ow", 1.0))
        except Exception:
            pass
    try:
        cmds.setInfinity(plug, edit=True,
                         preInfinite=cdata.get("pre", "constant"),
                         postInfinite=cdata.get("post", "constant"))
    except Exception:
        pass


def flatten_animation(anim_data: Dict) -> Dict[str, Dict]:
    """Merge a captured ``keyframes`` slice's role dicts into ``{attr: cdata}``.

    A capture splits curves by role (``transform`` / ``shape`` / ``node``);
    retargeting onto another node usually wants them flat, keyed by attribute.
    """
    flat: Dict[str, Dict] = {}
    for attrs in anim_data.values():
        flat.update(attrs)
    return flat


class KeyframeComponent(PresetComponent):
    """Capture / restore keyframed animCurves on a node's attributes.

    Named "keyframes" rather than "animation" on purpose: a channel can also
    be animated by an expression (or a driven connection), which this component
    does not capture - expressions come through as connections today and may
    get their own component later.

    Extends the historical value-only snapshot (``{attr: [(time, value)]}``,
    see presetSaver/dw_maps) to a full curve round-trip: per key it also stores
    in/out tangent types, angles and weights, plus the curve's weighted-tangent
    flag and pre/post infinity - so the rebuilt curve matches shape, not just
    values.

    Opt-in (``enabled_by_default = False``): include it with
    ``createPreset(only=[..., "keyframes"])``. Values are split by role
    (``transform`` / ``shape`` / ``node``) like AttributeComponent. Blend is not
    applied to curves - animation is restored wholesale.
    """

    key = "keyframes"
    enabled_by_default = False

    def _capture_target(self, target: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        target_short = target.split("|")[-1].split(":")[-1]
        curves = set(cmds.listConnections(target, type="animCurve",
                                          source=True, destination=False) or [])
        for curve in curves:
            driven = cmds.listConnections(f"{curve}.output", plugs=True,
                                          source=False, destination=True) or []
            for plug in driven:
                node_part, _, attr = plug.partition(".")
                if node_part.split("|")[-1].split(":")[-1] != target_short:
                    continue
                times = cmds.keyframe(plug, query=True) or []
                if not times:
                    continue
                values = cmds.keyframe(plug, query=True, valueChange=True) or []
                itt = cmds.keyTangent(plug, query=True, inTangentType=True) or []
                ott = cmds.keyTangent(plug, query=True, outTangentType=True) or []
                ia = cmds.keyTangent(plug, query=True, inAngle=True) or []
                oa = cmds.keyTangent(plug, query=True, outAngle=True) or []
                iw = cmds.keyTangent(plug, query=True, inWeight=True) or []
                ow = cmds.keyTangent(plug, query=True, outWeight=True) or []
                weighted = (cmds.keyTangent(plug, query=True,
                                            weightedTangents=True) or [False])[0]
                pre = (cmds.setInfinity(plug, query=True, preInfinite=True)
                       or ["constant"])[0]
                post = (cmds.setInfinity(plug, query=True, postInfinite=True)
                        or ["constant"])[0]

                keys = []
                for i, t in enumerate(times):
                    keys.append({
                        "t": t,
                        "v": values[i] if i < len(values) else 0.0,
                        "itt": itt[i] if i < len(itt) else "auto",
                        "ott": ott[i] if i < len(ott) else "auto",
                        "ia": ia[i] if i < len(ia) else 0.0,
                        "oa": oa[i] if i < len(oa) else 0.0,
                        "iw": iw[i] if i < len(iw) else 1.0,
                        "ow": ow[i] if i < len(ow) else 1.0,
                    })
                out[attr] = {
                    "curve_type": cmds.nodeType(curve),
                    "weighted": bool(weighted),
                    "pre": pre,
                    "post": post,
                    "keys": keys,
                }
        return out

    def capture(self, node: "Any", ctx: PresetContext) -> Optional[Dict]:
        tr, sh = node.tr, node.sh
        out: Dict[str, Dict] = {}
        if tr and sh and tr != sh:
            t = self._capture_target(tr)
            s = self._capture_target(sh)
            if t:
                out["transform"] = t
            if s:
                out["shape"] = s
        else:
            n = self._capture_target(node.node)
            if n:
                out["node"] = n
        return out or None

    def apply(self, node: "Any", data: Dict, ctx: PresetContext) -> None:
        roles = {"transform": node.tr, "shape": node.sh, "node": node.node}
        for role, attrs in data.items():
            target = roles.get(role)
            if not target:
                continue
            for attr, cdata in attrs.items():
                plug = f"{target}.{attr}"
                if cmds.objExists(plug):
                    apply_anim_curve(plug, cdata)


def collect_preset_namespaces(nodes: Dict[str, Dict]) -> Dict[str, list]:
    """Summarize the namespaces referenced by captured entries.

    Scans the connection slices for their recorded ``asset_ns`` /
    ``external_ns`` and returns ``{"asset": [...], "external": [...]}``
    (``:`` stands for the root namespace). Stored in the envelope so a remap
    UI can list its options without parsing every pair of every node.
    """
    asset: set = set()
    external: set = set()
    for body in nodes.values():
        conn = body.get("connections")
        if not isinstance(conn, dict):
            continue
        if "asset_ns" in conn:
            asset.add(conn["asset_ns"] or ":")
        external.update(conn.get("external_ns", []))
    return {"asset": sorted(asset), "external": sorted(external)}


# ---------------------------------------------------------------------------
# Rebuild dispatch
# ---------------------------------------------------------------------------

# Preset-specific class overrides, consulted before the node registry when
# rebuilding from a preset. Lets a class own a node type for *rebuild* purposes
# without registering it in dw_node_registry (e.g. Mesh for "mesh", which must
# stay unregistered there so lsNode's condition-based cloth / rigid resolution
# keeps working). Direct registrations land in PRESET_CLASSES; classes whose
# module cannot be imported here at import time (dw_maya_utils <-> dw_maya_nodes
# cycle, see dw_maya_hierarchy's module notes) are listed as deferred import
# paths and loaded on first use.
PRESET_CLASSES: Dict[str, type] = {}
_PRESET_CLASS_PATHS: Dict[str, tuple] = {
    "mesh": ("dw_maya.dw_maya_utils.mesh_class", "Mesh"),
}


def register_preset_class(node_type: str, cls: type) -> None:
    """Map ``node_type`` to ``cls`` for preset rebuilds only."""
    PRESET_CLASSES[node_type] = cls


def resolve_preset_class(node_type: str):
    """Return the preset-rebuild class for ``node_type``, or None.

    Checks direct registrations first, then the deferred-import paths
    (imported once, cached into PRESET_CLASSES).
    """
    cls = PRESET_CLASSES.get(node_type)
    if cls is not None:
        return cls
    path = _PRESET_CLASS_PATHS.get(node_type)
    if not path:
        return None
    import importlib
    try:
        module = importlib.import_module(path[0])
        cls = getattr(module, path[1])
    except Exception as e:
        logger.warning(f"resolve_preset_class: cannot load {path[0]}.{path[1]}: {e}")
        return None
    PRESET_CLASSES[node_type] = cls
    return cls


def node_from_preset(identity: str, body: Dict, ctx: Optional[PresetContext] = None) -> "Any":
    """Rebuild a single node from a stored entry, dispatching on its node type.

    Resolves the stored ``nodeType`` through the node registry so the correct
    ``MayaNode`` subclass - and therefore its components - runs the apply. This
    is the type-driven twin of ``lsNode()``: same registry, but keyed off the
    saved type string instead of a live scene node.

    Args:
        identity: Logical name of the entry (namespace-stripped).
        body: The entry dict (``nodeType`` + component slices).
        ctx: Apply context. A fresh one (create=True) is built when omitted.

    Returns:
        The wrapped node instance.
    """
    from dw_maya.dw_node_registry import resolve_type

    ctx = ctx or PresetContext(create=True)
    node_type = body.get("nodeType")
    cls = resolve_preset_class(node_type) or resolve_type(node_type)

    # A pre-seeded remap (load_preset_file(remap=...)) wins over the default
    # target-namespace naming, so an entry can be rebuilt under a new name.
    target = ctx.name_map.get(identity) or ctx.resolve_name(identity)
    if cmds.objExists(target):
        node = cls(target)
    else:
        # Documented "create new node" path: MayaNode(name, node_type). Building
        # the node here (rather than wrapping a missing name then poking .node)
        # avoids the accessors that assume an existing node, and suppresses the
        # "does not exist" warning the bare-name ctor would log.
        node = cls(target, node_type)
    node.applyPreset({"nodes": {identity: body}}, ctx)
    # Identity is transform-based (presetIdentity), so map it to the transform:
    # node.node defaults to the shape, and consumers of the map (constraint
    # rebuilds, connection replay) expect the name the identity stood for.
    # Recorded AFTER applyPreset: HierarchyComponent re-parents the node, so a
    # path snapshot taken at creation time (world root) would go stale.
    ctx.name_map[identity] = node.tr or node.node
    return node


def save_preset_file(nodes: List[Any],
                     path: str,
                     only: Optional[list] = None,
                     skip: Optional[list] = None,
                     defer: bool = False) -> bool:
    """Save several nodes into one ``dw_preset`` envelope, in the given order.

    Order matters on load: :func:`load_preset_file` rebuilds in saved order
    with one shared context, so put dependencies first (e.g. a collider mesh
    before the constraint that drives it).

    Args:
        nodes: Node names, MayaNode instances, and/or already-captured
            ``{identity: body}`` dicts (as returned by ``createPreset`` -
            merged as-is, ``only``/``skip`` do not re-filter them). Names are
            specialized through the registry (:func:`dw_lsNode.lsNode`) so
            type-specific components (constraint network, geometry, ...)
            are captured.
        path: Output json path.
        only / skip: Component-key filters forwarded to ``createPreset``.
        defer: Forwarded to ``save_json``.
    """
    import dw_maya.dw_lsNode as dw_lsNode

    data = {"format": PRESET_FORMAT,
            "version": PRESET_VERSION,
            "nodes": {}}
    for node in nodes:
        if isinstance(node, dict):
            data["nodes"].update(node.get("nodes", node))
            continue
        if isinstance(node, str):
            wrapped = dw_lsNode.lsNode(node)
            if not wrapped:
                logger.warning(f"save_preset_file: '{node}' not found, skipping")
                continue
            node = wrapped[0]
        data["nodes"].update(node.createPreset(only=only, skip=skip))
    if not data["nodes"]:
        logger.warning(f"save_preset_file: nothing captured, '{path}' not written")
        return False
    data["namespaces"] = collect_preset_namespaces(data["nodes"])
    logger.info(f"Saving preset to {path}")
    return dw_json.save_json(path, data, defer=defer)


def load_preset_file(path: str,
                     target_ns: str = ":",
                     create: bool = True,
                     remap: Optional[Dict[str, str]] = None,
                     apply_external: bool = True,
                     ext_ns_map: Optional[Dict[str, str]] = None) -> List[Any]:
    """Rebuild every node in a saved preset file. Returns the wrapped nodes.

    Args:
        path: Preset json path.
        target_ns: Namespace rebuilt nodes and name lookups resolve against.
        create: Allow creating missing nodes.
        remap: Optional ``{stored_identity: scene_node}`` overrides, seeded
            into the context's name map before anything applies - use it when
            a driver was renamed between save and load.
        apply_external: When False, connections captured toward *other*
            namespaces (external assets) are skipped instead of resolved.
        ext_ns_map: External-namespace remap, e.g. ``{"alien_999": "alien01",
            ":": "man_01", "god_00": ":"}``. The file's top-level
            ``namespaces["external"]`` lists valid keys.
    """
    data = dw_json.load_json(path)
    if not data or data.get("format") != PRESET_FORMAT:
        logger.warning(f"load_preset_file: '{path}' is not a {PRESET_FORMAT} file.")
        return []
    ctx = PresetContext(target_ns=target_ns, create=create,
                        apply_external=apply_external,
                        ext_ns_map=dict(ext_ns_map or {}))
    if remap:
        ctx.name_map.update(remap)
    return [node_from_preset(identity, body, ctx)
            for identity, body in data.get("nodes", {}).items()]