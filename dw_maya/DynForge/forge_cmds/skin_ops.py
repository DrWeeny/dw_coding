"""
forge_cmds/skin_ops.py - DynForge skinning helpers.

Register a skinCluster, find what a chain hangs from (influences around its
_PIN, radius = distance to the nearest skin joint), decide who takes what when
several chains share a donor bone (compute_split), preview that split as vertex
colours, back up / restore the vanilla skin and install every chain of a
skinCluster at once.

A "gizmo" is optional: a plain poly primitive used purely as a clip volume on a
chain's region (e.g. to keep a belt out of it):
    box      polyCube  1x1x1            -> local half-extent 0.5
    sphere   polySphere r=1             -> local radius 1
    capsule  polyCylinder r=1 h=2 cap   -> radius 1, body y in [-1, 1]
The artist moves / rotates / scales it; point-in-volume tests run in the
gizmo's local space (via its world-inverse matrix), so scale is respected.
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Optional

import maya.cmds as cmds
import maya.api.OpenMaya as om2
import maya.api.OpenMayaAnim as oma2

from dw_logger import get_logger
from dw_maya.dw_decorators import dw_undo

logger = get_logger()

GIZMO_TAG = "dwForgeGizmo"
BACKUP_ATTR = "dwForgeBackup"   # JSON weight backup stored on the skinCluster
CHAIN_TAG = "dwForge"            # string attr (= guide name) on every DynForge chain joint
_SHAPES = ("box", "sphere", "capsule")
_SETTING_ATTRS = ("maxInfluences", "maintainMaxInfluences",
                  "normalizeWeights", "skinningMethod")


# ----------------------------------------------------------------------------
# skinCluster discovery
# ----------------------------------------------------------------------------

def find_skin_cluster(mesh: str) -> Optional[str]:
    """Return the skinCluster deforming `mesh` (via history), or None."""
    if not cmds.objExists(mesh):
        return None
    for node in cmds.listHistory(mesh, pruneDagObjects=True) or []:
        if cmds.nodeType(node) == "skinCluster":
            return node
    return None


def skin_cluster_meshes(skin: str) -> list:
    """Return the mesh transforms deformed by `skin`."""
    meshes = []
    for shape in cmds.skinCluster(skin, query=True, geometry=True) or []:
        if cmds.nodeType(shape) == "mesh":
            parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
            meshes.append(parents[0] if parents else shape)
    return meshes


def selected_mesh() -> Optional[str]:
    """First polygon mesh transform in the active selection, or None."""
    for node in cmds.ls(selection=True, long=True) or []:
        base = node.split(".")[0]
        if cmds.nodeType(base) == "mesh":
            parents = cmds.listRelatives(base, parent=True, fullPath=True) or []
            return parents[0] if parents else base
        if cmds.listRelatives(base, shapes=True, type="mesh", fullPath=True):
            return base
    return None


# ----------------------------------------------------------------------------
# Gizmo (optional clip volume)
# ----------------------------------------------------------------------------
#
# Local volumes: box = unit cube (half-extent 0.5), sphere = radius 1, capsule =
# radius 1 around the local Y segment [-h, h]. h is stored on the capsule
# (GIZMO_HALF, default 1) so a fitted capsule keeps round caps: its length is
# baked in the geometry + h, its thickness is a uniform scale - scaling Y would
# stretch the caps and the point test runs in local space.

GIZMO_HALF = "dwForgeHalfLength"   # capsule half-length in local units


def create_gizmo(shape:       str = "box",
                 center:      Optional[str] = None,
                 name:        str = "dwForge_gizmo",
                 half_length: float = 1.0,) -> str:
    """Create a region gizmo of `shape` (unit size), centered on `center` if given."""
    shape = shape.lower()
    if shape == "sphere":
        node = cmds.polySphere(radius=1, constructionHistory=False, name=name)[0]
    elif shape == "capsule":
        node = cmds.polyCylinder(radius=1, height=2 * half_length, roundCap=True,
                                 subdivisionsCaps=4, constructionHistory=False, name=name)[0]
        cmds.addAttr(node, longName=GIZMO_HALF, attributeType="double")
        cmds.setAttr(f"{node}.{GIZMO_HALF}", half_length)
    else:
        node = cmds.polyCube(width=1, height=1, depth=1,
                             constructionHistory=False, name=name)[0]

    if not cmds.attributeQuery(GIZMO_TAG, node=node, exists=True):
        cmds.addAttr(node, longName=GIZMO_TAG, dataType="string")
    cmds.setAttr(f"{node}.{GIZMO_TAG}", shape, type="string")

    if center and cmds.objExists(center):
        pos = cmds.xform(center, query=True, worldSpace=True, translation=True)
        cmds.xform(node, worldSpace=True, translation=pos)

    cmds.select(clear=True)
    return node


def gizmo_half_length(gizmo: str) -> float:
    """Capsule half-length in local units (1 for gizmos made before it was stored)."""
    if cmds.attributeQuery(GIZMO_HALF, node=gizmo, exists=True):
        return float(cmds.getAttr(f"{gizmo}.{GIZMO_HALF}"))
    return 1.0


def _point_in_shape(p:     om2.MPoint,
                    shape: str,
                    half:  float = 1.0,) -> bool:
    """Point-in-volume test in the gizmo's local space."""
    if shape == "sphere":
        return (p.x * p.x + p.y * p.y + p.z * p.z) <= 1.0
    if shape == "capsule":
        cy = max(-half, min(half, p.y))   # nearest point on the local Y axis segment
        dx, dy, dz = p.x, p.y - cy, p.z
        return (dx * dx + dy * dy + dz * dz) <= 1.0
    return abs(p.x) <= 0.5 and abs(p.y) <= 0.5 and abs(p.z) <= 0.5   # box


def vertices_in_gizmo(mesh:  str,
                      gizmo: str,
                      shape: str,) -> list:
    """Return the indices of `mesh` vertices that fall inside `gizmo`."""
    world_inv = _shape_dag(gizmo).inclusiveMatrixInverse()
    mesh_dag = _shape_dag(mesh)
    mesh_dag.extendToShape()
    points = om2.MFnMesh(mesh_dag).getPoints(om2.MSpace.kWorld)
    shape, half = shape.lower(), gizmo_half_length(gizmo)
    return [i for i, p in enumerate(points) if _point_in_shape(p * world_inv, shape, half)]


def _curve_samples(curve: str,
                   count: int = 64,) -> list:
    """`count` world points evenly spread by arc length along `curve`."""
    dag = _shape_dag(curve)
    dag.extendToShape()
    fn = om2.MFnNurbsCurve(dag)
    length = fn.length()
    if length < 1e-9:
        return [fn.cvPosition(0, om2.MSpace.kWorld)]
    return [fn.getPointAtParam(fn.findParamFromLength(min(length * i / (count - 1), length * (1 - 1e-7))),
                               om2.MSpace.kWorld)
            for i in range(count)]


