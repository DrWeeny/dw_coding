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
        "nodes": {
            "<identity>": {
                "nodeType": "mesh",
                "attributes": {"transform": {...}, "shape": {...}},
                ...one key per component...
            }
        }
    }

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
    """
    target_ns: str = ":"
    blend: float = 1.0
    create: bool = False
    name_map: Dict[str, str] = field(default_factory=dict)

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


class ConnectionComponent(PresetComponent):
    """Capture / restore a node's connections as remappable plug pairs.

    Stores namespace-stripped directed pairs (``{"pairs": [[src, dst], ...]}``)
    and replays them through :class:`PresetContext` so a rebuilt graph reconnects
    under a new namespace. Incoming-only by default - in a whole-graph rebuild
    every node records its own inputs, so capturing outputs too would just
    duplicate. Set ``directions=("in", "out")`` for single-node presets that must
    also keep their downstream links (e.g. mesh -> shadingGroup).
    """

    key = "connections"
    enabled_by_default = True

    def __init__(self,
                 directions: tuple = ("in",),
                 skip_types: tuple = _DEFAULT_SKIP_CONN_TYPES):
        self.directions = tuple(directions)
        self.skip_types = tuple(skip_types)

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

    def capture(self, node: "Any", ctx: PresetContext) -> Optional[Dict]:
        targets = self._targets(node)
        local_short = {t.split("|")[-1].split(":")[-1] for t in targets}
        pairs: List[List[str]] = []
        seen = set()

        def _add(src: str, dst: str):
            key = (_strip_plug(src), _strip_plug(dst))
            if key not in seen:
                seen.add(key)
                pairs.append([key[0], key[1]])

        for target in targets:
            if "in" in self.directions:
                conns = cmds.listConnections(target, s=True, d=False,
                                             p=True, c=True) or []
                for i in range(0, len(conns), 2):
                    local, other = conns[i], conns[i + 1]
                    if not self._skip(other, local_short):
                        _add(other, local)   # other -> this node
            if "out" in self.directions:
                conns = cmds.listConnections(target, s=False, d=True,
                                             p=True, c=True) or []
                for i in range(0, len(conns), 2):
                    local, other = conns[i], conns[i + 1]
                    if not self._skip(other, local_short):
                        _add(local, other)   # this node -> other

        return {"pairs": pairs} if pairs else None

    def _resolve_plug(self, plug: str, ctx: PresetContext) -> Optional[str]:
        node_part, _, attr_part = plug.partition(".")
        short = node_part.split("|")[-1].split(":")[-1]
        # 1. node created during this rebuild
        if short in ctx.name_map:
            resolved = ctx.name_map[short]
        else:
            # 2. target-namespace qualified, 3. bare short, 4. original plug node
            for cand in (ctx.resolve_name(short), short, node_part):
                if cmds.objExists(cand):
                    resolved = cand
                    break
            else:
                return None
        return f"{resolved}.{attr_part}"

    def apply(self, node: "Any", data: Dict, ctx: PresetContext) -> None:
        for src, dst in data.get("pairs", []):
            s = self._resolve_plug(src, ctx)
            d = self._resolve_plug(dst, ctx)
            if not s or not d:
                continue
            try:
                if not cmds.isConnected(s, d):
                    cmds.connectAttr(s, d, force=True)
            except Exception as e:
                logger.warning(f"ConnectionComponent: connect {s} -> {d} failed: {e}")


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
# Animation component (keyframes)
# ---------------------------------------------------------------------------

def apply_anim_curve(plug: str, cdata: Dict, clear: bool = True) -> None:
    """Write a captured animation curve onto ``plug`` (``node.attr``).

    The reusable primitive behind AnimationComponent.apply - exposed so a curve
    captured on one node can be retargeted onto a *different* plug (e.g. baking
    a joint's animation onto a control). ``cdata`` is one attr's dict from a
    captured ``animation`` slice (``keys`` + ``weighted`` / ``pre`` / ``post``).

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
    """Merge a captured ``animation`` slice's role dicts into ``{attr: cdata}``.

    A capture splits curves by role (``transform`` / ``shape`` / ``node``);
    retargeting onto another node usually wants them flat, keyed by attribute.
    """
    flat: Dict[str, Dict] = {}
    for attrs in anim_data.values():
        flat.update(attrs)
    return flat


class AnimationComponent(PresetComponent):
    """Capture / restore keyframe animation on a node's attributes.

    Extends the historical value-only snapshot (``{attr: [(time, value)]}``,
    see presetSaver/dw_maps) to a full curve round-trip: per key it also stores
    in/out tangent types, angles and weights, plus the curve's weighted-tangent
    flag and pre/post infinity - so the rebuilt curve matches shape, not just
    values.

    Opt-in (``enabled_by_default = False``): include it with
    ``createPreset(only=[..., "animation"])``. Values are split by role
    (``transform`` / ``shape`` / ``node``) like AttributeComponent. Blend is not
    applied to curves - animation is restored wholesale.
    """

    key = "animation"
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


# ---------------------------------------------------------------------------
# Rebuild dispatch
# ---------------------------------------------------------------------------

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
    cls = resolve_type(node_type)

    target = ctx.resolve_name(identity)
    if cmds.objExists(target):
        node = cls(target)
    else:
        # Documented "create new node" path: MayaNode(name, node_type). Building
        # the node here (rather than wrapping a missing name then poking .node)
        # avoids the accessors that assume an existing node, and suppresses the
        # "does not exist" warning the bare-name ctor would log.
        node = cls(target, node_type)
    ctx.name_map[identity] = node.node

    node.applyPreset({"nodes": {identity: body}}, ctx)
    return node


def load_preset_file(path: str,
                     target_ns: str = ":",
                     create: bool = True) -> List["Any"]:
    """Rebuild every node in a saved preset file. Returns the wrapped nodes."""
    data = dw_json.load_json(path)
    if not data or data.get("format") != PRESET_FORMAT:
        logger.warning(f"load_preset_file: '{path}' is not a {PRESET_FORMAT} file.")
        return []
    ctx = PresetContext(target_ns=target_ns, create=create)
    return [node_from_preset(identity, body, ctx)
            for identity, body in data.get("nodes", {}).items()]