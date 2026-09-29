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
from typing import Optional

import maya.cmds as cmds
import maya.api.OpenMaya as om2
import maya.api.OpenMayaAnim as oma2

from dw_logger import get_logger
from dw_maya.dw_decorators import dw_undo

logger = get_logger()

GIZMO_TAG = "dwForgeGizmo"
BACKUP_ATTR = "dwForgeBackup"   # JSON weight backup stored on the skinCluster
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
        return node
    if shape == "capsule":
        node = create_gizmo("capsule", name=name, half_length=max((length / 2.0) / thick, 1e-3))
        cmds.setAttr(f"{node}.scale", thick, thick, thick)
    else:
        node = create_gizmo("box", name=name)
        cmds.setAttr(f"{node}.scale", 2 * thick, length + 2 * thick, 2 * thick)
    cmds.xform(node, worldSpace=True, rotation=degrees)
    cmds.xform(node, worldSpace=True, translation=(mid.x, mid.y, mid.z))
    return node


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
    return name.split("|")[-1]


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
        if _short(infl) in skip or cmds.attributeQuery("dwForge", node=infl, exists=True):
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


def attachment_candidates(skin:   str,
                          node:   str,
                          radius: float,) -> list:
    """
    Rank the skinCluster influences by participation (% of total weight) over
    the vertices within `radius` of `node` (the _PIN): the bone(s) the chain most
    likely hangs from. Each vertex counts with the same cosine falloff as the
    chain tube (1 at the _PIN, 0 at `radius`), so the skin right at the _PIN
    decides and the far edge of the sphere - often already the next bone's
    territory - barely weighs. Returns [(influence, pct)] high -> low.
    """
    center = _world_pos(node)
    skin_fn = _skin_fn(skin)
    names = [d.partialPathName() for d in skin_fn.influenceObjects()]
    totals = [0.0] * len(names)
    for shape in _mesh_shapes(skin):
        dag = _shape_dag(shape)
        points = om2.MFnMesh(dag).getPoints(om2.MSpace.kWorld)
        near = [(i, _tube_falloff((p - center).length(), radius)) for i, p in enumerate(points)]
        near = [(i, f) for i, f in near if f > 0.0]
        if not near:
            continue
        vids = [i for i, _ in near]
        comp_fn = om2.MFnSingleIndexedComponent()
        comp = comp_fn.create(om2.MFn.kMeshVertComponent)
        comp_fn.addElements(vids)
        weights, n_inf = skin_fn.getWeights(dag, comp)
        for k, (_, falloff) in enumerate(near):
            base = k * n_inf
            for j in range(n_inf):
                totals[j] += weights[base + j] * falloff
    grand = sum(totals) or 1.0
    ranked = [(name, 100.0 * total / grand) for name, total in zip(names, totals) if total > 1e-9]
    ranked.sort(key=lambda item: item[1], reverse=True)
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


def backup_skin(skin:  str,
                force: bool = False,) -> bool:
    """
    Store the current weights of `skin` as JSON on its dwForgeBackup attr. Does
    not overwrite an existing backup unless force=True (so the vanilla state is
    preserved across re-installs). Returns True if a backup was written.
    """
    if has_backup(skin) and not force:
        return False
    payload = json.dumps(_read_skin_data(skin))
    if not cmds.attributeQuery(BACKUP_ATTR, node=skin, exists=True):
        cmds.addAttr(skin, longName=BACKUP_ATTR, dataType="string")
    cmds.setAttr(f"{skin}.{BACKUP_ATTR}", payload, type="string")
    logger.info(f"DynForge: backed up {skin!r} "
                f"({len(_read_skin_data(skin)['geometry'])} mesh).")
    return True


def restore_skin(skin: str) -> None:
    """
    Restore `skin` to its DynForge backup: remove influences added since (those
    not in the backup), then write back the stored weights and settings.
    """
    if not has_backup(skin):
        raise ValueError(f"No DynForge backup found on {skin!r}.")
    data = json.loads(cmds.getAttr(f"{skin}.{BACKUP_ATTR}"))
    backup_infl = set(data["influences"])

    # Drop influences that were added after the backup (e.g. chain joints).
    for infl in cmds.skinCluster(skin, query=True, influence=True) or []:
        if infl not in backup_infl and infl.split("|")[-1] not in backup_infl:
            try:
                cmds.skinCluster(skin, edit=True, removeInfluence=infl)
            except Exception as e:
                logger.warning(f"DynForge restore: could not remove {infl!r}: {e}")

    sel = om2.MSelectionList()
    sel.add(skin)
    skin_fn = oma2.MFnSkinCluster(sel.getDependNode(0))

    # setWeights takes PHYSICAL indices (influenceObjects order), so the backup
    # columns are remapped onto the current influence order.
    current = [d.partialPathName() for d in skin_fn.influenceObjects()]
    col_of = {name: j for j, name in enumerate(current)}
    backup_names = data["influences"]
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