def fit_gizmo(shape:  str,
              curve:  str,
              radius: float,
              name:   str = "dwForge_gizmo",) -> str:
    """
    Create a gizmo containing the whole chain: along root -> tip of `curve`,
    `radius` (the reach) plus how far the curve bows away from the root -> tip
    line, so a curved cable stays inside. Starts clipping nothing - the artist
    only moves / shrinks it to cut something out (e.g. a belt).
    """
    pts = _curve_samples(curve)
    root, tip = pts[0], pts[-1]
    axis = om2.MVector(tip - root)
    length = axis.length()
    axis_n = axis.normal() if length > 1e-6 else om2.MVector(0.0, 1.0, 0.0)
    mid = root + axis * 0.5

    def off_axis(p: om2.MPoint) -> float:
        rel = om2.MVector(p - root)
        along = max(0.0, min(length, rel * axis_n))
        return (rel - axis_n * along).length()

    thick = max(radius, 1e-3) + max(off_axis(p) for p in pts)
    rotation = om2.MQuaternion(om2.MVector(0.0, 1.0, 0.0), axis_n).asEulerRotation()
    degrees = [math.degrees(a) for a in (rotation.x, rotation.y, rotation.z)]

    shape = shape.lower()
    if shape == "sphere":
        reach = max(radius, 1e-3) + max(om2.MVector(p - mid).length() for p in pts)
        node = create_gizmo("sphere", name=name)
        cmds.xform(node, worldSpace=True, translation=(mid.x, mid.y, mid.z))
        cmds.setAttr(f"{node}.scale", reach, reach, reach)
        _remember_fit_scale(node)
        return node
    if shape == "capsule":
        node = create_gizmo("capsule", name=name, half_length=max((length / 2.0) / thick, 1e-3))
        cmds.setAttr(f"{node}.scale", thick, thick, thick)
    else:
        node = create_gizmo("box", name=name)
        cmds.setAttr(f"{node}.scale", 2 * thick, length + 2 * thick, 2 * thick)
    cmds.xform(node, worldSpace=True, rotation=degrees)
    cmds.xform(node, worldSpace=True, translation=(mid.x, mid.y, mid.z))
    _remember_fit_scale(node)
    return node


GIZMO_FIT_SCALE = "dwForgeFitScale"   # the gizmo's X scale when it was fitted: 100% size


def _remember_fit_scale(gizmo: str) -> None:
    if not cmds.attributeQuery(GIZMO_FIT_SCALE, node=gizmo, exists=True):
        cmds.addAttr(gizmo, longName=GIZMO_FIT_SCALE, attributeType="double")
    cmds.setAttr(f"{gizmo}.{GIZMO_FIT_SCALE}", max(abs(cmds.getAttr(f"{gizmo}.scaleX")), 1e-6))


def gizmo_size_factor(gizmo: str) -> float:
    """Current size relative to the fitted one (1.0 = as fitted), read on X."""
    if not cmds.attributeQuery(GIZMO_FIT_SCALE, node=gizmo, exists=True):
        _remember_fit_scale(gizmo)   # older gizmo: its current size becomes the reference
    fit = cmds.getAttr(f"{gizmo}.{GIZMO_FIT_SCALE}") or 1.0
    return abs(cmds.getAttr(f"{gizmo}.scaleX")) / fit


def set_gizmo_size_factor(gizmo:  str,
                          factor: float,) -> None:
    """
    Scale the gizmo to `factor` x its fitted size, around its centre (the
    primitives are built centred on their pivot). All three axes are
    multiplied by the same ratio, so a non-uniform scale set in the viewport
    keeps its proportions and a capsule stays round.
    """
    current = gizmo_size_factor(gizmo)
    if current <= 1e-9:
        return
    ratio = factor / current
    sx, sy, sz = cmds.getAttr(f"{gizmo}.scale")[0]
    cmds.setAttr(f"{gizmo}.scale", sx * ratio, sy * ratio, sz * ratio)


def clip_coverage(gizmo: str,
                  shape: str,
                  curve: str,) -> float:
    """Fraction (0..1) of the chain's curve inside its clip gizmo - below 1 the chain loses its own verts."""
    inv = _shape_dag(gizmo).inclusiveMatrixInverse()
    half = gizmo_half_length(gizmo)
    pts = _curve_samples(curve)
    return sum(1 for p in pts if _point_in_shape(p * inv, shape.lower(), half)) / float(len(pts))


# ----------------------------------------------------------------------------
# Reach + attachment (no gizmo needed)
# ----------------------------------------------------------------------------

def _short(name: str) -> str:
    """
    The name influences are matched by: last path element WITHOUT namespace.
    A studio pipeline namespaces what it puts in its containers on save / load
    (BB_M_0_Hips placed by the artist comes back as _SKL_X_:BB_M_0_Hips), so a
    name stored before the save - a donor, a backup's influence list - only
    matches the live skin namespace-free. Two influences of one skinCluster
    sharing a bare name in different namespaces would collide; not seen in
    production, and the alternative breaks every reopened scene.
    """
    return name.split("|")[-1].split(":")[-1]


def _strip_path(path: str) -> str:
    """A DAG path with every element's namespace removed."""
    return "|".join(part.split(":")[-1] for part in path.split("|"))


def resolve_node(stored: str) -> Optional[str]:
    """
    The long path a stored node name designates NOW, or None when it is gone or
    ambiguous. The stored name is used as is when it still exists; otherwise
    the node is found by its bare name in any namespace and, among several,
    the one whose path matches once namespaces are stripped (the pipeline's
    save / load adds namespaces, it does not move nodes). Never guesses
    between two equally good candidates.
    """
    if not stored:
        return None
    if cmds.objExists(stored):
        found = cmds.ls(stored, long=True) or []
        if len(found) == 1:
            return found[0]
    candidates = cmds.ls(_short(stored), long=True, recursive=True) or []
    if len(candidates) == 1:
        return candidates[0]
    wanted = _strip_path(stored)
    if stored.startswith("|"):
        exact = [c for c in candidates if _strip_path(c) == wanted]
    else:
        exact = [c for c in candidates if _strip_path(c).endswith(f"|{wanted}") or _strip_path(c) == wanted]
    return exact[0] if len(exact) == 1 else None


def _world_pos(node: str) -> om2.MPoint:
    return om2.MPoint(*cmds.xform(node, query=True, worldSpace=True, translation=True))


def nearest_influence(skin:    str,
                      node:    str,
                      exclude: tuple = (),) -> tuple:
    """
    Return (influence, distance) of the skinCluster influence nearest to `node`
    (typically a chain's _PIN), skipping DynForge chain joints (tagged 'dwForge')
    and anything in `exclude`. Influences sitting on the node (distance ~0) are
    skipped too, so a _PIN snapped onto a bone still gets a usable radius.
    Returns (None, 0.0) when nothing qualifies.
    """
    center = _world_pos(node)
    skip = {_short(n) for n in exclude}
    best, best_d = None, 0.0
    for infl in cmds.skinCluster(skin, query=True, influence=True) or []:
        if _short(infl) in skip or cmds.attributeQuery(CHAIN_TAG, node=infl, exists=True):
            continue
        dist = (_world_pos(infl) - center).length()
        if dist > 1e-4 and (best is None or dist < best_d):
            best, best_d = infl, dist
    return best, best_d


def _skin_fn(skin: str) -> oma2.MFnSkinCluster:
    sel = om2.MSelectionList()
    sel.add(skin)
    return oma2.MFnSkinCluster(sel.getDependNode(0))


def _shape_dag(shape: str) -> om2.MDagPath:
    sel = om2.MSelectionList()
    sel.add(shape)
    return sel.getDagPath(0)


