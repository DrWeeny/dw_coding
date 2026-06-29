"""
forge_cmds/skin_ops.py - DynForge skinning helpers (phase 1: read-only).

Everything the Skinning tab needs to register a skinCluster, drop a region
gizmo and rank the current influences by participation inside it. No weights
are written here - the transfer happens later, on Install.

A "gizmo" is a plain poly primitive transform used purely as a volume:
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
# Gizmo
# ----------------------------------------------------------------------------

def create_gizmo(shape:  str = "box",
                 center: Optional[str] = None,
                 name:   str = "dwForge_gizmo",) -> str:
    """Create a region gizmo of `shape`, centered on `center` if given."""
    shape = shape.lower()
    if shape == "sphere":
        node = cmds.polySphere(radius=1, constructionHistory=False, name=name)[0]
    elif shape == "capsule":
        node = cmds.polyCylinder(radius=1, height=2, roundCap=True,
                                 constructionHistory=False, name=name)[0]
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


def _point_in_shape(p:     om2.MPoint,
                    shape: str,) -> bool:
    """Point-in-volume test in the gizmo's local space."""
    if shape == "sphere":
        return (p.x * p.x + p.y * p.y + p.z * p.z) <= 1.0
    if shape == "capsule":
        cy = max(-1.0, min(1.0, p.y))   # nearest point on the local Y axis segment
        dx, dy, dz = p.x, p.y - cy, p.z
        return (dx * dx + dy * dy + dz * dz) <= 1.0
    return abs(p.x) <= 0.5 and abs(p.y) <= 0.5 and abs(p.z) <= 0.5   # box


def vertices_in_gizmo(mesh:  str,
                      gizmo: str,
                      shape: str,) -> list:
    """Return the indices of `mesh` vertices that fall inside `gizmo`."""
    sel = om2.MSelectionList()
    sel.add(gizmo)
    world_inv = sel.getDagPath(0).inclusiveMatrixInverse()

    sel2 = om2.MSelectionList()
    sel2.add(mesh)
    mesh_dag = sel2.getDagPath(0)
    mesh_dag.extendToShape()
    points = om2.MFnMesh(mesh_dag).getPoints(om2.MSpace.kWorld)

    shape = shape.lower()
    return [i for i, p in enumerate(points)
            if _point_in_shape(p * world_inv, shape)]


# ----------------------------------------------------------------------------
# Participation
# ----------------------------------------------------------------------------

def _influence_totals(skin:     str,
                      mesh:     str,
                      vert_ids: list,):
    """Return (per-influence summed weight over vert_ids, influence names)."""
    sel = om2.MSelectionList()
    sel.add(skin)
    skin_fn = oma2.MFnSkinCluster(sel.getDependNode(0))

    sel2 = om2.MSelectionList()
    sel2.add(mesh)
    mesh_dag = sel2.getDagPath(0)
    mesh_dag.extendToShape()

    comp_fn = om2.MFnSingleIndexedComponent()
    comp = comp_fn.create(om2.MFn.kMeshVertComponent)
    comp_fn.addElements(vert_ids)

    weights, n_inf = skin_fn.getWeights(mesh_dag, comp)
    names = [d.partialPathName() for d in skin_fn.influenceObjects()]

    totals = [0.0] * n_inf
    for v in range(len(vert_ids)):
        base = v * n_inf
        for j in range(n_inf):
            totals[j] += weights[base + j]
    return totals, names


def analyze_participation(skin:   str,
                          meshes: list,
                          gizmo:  str,
                          shape:  str,) -> list:
    """
    Rank the skinCluster influences by their participation (% of total weight)
    over every vertex of `meshes` inside `gizmo`. Returns [(influence, pct)]
    sorted high -> low, dropping zero contributors.
    """
    totals: dict = {}
    grand = 0.0
    for mesh in meshes:
        if not cmds.objExists(mesh):
            continue
        vert_ids = vertices_in_gizmo(mesh, gizmo, shape)
        if not vert_ids:
            continue
        infl_totals, names = _influence_totals(skin, mesh, vert_ids)
        for name, total in zip(names, infl_totals):
            totals[name] = totals.get(name, 0.0) + total
            grand += total

    grand = grand or 1.0
    ranked = [(name, 100.0 * total / grand)
              for name, total in totals.items() if total > 1e-9]
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

    name_to_index = {d.partialPathName(): skin_fn.indexForInfluenceObject(d)
                     for d in skin_fn.influenceObjects()}
    missing = [n for n in data["influences"] if n not in name_to_index]
    if missing:
        raise ValueError(
            f"Cannot restore {skin!r}: backup influences missing from the scene: "
            f"{', '.join(missing)}")

    infl_indices = om2.MIntArray()
    for name in data["influences"]:
        infl_indices.append(name_to_index[name])

    for shape, geo in data["geometry"].items():
        if not cmds.objExists(shape):
            logger.warning(f"DynForge restore: geometry {shape!r} is gone, skipping.")
            continue
        dag, comp, n_verts = _all_verts_component(shape)
        if n_verts != geo["vertexCount"]:
            logger.warning(f"DynForge restore: {shape!r} vertex count changed "
                           f"({geo['vertexCount']} -> {n_verts}), skipping.")
            continue
        skin_fn.setWeights(dag, comp, infl_indices,
                           om2.MDoubleArray(geo["weights"]), False)

    for attr, value in data.get("settings", {}).items():
        try:
            cmds.setAttr(f"{skin}.{attr}", value)
        except Exception:
            pass
    logger.info(f"DynForge: restored {skin!r} from backup.")