def _live_donor_weights(skin:   str,
                        shape:  str,
                        vids:   list,
                        donors: set,) -> dict:
    """{vid: {donor short name: weight}} read from the live skinCluster."""
    skin_fn = _skin_fn(skin)
    names = [_short(d.partialPathName()) for d in skin_fn.influenceObjects()]
    cols = [(j, n) for j, n in enumerate(names) if n in donors]
    comp_fn = om2.MFnSingleIndexedComponent()
    comp = comp_fn.create(om2.MFn.kMeshVertComponent)
    comp_fn.addElements(vids)
    weights, n_inf = skin_fn.getWeights(_shape_dag(shape), comp)
    return {vid: {n: weights[k * n_inf + j] for j, n in cols} for k, vid in enumerate(vids)}


def _backup_donor_weights(skin:   str,
                          shape:  str,
                          vids:   list,
                          donors: set,) -> Optional[dict]:
    """Same as _live_donor_weights, read from the DynForge backup (None if unusable)."""
    if not has_backup(skin):
        return None
    data = json.loads(cmds.getAttr(f"{skin}.{BACKUP_ATTR}"))
    geo = data["geometry"].get(shape)
    if geo is None:
        return None
    names = [_short(n) for n in data["influences"]]
    n_inf = len(names)
    cols = [(j, n) for j, n in enumerate(names) if n in donors]
    flat = geo["weights"]
    return {vid: {n: flat[vid * n_inf + j] for j, n in cols} for vid in vids}


def compute_split(skin:        str,
                  specs:       list,
                  from_backup: bool = False,) -> tuple:
    """
    Decide who takes what on every mesh of `skin`.

    Returns (split, stats):
        split  {shape: {vid: [(chain index, donor, share, frac), ...]}}
        stats  [{"name", "verts", "contested", "taken"}] per spec - verts it
               takes weight on, verts where it shares a donor with another
               chain, and the total weight it takes.
    `from_backup` reads donor weights from the vanilla backup (preview of an
    already-installed skin); install reads the live, freshly restored skin.
    """
    fields = [_ChainField(spec) for spec in specs]
    all_donors = set().union(*(f.donors for f in fields)) if fields else set()
    stats = [{"name": spec["name"], "verts": 0, "contested": 0, "taken": 0.0} for spec in specs]
    split: dict = {}
    for shape in _mesh_shapes(skin):
        points = om2.MFnMesh(_shape_dag(shape)).getPoints(om2.MSpace.kWorld)
        claims: dict = {}
        for vid, point in enumerate(points):
            found = []
            for ci, field in enumerate(fields):
                hit = field.claim(point)
                if hit is not None:
                    found.append((ci,) + hit)   # (ci, t, frac, dist)
            if found:
                claims[vid] = found
        if not claims:
            continue
        vids = sorted(claims)
        donor_w = None
        if from_backup:
            donor_w = _backup_donor_weights(skin, shape, vids, all_donors)
        if donor_w is None:
            donor_w = _live_donor_weights(skin, shape, vids, all_donors)

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
                   specs: list,) -> list:
    """
    Add every chain's joints as influences and move the donor weight onto them
    following compute_split(). Meant to run on the vanilla skin (the caller
    restores the backup first) so the result never depends on install order.
    Returns the split stats.
    """
    existing = {_short(i) for i in cmds.skinCluster(skin, query=True, influence=True) or []}
    for spec in specs:
        for jnt in spec["joints"]:
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

    for shape, per_vert in split.items():
        vids = sorted(per_vert)
        comp_fn = om2.MFnSingleIndexedComponent()
        comp = comp_fn.create(om2.MFn.kMeshVertComponent)
        comp_fn.addElements(vids)
        dag = _shape_dag(shape)
        weights, _ = skin_fn.getWeights(dag, comp)
        for k, vid in enumerate(vids):
            base = k * n_inf
            for ci, donor, share, frac in per_vert[vid]:
                weights[base + col[donor]] = max(0.0, weights[base + col[donor]] - share)
                cascade = _cascade_falloff(frac, len(chain_cols[ci]), specs[ci]["power"])
                for c, w in zip(chain_cols[ci], cascade):
                    weights[base + c] += share * w
        skin_fn.setWeights(dag, comp, physical, weights, False)

    for entry in stats:
        logger.info(f"DynForge install {skin!r}: {entry['name']} takes weight on {entry['verts']} vert(s), "
                    f"{entry['contested']} contested.")
    return stats


@dw_undo.singleUndoChunk
def install_skin(skin:   str,
                 guides: list,) -> list:
    """
    Install `guides` (objects with skin_spec() / install_pin()) on `skin`: back
    it up on the first install, otherwise restore that vanilla backup, then
    apply every chain at once and place each _PIN. One undo step. Chains of
    `skin` left out of `guides` end up uninstalled (the restore removes them).
    """
    clear_preview()
    if has_backup(skin):
        restore_skin(skin)
    else:
        backup_skin(skin)
    stats = install_chains(skin, [guide.skin_spec() for guide in guides])
    for guide in guides:
        guide.skin_installed = True   # set before install_pin, which stores the recipe
        guide.install_pin()
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
    split, stats = compute_split(skin, specs, from_backup=True)
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