def _mesh_shapes(skin: str) -> list:
    """The mesh shapes the skinCluster deforms (names as the skinCluster reports them)."""
    return [s for s in cmds.skinCluster(skin, query=True, geometry=True) or []
            if cmds.nodeType(s) == "mesh"]


def _long(node: str) -> str:
    return (cmds.ls(node, long=True) or [node])[0]


# ----------------------------------------------------------------------------
# Vertex mask: the verts a chain is allowed to take weight on
# ----------------------------------------------------------------------------
#
# Stored per guide as {mesh transform: [[first, last], ...]} - ranges, so a mask
# over thousands of verts stays a few lines in the recipe JSON.

def to_ranges(vids) -> list:
    """[0, 1, 2, 5, 7, 8] -> [[0, 2], [5, 5], [7, 8]] (sorted, deduplicated)."""
    ranges = []
    for vid in sorted(set(int(v) for v in vids)):
        if ranges and vid == ranges[-1][1] + 1:
            ranges[-1][1] = vid
        else:
            ranges.append([vid, vid])
    return ranges


def from_ranges(ranges) -> set:
    """[[0, 2], [5, 5]] -> {0, 1, 2, 5}."""
    out = set()
    for first, last in ranges or []:
        out.update(range(int(first), int(last) + 1))
    return out


def selected_vertices() -> dict:
    """
    The selection as vertices, {mesh transform (long): set(vids)} - faces /
    edges / objects converted to their vertices.
    """
    selection = cmds.ls(selection=True, long=True) or []
    if not selection:
        return {}
    verts = cmds.ls(cmds.polyListComponentConversion(selection, toVertex=True) or [], flatten=True, long=True)
    out: dict = {}
    for vert in verts:
        node, _, index = vert.partition(".vtx[")
        if not index:
            continue
        if cmds.nodeType(node) == "mesh":
            node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
        out.setdefault(_long(node), set()).add(int(index.rstrip("]")))
    return out


def _mask_by_shape(mask: Optional[dict]) -> Optional[dict]:
    """A spec's {mesh transform: vids} as {mesh shape (long): set(vids)}, None when there is no mask."""
    if not mask:
        return None
    out = {}
    for mesh, vids in mask.items():
        if not cmds.objExists(mesh):
            logger.warning(f"DynForge mask: {mesh!r} is gone, its part of the mask is ignored.")
            continue
        shapes = cmds.listRelatives(mesh, shapes=True, noIntermediate=True, type="mesh", fullPath=True) \
            or ([_long(mesh)] if cmds.nodeType(mesh) == "mesh" else [])
        for shape in shapes:
            out[_long(shape)] = set(vids)
    return out


def is_chain_joint(node: str) -> bool:
    """A DynForge chain joint (any guide's): never a donor, never an attachment candidate."""
    return bool(node) and cmds.objExists(node) and cmds.attributeQuery(CHAIN_TAG, node=node, exists=True)


def _rows_for(skin:  str,
              shape: str,
              vids:  list,
              layer: Optional[dict] = None,) -> tuple:
    """
    (influence names, {vid: [weight per influence]}) for `vids` of `shape`: the
    live skin, minus the DynForge `layer` when given - the skin as the other
    departments left it, which is what an installed chain is analysed and
    previewed against.
    """
    skin_fn = _skin_fn(skin)
    names = [d.partialPathName() for d in skin_fn.influenceObjects()]
    comp_fn = om2.MFnSingleIndexedComponent()
    comp = comp_fn.create(om2.MFn.kMeshVertComponent)
    comp_fn.addElements(vids)
    weights, n_inf = skin_fn.getWeights(_shape_dag(shape), comp)
    rows = {v: list(weights[k * n_inf:(k + 1) * n_inf]) for k, v in enumerate(vids)}
    deltas = _layer_rows(layer, shape)
    if deltas:
        col = {_short(n): j for j, n in enumerate(names)}
        for vid, row in rows.items():
            for infl, delta in (deltas.get(vid) or {}).items():
                j = col.get(infl)
                if j is not None:
                    row[j] = max(0.0, row[j] - delta)
    return names, rows


def attachment_candidates(skin:        str,
                          node:        str,
                          radius:      float,
                          curve:       Optional[str] = None,
                          from_base:   bool = True,) -> list:
    """
    Rank the skinCluster influences by participation (% of total weight) over
    the skin around the chain: within `radius` of `curve` (the whole chain - a
    strip running down a leg hangs from every bone under it, not only the one at
    its root) or, without a curve, of `node` (the _PIN). Each vertex counts with
    the tube's cosine falloff, so the skin right on the chain decides and the
    edge of the region barely weighs. Returns [(influence, pct)] high -> low,
    every influence of the skin included (0 when it has no weight in reach).

    Reads the skin WITHOUT the DynForge layer (`from_base`): once a chain is
    installed, the live weights near it are the chain's own, and the bones it
    hangs from have already given them away. DynForge chain joints are never
    listed - a chain taking from another chain (or from itself) is not an
    attachment.
    """
    layer = load_layer(skin) if from_base else None
    if curve and cmds.objExists(curve):
        field = _ChainField({"name": "", "curve": curve, "radius": radius, "donors": []})

        def near_of(point):
            hit = field.claim(point)
            return hit[0] if hit else 0.0
    else:
        center = _world_pos(node)

        def near_of(point):
            return _tube_falloff((point - center).length(), radius)

    totals: dict = {}
    for shape in _mesh_shapes(skin):
        points = om2.MFnMesh(_shape_dag(shape)).getPoints(om2.MSpace.kWorld)
        near = [(i, near_of(p)) for i, p in enumerate(points)]
        near = [(i, f) for i, f in near if f > 0.0]
        if not near:
            continue
        names, rows = _rows_for(skin, shape, [i for i, _ in near], layer)
        for vid, falloff in near:
            for name, weight in zip(names, rows[vid]):
                if weight > 0.0:
                    totals[name] = totals.get(name, 0.0) + weight * falloff
    # Every influence is listed, the ones with no weight in reach at 0%: seeing a
    # bone at 0 tells the artist it exists and the radius is what leaves it out
    # (raise the scale, analyse again). Keyed by short name, so a backup name and
    # the live one of the same joint merge.
    by_short = {}
    for name in cmds.skinCluster(skin, query=True, influence=True) or []:
        by_short[_short(name)] = [name, 0.0]
    for name, total in totals.items():
        # The live name wins: a backup taken before a pipeline reload names the
        # bone without the namespace it has now.
        entry = by_short.setdefault(_short(name), [name, 0.0])
        entry[1] += total
    entries = [(name, total) for name, total in by_short.values() if not is_chain_joint(name)]
    grand = sum(total for _, total in entries) or 1.0
    ranked = [(name, 100.0 * total / grand if total > 1e-9 else 0.0) for name, total in entries]
    ranked.sort(key=lambda item: (-item[1], _short(item[0]).lower()))
    return ranked


# ----------------------------------------------------------------------------
# Inspect
# ----------------------------------------------------------------------------

def inspect_influence(mesh:      str,
                      influence: str,) -> None:
    """
    Open the Paint Skin Weights tool on `mesh` and try to focus `influence` so
    the artist can see its current painting. Best-effort: if focusing the
    influence fails, the tool is still opened.
    """
    from maya import mel
    cmds.select(mesh, replace=True)
    try:
        mel.eval("ArtPaintSkinWeightsTool;")
        mel.eval(f'artSkinSelectInfluence("artAttrSkinPaintCtx", "{influence}");')
    except Exception as e:
        logger.warning(f"DynForge: could not focus influence {influence!r}: {e}")