# ----------------------------------------------------------------------------
# Install: transfer donor weight onto the chain with a spatial cascade
# ----------------------------------------------------------------------------

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


def install_chain(skin:             str,
                  meshes:           list,
                  gizmo:            str,
                  gizmo_shape:      str,
                  curve:            str,
                  chain_joints:     list,
                  donor_influences: list,
                  power:            float = 1.0,) -> int:
    """
    Add `chain_joints` as influences and, for every mesh vertex inside `gizmo`,
    move the donor influences' weight onto the chain, distributed down the chain
    by the vertex's projection on `curve` (spatial cascade). Donor weight in the
    region goes to 0; totals stay normalized. Returns the number of verts edited.
    """
    # 1. Add the chain joints as influences (weight 0) if not already present.
    existing = set(cmds.skinCluster(skin, query=True, influence=True) or [])
    existing_short = {i.split("|")[-1] for i in existing}
    for jnt in chain_joints:
        if jnt in existing or jnt.split("|")[-1] in existing_short:
            continue
        try:
            cmds.skinCluster(skin, edit=True, addInfluence=jnt, weight=0.0)
        except Exception as e:
            logger.warning(f"DynForge install: addInfluence {jnt!r} failed: {e}")

    # 2. Influence ordering (getWeights column order == influenceObjects order).
    sel = om2.MSelectionList()
    sel.add(skin)
    skin_fn = oma2.MFnSkinCluster(sel.getDependNode(0))
    infl_objs = skin_fn.influenceObjects()
    names = [d.partialPathName() for d in infl_objs]
    short_names = [n.split("|")[-1] for n in names]
    logical = om2.MIntArray([skin_fn.indexForInfluenceObject(d) for d in infl_objs])
    n_inf = len(infl_objs)

    def col_of(node: str) -> int:
        if node in names:
            return names.index(node)
        short = node.split("|")[-1]
        return short_names.index(short) if short in short_names else -1

    donor_cols = [c for c in (col_of(d) for d in donor_influences) if c >= 0]
    chain_cols = [col_of(j) for j in chain_joints]   # root -> tip order
    if not donor_cols or any(c < 0 for c in chain_cols):
        raise ValueError("Install: could not map donor / chain influences on the skinCluster.")

    # 3. Curve for the arc-length projection.
    csel = om2.MSelectionList()
    csel.add(curve)
    cdag = csel.getDagPath(0)
    cdag.extendToShape()
    curve_fn = om2.MFnNurbsCurve(cdag)
    total_len = curve_fn.length()
    if total_len < 1e-6:
        raise ValueError("Install: source curve has zero length.")
    n_chain = len(chain_cols)

    # 4. Transfer, per mesh.
    edited = 0
    for mesh in meshes:
        if not cmds.objExists(mesh):
            continue
        region = vertices_in_gizmo(mesh, gizmo, gizmo_shape)
        if not region:
            continue
        msel = om2.MSelectionList()
        msel.add(mesh)
        mdag = msel.getDagPath(0)
        mdag.extendToShape()
        points = om2.MFnMesh(mdag).getPoints(om2.MSpace.kWorld)

        comp_fn = om2.MFnSingleIndexedComponent()
        comp = comp_fn.create(om2.MFn.kMeshVertComponent)
        comp_fn.addElements(region)
        weights, _ = skin_fn.getWeights(mdag, comp)

        for k, vid in enumerate(region):
            base = k * n_inf
            donor_w = sum(weights[base + c] for c in donor_cols)
            if donor_w <= 1e-9:
                continue
            try:
                _, param = curve_fn.closestPoint(points[vid], space=om2.MSpace.kWorld)
                frac = curve_fn.findLengthFromParam(param) / total_len
            except Exception:
                frac = 0.0
            frac = max(0.0, min(1.0, frac))
            falloff = _cascade_falloff(frac, n_chain, power)
            for c in donor_cols:
                weights[base + c] = 0.0
            for idx, c in enumerate(chain_cols):
                weights[base + c] += donor_w * falloff[idx]
            edited += 1

        skin_fn.setWeights(mdag, comp, logical, weights, False)

    logger.info(f"DynForge: installed chain on {skin!r} - {edited} vert(s) transferred.")
    return edited