# ----------------------------------------------------------------------------
# Backup / restore (JSON in a string attr on the skinCluster)
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# DynForge layer: what the installs moved, removable without touching the rest
# ----------------------------------------------------------------------------
#
# The skin is edited by several departments (rigging adds bones, modeling
# changes the mesh, someone repaints): a snapshot of the "original" restored
# before each install would undo all of that. So DynForge records only ITS
# edit - per touched vertex, the signed weight change per influence (donors
# negative, chain joints positive) - and removing DynForge from a skin is
# subtracting that layer from whatever the skin is now. Reinstall = remove the
# layer, compute the split on what is left, record the new layer.
#
# Stored as a JSON string attr on the setup top group of the guides (in a
# studio, the group inside the part's metadata container - it survives the
# pipeline's save / reload, a skinCluster's custom attr does not) keyed by the
# skinCluster's bare name, plus a JSON copy per part in the project's preset
# dir (latest + timestamped history).

LAYER_ATTR = "dwForgeSkinLayers"   # on a setup group: {skin bare name: layer}
LAYER_FORMAT = "dw_forge_skin_layer"
LAYER_VERSION = 1


def _skin_key(skin: str) -> str:
    return _short(skin)


def _setup_groups() -> list:
    from dw_maya.DynForge import forge_host
    return [g for g in forge_host.get_host().list_setups() if cmds.objExists(g)]


def _read_layers(group: str) -> dict:
    if not cmds.attributeQuery(LAYER_ATTR, node=group, exists=True):
        return {}
    try:
        return json.loads(cmds.getAttr(f"{group}.{LAYER_ATTR}") or "{}")
    except ValueError:
        logger.warning(f"DynForge: unreadable skin layers on {group!r}, ignored.")
        return {}


def _write_layers(group: str,
                  layers: dict,) -> None:
    if not cmds.attributeQuery(LAYER_ATTR, node=group, exists=True):
        cmds.addAttr(group, longName=LAYER_ATTR, dataType="string")
    cmds.setAttr(f"{group}.{LAYER_ATTR}", json.dumps(layers), type="string")


def layer_dir(part: str) -> str:
    """The per-part folder of the JSON copies (dw_pipe_project preset dir, category 'dynforge')."""
    import dw_pipe_project
    return dw_pipe_project.get_project().get_preset_dir(part or "unassigned", category="dynforge")


def load_layer(skin: str,
               part: str = "",) -> Optional[dict]:
    """
    The DynForge layer recorded for `skin`, or None: from a setup group in the
    scene, else from the part's JSON copy (when the scene lost it).
    """
    key = _skin_key(skin)
    for group in _setup_groups():
        layer = _read_layers(group).get(key)
        if layer:
            return layer
    if part:
        path = os.path.join(layer_dir(part), f"skin_layer_{key}.json")
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    layer = json.load(handle)
            except (OSError, ValueError) as e:
                logger.warning(f"DynForge: unreadable layer copy {path}: {e}")
                return None
            if layer.get("shapes") and _copy_matches_skin(skin, layer):
                logger.info(f"DynForge: layer of {key} read from its JSON copy {path}")
                return layer
    return None


def _copy_matches_skin(skin:  str,
                       layer: dict,) -> bool:
    """
    Whether a layer read from the part's JSON copy describes THIS skin's DynForge
    weight. The copy is per part, the scene may not be the one that wrote it (an
    older version opened, the part fresh in another character): subtracting a
    layer from a skin that never received it pumps weight back into the donors.
    So it is used only when the skin carries chain weight no scene layer records,
    and the chain joints the copy gave weight to are exactly those.
    """
    carrying = set(chain_weighted_influences(skin))
    if not carrying:
        return False
    received = {infl for rows in layer["shapes"].values() for row in rows.values()
                for infl, delta in row.items() if delta > 1e-9}
    given = set()
    for infl in received:   # the layer stores bare names: find the node to read its tag
        nodes = cmds.ls(infl, recursive=True) or []
        if nodes and is_chain_joint(nodes[0]):
            given.add(infl)
    if given != carrying:
        logger.warning(f"DynForge: the JSON copy of {_skin_key(skin)}'s layer does not match the skin's chain weights "
                       f"(copy: {sorted(given)}, skin: {sorted(carrying)}) - not used.")
        return False
    return True


def save_layer(skin:   str,
               layer:  Optional[dict],
               home:   str,
               part:   str = "",) -> None:
    """
    Store `layer` (None = no DynForge weight left on the skin) on the setup
    group `home`, drop any other copy of it in the scene (one truth per skin),
    and write the part's JSON copy + a timestamped history entry.
    """
    key = _skin_key(skin)
    for group in _setup_groups():
        layers = _read_layers(group)
        if key in layers and group != home:
            del layers[key]
            _write_layers(group, layers)
    if home and cmds.objExists(home):
        layers = _read_layers(home)
        if layer:
            layers[key] = layer
        else:
            layers.pop(key, None)
        _write_layers(home, layers)
    if part:
        try:
            folder = layer_dir(part)
            os.makedirs(os.path.join(folder, "history"), exist_ok=True)
            payload = json.dumps(layer or {"format": LAYER_FORMAT, "version": LAYER_VERSION, "skin": key,
                                           "chains": [], "shapes": {}}, indent=1)
            with open(os.path.join(folder, f"skin_layer_{key}.json"), "w", encoding="utf-8") as handle:
                handle.write(payload)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            with open(os.path.join(folder, "history", f"skin_layer_{key}_{stamp}.json"), "w",
                      encoding="utf-8") as handle:
                handle.write(payload)
        except OSError as e:
            logger.warning(f"DynForge: could not write the layer copy of {key}: {e}")


def _shape_by_key(skin: str) -> dict:
    return {_short(shape): shape for shape in _mesh_shapes(skin)}


def _layer_rows(layer: Optional[dict],
                shape: str,) -> dict:
    """{vid: {influence bare: delta}} of `shape` in a layer (empty without one)."""
    if not layer:
        return {}
    return {int(v): d for v, d in (layer.get("shapes", {}).get(_short(shape)) or {}).items()}


def remove_layer(skin:  str,
                 layer: dict,) -> dict:
    """
    Subtract a DynForge layer from the skin as it is NOW: the chain joints give
    back what they took, to the donors they took it from; every other weight,
    influence and bone stays as the other departments left it. Where someone
    edited a touched vertex since (a chain joint no longer holds what the layer
    says, a donor bone is gone, the vertex no longer exists), the row is
    clamped, renormalised and reported. Returns {"verts", "conflicts": [str]}.
    """
    skin_fn = _skin_fn(skin)
    names = [_short(d.partialPathName()) for d in skin_fn.influenceObjects()]
    col = {n: j for j, n in enumerate(names)}
    n_inf = len(names)
    physical = om2.MIntArray(list(range(n_inf)))
    shapes = _shape_by_key(skin)
    report = {"verts": 0, "conflicts": []}
    for shape_key, rows in (layer.get("shapes") or {}).items():
        shape = shapes.get(shape_key)
        if shape is None:
            report["conflicts"].append(f"{shape_key}: mesh no longer deformed by {_short(skin)}")
            continue
        count = om2.MFnMesh(_shape_dag(shape)).numVertices
        vids = sorted(int(v) for v in rows if int(v) < count)
        if len(vids) < len(rows):
            report["conflicts"].append(f"{shape_key}: {len(rows) - len(vids)} vert(s) no longer exist "
                                       f"(topology changed)")
        if not vids:
            continue
        comp_fn = om2.MFnSingleIndexedComponent()
        comp = comp_fn.create(om2.MFn.kMeshVertComponent)
        comp_fn.addElements(vids)
        dag = _shape_dag(shape)
        weights, _ = skin_fn.getWeights(dag, comp)
        for k, vid in enumerate(vids):
            base = k * n_inf
            clamped = False
            for infl, delta in rows[str(vid)].items():
                j = col.get(infl)
                if j is None:
                    report["conflicts"].append(f"{shape_key}.vtx[{vid}]: {infl} is no longer an influence")
                    clamped = True
                    continue
                value = weights[base + j] - delta
                if value < -1e-4:
                    report["conflicts"].append(f"{shape_key}.vtx[{vid}]: {infl} holds less than the layer moved "
                                               f"(edited since)")
                    clamped = True
                weights[base + j] = max(0.0, value)
            total = sum(weights[base + j] for j in range(n_inf))
            if clamped or abs(total - 1.0) > 1e-4:
                if total > 1e-9:
                    for j in range(n_inf):
                        weights[base + j] /= total
        skin_fn.setWeights(dag, comp, physical, weights, False)
        report["verts"] += len(vids)
    for line in report["conflicts"][:20]:
        logger.warning(f"DynForge remove layer {_short(skin)}: {line}")
    return report


def has_backup(skin: str) -> bool:
    """True if `skin` carries a DynForge weight backup."""
    return bool(cmds.attributeQuery(BACKUP_ATTR, node=skin, exists=True)) \
        and bool(cmds.getAttr(f"{skin}.{BACKUP_ATTR}"))


def _all_verts_component(shape: str):
    """Return (dagPath, component) covering every vertex of a mesh shape."""
    sel = om2.MSelectionList()
    sel.add(shape)
    dag = sel.getDagPath(0)
    n_verts = om2.MFnMesh(dag).numVertices
    comp_fn = om2.MFnSingleIndexedComponent()
    comp = comp_fn.create(om2.MFn.kMeshVertComponent)
    comp_fn.addElements(list(range(n_verts)))
    return dag, comp, n_verts


def _read_skin_data(skin: str) -> dict:
    """Read a full snapshot of the skinCluster: influences, settings, weights."""
    sel = om2.MSelectionList()
    sel.add(skin)
    skin_fn = oma2.MFnSkinCluster(sel.getDependNode(0))
    influences = [d.partialPathName() for d in skin_fn.influenceObjects()]

    settings = {}
    for attr in _SETTING_ATTRS:
        if cmds.attributeQuery(attr, node=skin, exists=True):
            settings[attr] = cmds.getAttr(f"{skin}.{attr}")

    geometry = {}
    for shape in cmds.skinCluster(skin, query=True, geometry=True) or []:
        if cmds.nodeType(shape) != "mesh":
            logger.warning(f"DynForge backup: skipping non-mesh geometry {shape!r}.")
            continue
        dag, comp, n_verts = _all_verts_component(shape)
        weights, _ = skin_fn.getWeights(dag, comp)
        geometry[shape] = {"vertexCount": n_verts, "weights": list(weights)}

    return {"skinCluster": skin,
            "influences": influences,
            "settings":   settings,
            "geometry":   geometry}



def chain_weighted_influences(skin: str) -> list:
    """Short names of the DynForge chain joints that carry weight on `skin` (empty on an original skin)."""
    skin_fn = _skin_fn(skin)
    names = [d.partialPathName() for d in skin_fn.influenceObjects()]
    chain_cols = [j for j, name in enumerate(names) if is_chain_joint(name)]
    if not chain_cols:
        return []
    totals = [0.0] * len(names)
    for shape in _mesh_shapes(skin):
        dag, comp, _ = _all_verts_component(shape)
        weights, n_inf = skin_fn.getWeights(dag, comp)
        for j in chain_cols:
            totals[j] += sum(weights[j::n_inf])
    return [_short(names[j]) for j in chain_cols if totals[j] > 1e-6]


def _weighted_chain_names(data: dict) -> list:
    """Short names of the DynForge chain joints holding weight in a backup snapshot (an original has none)."""
    names = data["influences"]
    n_inf = len(names)
    out = []
    for j, name in enumerate(names):
        nodes = cmds.ls(_short(name), recursive=True) or []
        if not (nodes and is_chain_joint(nodes[0])):
            continue
        if any(abs(geo["weights"][v * n_inf + j]) > 1e-6
               for geo in data["geometry"].values() for v in range(geo["vertexCount"])):
            out.append(_short(name))
    return out



def reserve_influences(skin:   str,
                       joints: list,) -> list:
    """
    Install without skin: make `joints` influences of `skin` at weight 0 and
    lock them, so the chain is already wired for skinning but takes nothing
    until a skin install (or a hand paint after unlocking). Idempotent.
    Returns the joints newly added.
    """
    existing = {_short(i) for i in cmds.skinCluster(skin, query=True, influence=True) or []}
    added = []
    for jnt in joints:
        if not cmds.objExists(jnt):
            continue
        if _short(jnt) not in existing:
            cmds.skinCluster(skin, edit=True, addInfluence=jnt, weight=0.0, lockWeights=True)
            existing.add(_short(jnt))
            added.append(jnt)
        cmds.setAttr(f"{jnt}.lockInfluenceWeights", True)
    return added


def influence_weight(skin:  str,
                     joint: str,) -> float:
    """Total weight `joint` carries over every vertex of `skin` (0 when it is not an influence)."""
    skin_fn = _skin_fn(skin)
    names = [_short(d.partialPathName()) for d in skin_fn.influenceObjects()]
    if _short(joint) not in names:
        return 0.0
    column = names.index(_short(joint))
    total = 0.0
    for shape in _mesh_shapes(skin):
        dag, comp, _ = _all_verts_component(shape)
        weights, n_inf = skin_fn.getWeights(dag, comp)
        total += sum(weights[column::n_inf])
    return total


def release_influences(skin:   str,
                       joints: list,) -> list:
    """
    Undo reserve_influences: remove `joints` from `skin`. Returns the ones that
    carried weight (painted by hand after an unlock) - removed all the same, Maya
    hands their weight back to the other influences - so the caller can say so.
    """
    existing = {_short(i) for i in cmds.skinCluster(skin, query=True, influence=True) or []}
    painted = []
    for jnt in joints:
        if not cmds.objExists(jnt) or _short(jnt) not in existing:
            continue
        if influence_weight(skin, jnt) > 1e-6:
            painted.append(jnt)
        cmds.setAttr(f"{jnt}.lockInfluenceWeights", False)
        cmds.skinCluster(skin, edit=True, removeInfluence=jnt)
    return painted


def restore_skin(skin: str) -> None:
    """
    Restore `skin` to its DynForge backup: remove influences added since (those
    not in the backup), then write back the stored weights and settings.
    """
    if not has_backup(skin):
        raise ValueError(f"No DynForge backup found on {skin!r}.")
    data = json.loads(cmds.getAttr(f"{skin}.{BACKUP_ATTR}"))
    chained = _weighted_chain_names(data)
    if chained:
        # Taken from a skin that already held the chains' weights (its real
        # original was lost - a pipeline reload drops the attribute - and an
        # older DynForge backed up what was left). Restoring it and installing
        # again would transfer onto the chains a second time.
        raise ValueError(
            f"The backup on {_short(skin)} is not the original skin: it already holds DynForge chain weights "
            f"({', '.join(chained[:4])}{'...' if len(chained) > 4 else ''}). Refusing to restore it - restore the "
            f"pre-DynForge skin first.")
    # Matched namespace-free (_short): a backup taken before a pipeline save /
    # reload names the bones without the namespace they come back with.
    backup_infl = {_short(name) for name in data["influences"]}

    # Drop influences that were added after the backup (e.g. chain joints).
    for infl in cmds.skinCluster(skin, query=True, influence=True) or []:
        if _short(infl) not in backup_infl:
            try:
                cmds.skinCluster(skin, edit=True, removeInfluence=infl)
            except Exception as e:
                logger.warning(f"DynForge restore: could not remove {infl!r}: {e}")

    sel = om2.MSelectionList()
    sel.add(skin)
    skin_fn = oma2.MFnSkinCluster(sel.getDependNode(0))

    # setWeights takes PHYSICAL indices (influenceObjects order), so the backup
    # columns are remapped onto the current influence order.
    current = [_short(d.partialPathName()) for d in skin_fn.influenceObjects()]
    col_of = {name: j for j, name in enumerate(current)}
    backup_names = [_short(name) for name in data["influences"]]
    missing = [n for n in backup_names if n not in col_of]
    if missing:
        raise ValueError(
            f"Cannot restore {skin!r}: backup influences missing from the scene: "
            f"{', '.join(missing)}")
    n_cur, n_bak = len(current), len(backup_names)
    physical = om2.MIntArray(list(range(n_cur)))
    same_order = backup_names == current

    for shape, geo in data["geometry"].items():
        if not cmds.objExists(shape):
            logger.warning(f"DynForge restore: geometry {shape!r} is gone, skipping.")
            continue
        dag, comp, n_verts = _all_verts_component(shape)
        if n_verts != geo["vertexCount"]:
            logger.warning(f"DynForge restore: {shape!r} vertex count changed "
                           f"({geo['vertexCount']} -> {n_verts}), skipping.")
            continue
        flat = geo["weights"]
        if same_order:
            weights = om2.MDoubleArray(flat)
        else:
            weights = om2.MDoubleArray(n_verts * n_cur, 0.0)
            cols = [col_of[name] for name in backup_names]
            for v in range(n_verts):
                src, dst = v * n_bak, v * n_cur
                for b, c in enumerate(cols):
                    weights[dst + c] = flat[src + b]
        skin_fn.setWeights(dag, comp, physical, weights, False)

    for attr, value in data.get("settings", {}).items():
        try:
            cmds.setAttr(f"{skin}.{attr}", value)
        except Exception:
            pass
    logger.info(f"DynForge: restored {skin!r} from backup.")


# ----------------------------------------------------------------------------
# Split: who takes what (shared by the preview and the install)
# ----------------------------------------------------------------------------
#
# A chain "spec" is a plain dict built by the guide (ChainJointGuide.skin_spec):
#     name, joints (root -> tip), curve, donors (influence names), radius,
#     power, gizmo (optional clip volume), gizmo_shape
#
# For every vertex near a chain, the chain's claim t = cosine falloff of the
# distance to its curve (1 on the curve, 0 at `radius`). For each donor bone of
# the vertex:
#   - the amount leaving the donor is weight x the strongest claim; the rest
#     stays on the donor, so the region blends back into the bone seamlessly;
#   - the chains taking from that donor share it by closeness, claim x
#     (1 / distance)^SPLIT_SHARPNESS: the radius only sets how far a chain
#     reaches, it does not decide between two chains (the nearest wins, 50/50
#     at the midline) - two cables a few units apart stay separate even with
#     tubes wide enough to cover both.
# Inside a chain the share cascades down its joints by the vertex's arc-length
# position.

def _cascade_falloff(frac:  float,
                     n:     int,
                     power: float,) -> list:
    """
    Weights (summing to 1) spreading a vertex's transferred weight across the n
    chain joints by its arc-length position `frac` (0=root .. 1=tip). Gaussian
    falloff; `power` scales its width (1 ~ one joint-spacing).
    """
    if n <= 1:
        return [1.0]
    spacing = 1.0 / (n - 1)
    sigma = max(power, 1e-3) * spacing
    weights = []
    for j in range(n):
        d = (frac - j / (n - 1)) / sigma
        weights.append(math.exp(-0.5 * d * d))
    total = sum(weights) or 1.0
    return [w / total for w in weights]


SPLIT_SHARPNESS = 4.0    # closeness exponent when chains share a donor (higher = crisper border)
CONTESTED_SHARE = 0.1    # a vertex is "contested" when 2+ chains each get at least this share of it


def _tube_falloff(dist:   float,
                  radius: float,) -> float:
    if radius <= 0.0 or dist >= radius:
        return 0.0
    return 0.5 * (1.0 + math.cos(math.pi * dist / radius))


class _ChainField(object):
    """Evaluates one chain spec's claim (t, arc-length frac) on world points."""

    def __init__(self,
                 spec: dict,) -> None:
        self.spec = spec
        self.donors = {_short(d) for d in spec["donors"]}
        dag = _shape_dag(spec["curve"])
        dag.extendToShape()
        self.curve_fn = om2.MFnNurbsCurve(dag)
        self.length = self.curve_fn.length() or 1.0
        radius = spec["radius"]
        box = om2.MBoundingBox()
        for cv in self.curve_fn.cvPositions(om2.MSpace.kWorld):
            box.expand(cv)
        self.box = om2.MBoundingBox(
            om2.MPoint(box.min.x - radius, box.min.y - radius, box.min.z - radius),
            om2.MPoint(box.max.x + radius, box.max.y + radius, box.max.z + radius))
        self.clip = None
        gizmo = spec.get("gizmo")
        if gizmo and cmds.objExists(gizmo):
            self.clip = (_shape_dag(gizmo).inclusiveMatrixInverse(), spec.get("gizmo_shape", "box").lower(),
                         gizmo_half_length(gizmo))
        # Vertex mask: {shape long: vids} - outside it the chain claims nothing,
        # on top of the gizmo clip. None = no mask.
        self.mask = _mask_by_shape(spec.get("mask"))

    def allows(self,
               shape_long: str,
               vid:        int,) -> bool:
        """False when the chain has a mask and this vertex is not in it."""
        if self.mask is None:
            return True
        return vid in self.mask.get(shape_long, ())

    def claim(self,
              point: om2.MPoint,):
        """Return (t, frac, distance to the curve) for a world point, or None outside the tube."""
        if not self.box.contains(point):
            return None
        if self.clip is not None and not _point_in_shape(point * self.clip[0], self.clip[1], self.clip[2]):
            return None
        closest, param = self.curve_fn.closestPoint(point, space=om2.MSpace.kWorld)
        dist = (closest - point).length()
        t = _tube_falloff(dist, self.spec["radius"])
        if t <= 0.0:
            return None
        frac = self.curve_fn.findLengthFromParam(param) / self.length
        return t, max(0.0, min(1.0, frac)), dist




def compute_split(skin:      str,
                  specs:     list,
                  from_base: bool = False,) -> tuple:
    """
    Decide who takes what on every mesh of `skin`.

    Returns (split, stats):
        split  {shape: {vid: [(chain index, donor, share, frac), ...]}}
        stats  [{"name", "verts", "contested", "taken"}] per spec - verts it
               takes weight on, verts where it shares a donor with another
               chain, and the total weight it takes.
    `from_base` reads donor weights from the skin minus its DynForge layer
    (preview of an already-installed skin); install reads the live skin, the
    layer having just been removed.
    """
    layer = load_layer(skin) if from_base else None
    fields = [_ChainField(spec) for spec in specs]
    all_donors = set().union(*(f.donors for f in fields)) if fields else set()
    stats = [{"name": spec["name"], "verts": 0, "contested": 0, "taken": 0.0} for spec in specs]
    split: dict = {}
    for shape in _mesh_shapes(skin):
        points = om2.MFnMesh(_shape_dag(shape)).getPoints(om2.MSpace.kWorld)
        shape_long = _long(shape)
        claims: dict = {}
        for vid, point in enumerate(points):
            found = []
            for ci, field in enumerate(fields):
                if not field.allows(shape_long, vid):
                    continue
                hit = field.claim(point)
                if hit is not None:
                    found.append((ci,) + hit)   # (ci, t, frac, dist)
            if found:
                claims[vid] = found
        if not claims:
            continue
        vids = sorted(claims)
        names, rows = _rows_for(skin, shape, vids, layer)
        cols = [(j, _short(n)) for j, n in enumerate(names) if _short(n) in all_donors]
        donor_w = {vid: {n: rows[vid][j] for j, n in cols} for vid in vids}

        per_vert: dict = {}
        for vid in vids:
            entries = []
            touched, shared = set(), set()
            for donor, weight in donor_w[vid].items():
                if weight <= 1e-9:
                    continue
                takers = [c for c in claims[vid] if donor in fields[c[0]].donors]
                if not takers:
                    continue
                # How much leaves the donor: the strongest claim (overlapping
                # tubes must not take more together than the closest one alone).
                taken = weight * max(t for _, t, _, _ in takers)
                # Who gets it: closeness wins - claim x (1 / distance)^SPLIT_SHARPNESS,
                # so a vertex on one chain is not shared with a chain a few units
                # away just because both tubes reach it; 50/50 at the midline.
                pulls = [t / max(dist, 1e-6) ** SPLIT_SHARPNESS for _, t, _, dist in takers]
                total_pull = sum(pulls)
                sharing = sum(1 for p in pulls if p / total_pull >= CONTESTED_SHARE)
                for (ci, _, frac, _), pull in zip(takers, pulls):
                    share = taken * pull / total_pull
                    if share <= 1e-9:
                        continue
                    entries.append((ci, donor, share, frac))
                    stats[ci]["taken"] += share
                    touched.add(ci)
                    if sharing > 1 and pull / total_pull >= CONTESTED_SHARE:
                        shared.add(ci)
            for ci in touched:
                stats[ci]["verts"] += 1
            for ci in shared:
                stats[ci]["contested"] += 1
            if entries:
                per_vert[vid] = entries
        if per_vert:
            split[shape] = per_vert
    return split, stats


# ----------------------------------------------------------------------------
# Install: apply the split for every chain of a skinCluster at once
# ----------------------------------------------------------------------------

def install_chains(skin:  str,
                   specs: list,) -> tuple:
    """
    Add every chain's joints as influences and move the donor weight onto them
    following compute_split(). Meant to run on the skin WITHOUT any DynForge
    weight (the caller strips the layer first) so the result never depends on
    install order. Returns (stats, deltas): the split stats, and the layer of
    this install - {shape bare: {vid: {influence bare: signed change}}}.
    """
    existing = {_short(i) for i in cmds.skinCluster(skin, query=True, influence=True) or []}
    for spec in specs:
        for jnt in spec["joints"]:
            # A chain reserved by an install without skin is locked: a skin
            # install hands it its weights, so it is paintable again afterwards.
            if cmds.attributeQuery("lockInfluenceWeights", node=jnt, exists=True):
                cmds.setAttr(f"{jnt}.lockInfluenceWeights", False)
            if _short(jnt) in existing:
                continue
            cmds.skinCluster(skin, edit=True, addInfluence=jnt, weight=0.0)
            existing.add(_short(jnt))

    split, stats = compute_split(skin, specs)

    skin_fn = _skin_fn(skin)
    infl_objs = skin_fn.influenceObjects()
    names = [_short(d.partialPathName()) for d in infl_objs]
    col = {n: j for j, n in enumerate(names)}
    n_inf = len(names)
    # setWeights wants PHYSICAL indices (influenceObjects order, = getWeights
    # columns), not logical ones: after a restore + re-add the logical indices
    # are sparse and passing them raises kInvalidParameter.
    physical = om2.MIntArray(list(range(n_inf)))
    chain_cols = [[col[_short(j)] for j in spec["joints"]] for spec in specs]

    deltas: dict = {}
    for shape, per_vert in split.items():
        vids = sorted(per_vert)
        comp_fn = om2.MFnSingleIndexedComponent()
        comp = comp_fn.create(om2.MFn.kMeshVertComponent)
        comp_fn.addElements(vids)
        dag = _shape_dag(shape)
        weights, _ = skin_fn.getWeights(dag, comp)
        before = list(weights)
        for k, vid in enumerate(vids):
            base = k * n_inf
            for ci, donor, share, frac in per_vert[vid]:
                weights[base + col[donor]] = max(0.0, weights[base + col[donor]] - share)
                cascade = _cascade_falloff(frac, len(chain_cols[ci]), specs[ci]["power"])
                for c, w in zip(chain_cols[ci], cascade):
                    weights[base + c] += share * w
        skin_fn.setWeights(dag, comp, physical, weights, False)
        # The layer: what this install changed, per vertex and influence.
        shape_rows = {}
        for k, vid in enumerate(vids):
            base = k * n_inf
            row = {names[j]: weights[base + j] - before[base + j] for j in range(n_inf)
                   if abs(weights[base + j] - before[base + j]) > 1e-9}
            if row:
                shape_rows[str(vid)] = row
        if shape_rows:
            deltas[_short(shape)] = shape_rows

    for entry in stats:
        logger.info(f"DynForge install {skin!r}: {entry['name']} takes weight on {entry['verts']} vert(s), "
                    f"{entry['contested']} contested.")
    return stats, deltas


def layer_home(guide) -> Optional[str]:
    """The setup group holding a guide's group - where the layer of its skin is stored."""
    try:
        parents = cmds.listRelatives(guide.guide_group(), parent=True, fullPath=True) or []
    except Exception:
        return None
    return parents[0] if parents else None


def _part_of(guide) -> str:
    """The install unit label of a guide (its part / prop in a studio) - where its layer copy is filed."""
    from dw_maya.DynForge import forge_host
    try:
        return forge_host.get_host().install_unit(guide)[1]
    except Exception:
        return ""


def strip_dynforge(skin:        str,
                   keep_joints: tuple = (),
                   part:        str = "",) -> Optional[dict]:
    """
    Take every DynForge weight off `skin` and leave the rest as it is now:
    subtract its layer (see remove_layer), then remove the chain joints that
    are not in `keep_joints` from the influences. A skin installed before the
    layer existed is migrated once: its old snapshot backup is restored when it
    has a usable one. A skin carrying chain weight recorded nowhere is refused
    before anything changes. Returns the removal report (None without a layer).
    """
    layer = load_layer(skin, part)
    report = None
    if layer:
        report = remove_layer(skin, layer)
    elif has_backup(skin):
        restore_skin(skin)   # legacy snapshot (raises when it is not an original)
    else:
        carrying = chain_weighted_influences(skin)
        if carrying:
            raise ValueError(
                f"{_short(skin)} carries DynForge chain weights ({', '.join(carrying[:4])}"
                f"{'...' if len(carrying) > 4 else ''}) that no layer records - installed before the layer "
                f"existed and its backup was lost (a pipeline save / reload drops it). Nothing was changed.")
    keep = {_short(j) for j in keep_joints}
    for infl in cmds.skinCluster(skin, query=True, influence=True) or []:
        if is_chain_joint(infl) and _short(infl) not in keep:
            cmds.setAttr(f"{infl}.lockInfluenceWeights", False)
            cmds.skinCluster(skin, edit=True, removeInfluence=infl)
    return report


@dw_undo.singleUndoChunk
def install_skin(skin:     str,
                 guides:   list,
                 reserved: tuple = (),) -> list:
    """
    Install `guides` (objects with skin_spec() / install_pin()) on `skin`, one
    undo step: take the current DynForge layer off (strip_dynforge - the other
    departments' edits stay), apply every chain at once, place each _PIN not
    yet in the rig (an installed one only gets its weights redone) and record
    the new layer on the guides' setup group + the part's JSON copy. Chains of
    `skin` left out of `guides` end up uninstalled - except the `reserved`
    guides (installed without skin), whose joints are put back at weight 0,
    locked.
    """
    clear_preview()
    part = _part_of(guides[0]) if guides else ""
    keep = [j for g in tuple(guides) + tuple(reserved) for j in g.chain_joints]
    strip_dynforge(skin, keep_joints=keep, part=part)
    # Placed BEFORE the transfer: the host renames the joints as it installs
    # them, and the layer must record the names they keep, not the build ones.
    for guide in guides:
        guide.skin_installed = True   # set before install_pin, which stores the recipe
        if getattr(guide, "installed", False):
            # Already in the rig (a peer re-applied after a restore, or a guide
            # installed without skin first): only its weights are redone - placing
            # it again would re-run the host install on a chain that is in place.
            guide.store_recipe()
        else:
            guide.install_pin()
    stats, deltas = install_chains(skin, [guide.skin_spec() for guide in guides])
    for guide in reserved:
        reserve_influences(skin, guide.chain_joints)
    layer = {"format": LAYER_FORMAT, "version": LAYER_VERSION, "skin": _skin_key(skin),
             "chains": [guide.name for guide in guides], "time": time.strftime("%Y-%m-%d %H:%M:%S"),
             "shapes": deltas}
    save_layer(skin, layer, layer_home(guides[0]) if guides else None, part)
    if has_backup(skin):
        cmds.deleteAttr(f"{skin}.{BACKUP_ATTR}")   # migrated: the layer is the record now
    return stats


# ----------------------------------------------------------------------------
# Preview: vertex-colour copy of the meshes showing the split
# ----------------------------------------------------------------------------

PREVIEW_GRP    = "dwForgePreview_GRP"
PREVIEW_HIDE   = "dwForgeHidden"   # JSON list of the originals hidden by the preview
PREVIEW_COLORS = ((0.95, 0.45, 0.15), (0.20, 0.60, 0.95), (0.35, 0.80, 0.35),
                  (0.85, 0.30, 0.75), (0.95, 0.85, 0.20), (0.25, 0.85, 0.85))
_DONOR_GREY    = (0.35, 0.35, 0.35)


def clear_preview() -> None:
    """Delete the split preview and show the meshes it hid."""
    if not cmds.objExists(PREVIEW_GRP):
        return
    hidden = []
    if cmds.attributeQuery(PREVIEW_HIDE, node=PREVIEW_GRP, exists=True):
        hidden = json.loads(cmds.getAttr(f"{PREVIEW_GRP}.{PREVIEW_HIDE}") or "[]")
    for node in hidden:
        try:
            cmds.setAttr(f"{node}.visibility", True)
        except Exception as e:
            logger.warning(f"DynForge preview: could not show {node!r} again: {e}")
    cmds.delete(PREVIEW_GRP)


def preview_split(skin:  str,
                  specs: list,) -> list:
    """
    Show who takes what: duplicate every mesh of `skin` under PREVIEW_GRP and
    colour it - each chain has its colour (PREVIEW_COLORS, spec order), mixed
    hues are contested, grey is what the donors keep / untouched weight. The
    originals are hidden (and shown again by clear_preview) so nothing is
    written on the production meshes. Reads the vanilla backup when there is
    one, so an installed skin previews the same split. Returns the stats.
    """
    clear_preview()
    split, stats = compute_split(skin, specs, from_base=True)
    group = cmds.group(empty=True, name=PREVIEW_GRP)
    hidden = []
    for shape in _mesh_shapes(skin):
        transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
        copy = cmds.duplicate(transform, name=f"{_short(transform).split(':')[-1]}_dwForgePreview")[0]
        copy = cmds.ls(cmds.parent(copy, group)[0], long=True)[0]
        keep = None
        for child in cmds.listRelatives(copy, children=True, fullPath=True) or []:
            is_live_mesh = (cmds.nodeType(child) == "mesh"
                            and not cmds.getAttr(f"{child}.intermediateObject"))
            if is_live_mesh and keep is None:
                keep = child
            else:
                cmds.delete(child)
        fn = om2.MFnMesh(_shape_dag(keep))
        n_verts = fn.numVertices
        colors = om2.MColorArray(n_verts, om2.MColor(_DONOR_GREY))
        for vid, entries in split.get(shape, {}).items():
            taken = [0.0] * len(specs)
            for ci, _, share, _ in entries:
                taken[ci] += share
            rest = max(0.0, 1.0 - sum(taken))
            rgb = [_DONOR_GREY[i] * rest for i in range(3)]
            for ci, amount in enumerate(taken):
                color = PREVIEW_COLORS[ci % len(PREVIEW_COLORS)]
                for i in range(3):
                    rgb[i] += color[i] * amount
            colors[vid] = om2.MColor(rgb)
        fn.setVertexColors(colors, om2.MIntArray(list(range(n_verts))))
        cmds.setAttr(f"{keep}.displayColors", True)
        try:
            if cmds.getAttr(f"{transform}.visibility"):
                cmds.setAttr(f"{transform}.visibility", False)
                hidden.append(transform)
        except Exception as e:
            logger.warning(f"DynForge preview: could not hide {transform!r}: {e}")
    cmds.addAttr(group, longName=PREVIEW_HIDE, dataType="string")
    cmds.setAttr(f"{group}.{PREVIEW_HIDE}", json.dumps(hidden), type="string")
    cmds.select(clear=True)
    return stats
