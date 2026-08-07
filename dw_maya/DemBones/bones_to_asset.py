"""
bones_to_asset.py - send a solve's joints back to the asset, in asset space.

Summary:
    DemBones inverts the usual pipeline. Normally it is
    ``model -> rig -> anim -> sim``; with a solve it becomes
    ``model -> sim -> DemBones -> rig -> anim``. So the joints are born in the
    space the SIMULATION lived in, and rigging needs them in ASSET space
    (usually the origin, usually a T/A-pose for a character).

    The difference between those two spaces is rarely a clean rigid move. Users
    relax or otherwise preprocess the mesh before caching, and a character's
    first simulated frame is an animated pose, not the bind pose. So this module
    classifies the difference first and picks a method to match, rather than
    assuming one and silently approximating.

Regimes (``classify``):
    ``rigid``    - same topology, difference is a pure rigid move. Exact: one
                   matrix for every joint.
    ``topology`` - same topology, non-rigid difference (relaxed, or posed). Each
                   joint is re-anchored to the SAME triangle it sat over,
                   identified by vertex index.
    ``uv``       - vertex counts differ. The triangle can only be found through
                   the UV parametrisation. Least reliable, and the only option
                   when point order is gone.

    Every regime produces the same thing - a world matrix per joint - so the
    joint building, binding and animation steps downstream do not branch.

The bind:
    Fresh joints are created in asset space and the asset mesh is bound to them,
    so ``bindPreMatrix`` is re-derived at the asset pose rather than carried
    over. Carrying the solve's bind is only valid when the difference is rigid;
    across a non-rigid one it reproduces the old deformation and the joints look
    right while the mesh is wrong.

The animation:
    ``relink`` - parent each joint under an offset group and connect the solved
                 curves verbatim. No resampling, exact under a rigid difference.
    ``bake``   - write ``B * inverse(A) * A(t)`` per frame: each joint's motion
                 in its OWN rest frame, re-applied at its new rest. The right
                 semantics once the joints have moved non-rigidly relative to
                 each other, and unreachable by parenting (a parent multiplies
                 on the right).

Functions:
    classify, solve_placements, create_asset_joints, bind_asset_mesh,
    copy_solved_weights, link_animation, bones_to_asset

Example::

    import dw_maya.DemBones.bones_to_asset as b2a

    info = b2a.classify("sim_mesh", "asset_mesh")
    print(info["regime"], info["detail"])

    result = b2a.bones_to_asset("sim_mesh", "asset_mesh",
                                anim_mode="auto",
                                joint_prefix="assetBone")

TODO:
    - Frame-sampled verification that the rigid offset is constant over time.
    - One-ring averaged tangent frames (currently per-triangle).

Author: DrWeeny
"""

import maya.cmds as cmds
import maya.api.OpenMaya as om

from typing import Dict, List, Optional, Tuple

import dw_maya.DemBones.dem_cmds as dem_cmds
from dw_logger import get_logger

logger = get_logger()


REGIMES = ("rigid", "topology", "uv")
ANIM_MODES = ("auto", "relink", "bake", "none")

_CHANNELS = ("translateX", "translateY", "translateZ",
             "rotateX", "rotateY", "rotateZ")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(source_mesh: str,
             target_mesh: str,
             tolerance: float = 0.001,
             ) -> Dict:
    """Decide which correspondence the two meshes actually support.

    Cheap, and run first on purpose: when it comes back ``rigid`` every later
    step collapses to a single matrix and there is nothing left to reason
    about. When it does not, the answer says why.

    Args:
        source_mesh: The mesh the solve was run against (simulation space).
        target_mesh: The asset mesh, in asset space.
        tolerance:   Rigid-fit tolerance, as a fraction of the sample spread.

    Returns:
        Dict with ``regime`` (one of :data:`REGIMES`), ``matrix`` (flat 16
        floats for the rigid regime, else None), ``source_count``,
        ``target_count`` and a human ``detail`` string.
    """
    n_src = dem_cmds.mesh_vertex_count(source_mesh) or 0
    n_tgt = dem_cmds.mesh_vertex_count(target_mesh) or 0

    if not n_src or not n_tgt:
        return {"regime": "uv", "matrix": None,
                "source_count": n_src, "target_count": n_tgt,
                "detail": "Could not read a vertex count from one of the meshes."}

    if n_src != n_tgt:
        return {"regime": "uv", "matrix": None,
                "source_count": n_src, "target_count": n_tgt,
                "detail": (f"Vertex counts differ ({n_src} vs {n_tgt}) - point "
                           f"order is gone, falling back to the UV "
                           f"parametrisation.")}

    matrix = dem_cmds.rigid_transform_between(source_mesh, target_mesh,
                                              tolerance=tolerance)
    if matrix is not None:
        return {"regime": "rigid", "matrix": matrix,
                "source_count": n_src, "target_count": n_tgt,
                "detail": "Same topology, difference is a pure rigid move."}

    return {"regime": "topology", "matrix": None,
            "source_count": n_src, "target_count": n_tgt,
            "detail": ("Same topology, non-rigid difference (relaxed or posed) "
                       "- joints re-anchored per triangle by vertex index.")}


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def source_max_influences(skin_node: str, mesh: str) -> int:
    """Highest number of non-zero influences on any vertex of ``skin_node``."""
    import dw_maya.dw_deformers.SkinMatch.skin_match_cmds as smc

    influences, _, weights = smc.dw_skinning.get_influence_weights(skin_node,
                                                                   mesh)
    n = len(influences)
    if not n:
        return 0
    best = 0
    for base in range(0, len(weights), n):
        count = sum(1 for w in weights[base:base + n] if w > 1e-6)
        best = max(best, count)
    return best


def preflight(source_mesh: str,
              target_mesh: str,
              max_influences: int = 8,
              ) -> List[Dict]:
    """Every precondition that silently ruins this transfer, checked up front.

    Returned as data rather than logged, so a UI can show each one with its
    reason. Each entry is ``{status, label, detail, tip}`` where status is
    ``ok`` / ``warn`` / ``fail``. A single ``fail`` means the build cannot run;
    ``warn`` means it will run and you should know what you are getting.
    """
    checks: List[Dict] = []

    def add(status, label, detail, tip=""):
        checks.append({"status": status, "label": label,
                       "detail": detail, "tip": tip})

    # -- source skinCluster ------------------------------------------------
    src_skin = dem_cmds.find_skin_cluster(source_mesh) if source_mesh else None
    if not src_skin:
        add("fail", "Source skinCluster", "none found on the solved mesh",
            "The solve's weights are the input. Without a skinCluster there "
            "is nothing to send back.")
        return checks

    joints = cmds.skinCluster(src_skin, query=True, influence=True) or []
    add("ok", "Source skinCluster", f"{src_skin} - {len(joints)} influences")

    # -- current frame -----------------------------------------------------
    now = cmds.currentTime(query=True)
    start = cmds.playbackOptions(query=True, minTime=True)
    if abs(now - start) > 1e-6:
        add("warn", "Current frame",
            f"at {now:g}, range starts at {start:g}",
            "Joint placement is measured at the CURRENT frame. If the solved "
            "joints are posed rather than at their rest, every placement is "
            "computed from the wrong positions. Go to the rest frame first.")
    else:
        add("ok", "Current frame", f"{now:g} (range start)")

    # -- vertex counts / regime -------------------------------------------
    n_src = dem_cmds.mesh_vertex_count(source_mesh) or 0
    n_tgt = dem_cmds.mesh_vertex_count(target_mesh) or 0
    if n_src and n_src == n_tgt:
        add("ok", "Vertex counts", f"{n_src} == {n_tgt}",
            "Matching counts mean point order survives, so joints can be "
            "re-anchored by vertex index - no UV lookup needed.")
    else:
        add("warn", "Vertex counts", f"{n_src} vs {n_tgt} - UV regime",
            "Point order is gone, so the correspondence has to go through the "
            "UV parametrisation. Least reliable of the three regimes: UV "
            "seams, mirrored shells and non-uniform UV scale all distort it.")

    # -- rigid fit ---------------------------------------------------------
    if n_src and n_src == n_tgt:
        matrix = dem_cmds.rigid_transform_between(source_mesh, target_mesh)
        if matrix is not None:
            add("ok", "Rigid match", "the two meshes differ by a pure move",
                "The lucky case: one matrix places every joint exactly, and "
                "the animation can be relinked without baking.")
        else:
            add("warn", "Rigid match", "not rigid - relaxed or posed",
                "Normal, not an error. The mesh was preprocessed before "
                "caching, or a character's first frame is an animated pose. "
                "Joints are re-anchored per triangle instead, and the "
                "animation is baked rather than relinked.")

    # -- target already skinned -------------------------------------------
    tgt_skin = dem_cmds.find_skin_cluster(target_mesh) if target_mesh else None
    if tgt_skin:
        add("warn", "Asset already skinned", f"{tgt_skin} present",
            "Binding again would stack a second skinCluster on the mesh. "
            "Enable 'Replace existing skinCluster' or delete it first.")
    else:
        add("ok", "Asset already skinned", "no existing skinCluster")

    # -- influence budget --------------------------------------------------
    try:
        used = source_max_influences(src_skin, source_mesh)
    except Exception as e:
        used = 0
        logger.warning(f"Could not measure the source influence budget: {e}")
    if used and used > max_influences:
        add("warn", "Influence budget",
            f"source uses up to {used}, binding at {max_influences}",
            "A cap narrower than the incoming data prunes it on arrival. "
            "Match maximumInfluences to the solve's nnz.")
    elif used:
        add("ok", "Influence budget",
            f"source uses up to {used}, binding at {max_influences}")

    # -- asset bind space --------------------------------------------------
    if target_mesh:
        shape = dem_cmds.bind_space_shape(target_mesh)
        visible = dem_cmds.mesh_shape(target_mesh) if hasattr(
            dem_cmds, "mesh_shape") else None
        if shape and visible and shape != visible:
            add("warn", "Asset bind space",
                "asset is deformed - measuring its intermediate shape",
                "A rigged asset displays in the set while the geometry a fresh "
                "bind consumes is still in modelling space. Placement is "
                "measured on what the viewport shows, so an already-rigged "
                "asset may place joints in the wrong space.")

    return checks


# ---------------------------------------------------------------------------
# Surface frames
# ---------------------------------------------------------------------------

def _mesh_fn(mesh: str) -> om.MFnMesh:
    """MFnMesh for a mesh transform or shape."""
    sel = om.MSelectionList()
    sel.add(mesh)
    dag = sel.getDagPath(0)
    dag.extendToShape()
    return om.MFnMesh(dag)


def _frame_from_triangle(p0: om.MPoint,
                         p1: om.MPoint,
                         p2: om.MPoint,
                         bary: Tuple[float, float, float],
                         ) -> Optional[om.MMatrix]:
    """Orthonormal frame at a barycentric point of a triangle.

    Built identically on both meshes, so whatever bias the construction has
    cancels between encode and decode. Returns None for a degenerate triangle,
    which must be skipped rather than approximated.
    """
    edge1 = om.MVector(p1 - p0)
    edge2 = om.MVector(p2 - p0)
    normal = edge1 ^ edge2
    if normal.length() < 1e-9 or edge1.length() < 1e-9:
        return None

    z = normal.normal()
    x = (edge1 - z * (edge1 * z)).normal()
    y = z ^ x

    origin = om.MPoint(
        p0.x * bary[0] + p1.x * bary[1] + p2.x * bary[2],
        p0.y * bary[0] + p1.y * bary[1] + p2.y * bary[2],
        p0.z * bary[0] + p1.z * bary[1] + p2.z * bary[2])

    return om.MMatrix([x.x, x.y, x.z, 0.0,
                       y.x, y.y, y.z, 0.0,
                       z.x, z.y, z.z, 0.0,
                       origin.x, origin.y, origin.z, 1.0])


def _barycentric(point: om.MPoint,
                 p0: om.MPoint,
                 p1: om.MPoint,
                 p2: om.MPoint,
                 ) -> Tuple[float, float, float]:
    """Barycentric coordinates of ``point`` projected on a triangle."""
    v0 = om.MVector(p1 - p0)
    v1 = om.MVector(p2 - p0)
    v2 = om.MVector(point - p0)
    d00 = v0 * v0
    d01 = v0 * v1
    d11 = v1 * v1
    d20 = v2 * v0
    d21 = v2 * v1
    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1e-12:
        return 1.0, 0.0, 0.0
    v = (d11 * d20 - d01 * d21) / denom
    w = (d00 * d21 - d01 * d20) / denom
    return 1.0 - v - w, v, w


def _face_triangles(mesh_fn: om.MFnMesh, face_id: int) -> List[List[int]]:
    """Fan-triangulate a polygon, returned as vertex-index triples."""
    verts = mesh_fn.getPolygonVertices(face_id)
    return [[verts[0], verts[i], verts[i + 1]]
            for i in range(1, len(verts) - 1)]


def _closest_triangle(mesh_fn: om.MFnMesh,
                      points: om.MPointArray,
                      position: om.MPoint,
                      ) -> Optional[Tuple[List[int], Tuple[float, float, float]]]:
    """The triangle under ``position``, plus barycentric coords within it."""
    try:
        _, face_id = mesh_fn.getClosestPoint(position, om.MSpace.kWorld)
    except Exception as e:
        logger.warning(f"Closest point failed: {e}")
        return None

    best = None
    best_dist = None
    for tri in _face_triangles(mesh_fn, face_id):
        p0, p1, p2 = (points[tri[0]], points[tri[1]], points[tri[2]])
        bary = _barycentric(position, p0, p1, p2)
        clamped = [max(0.0, min(1.0, b)) for b in bary]
        total = sum(clamped) or 1.0
        clamped = [b / total for b in clamped]
        on_tri = om.MPoint(
            p0.x * clamped[0] + p1.x * clamped[1] + p2.x * clamped[2],
            p0.y * clamped[0] + p1.y * clamped[1] + p2.y * clamped[2],
            p0.z * clamped[0] + p1.z * clamped[1] + p2.z * clamped[2])
        dist = (on_tri - position).length()
        if best_dist is None or dist < best_dist:
            best, best_dist = (tri, tuple(bary)), dist
    return best


def _uv_triangle(mesh_fn: om.MFnMesh,
                 u: float,
                 v: float,
                 ) -> Optional[Tuple[List[int], Tuple[float, float, float]]]:
    """Find the triangle containing a UV coordinate, with its barycentrics.

    Linear over the faces - fine for a joint cloud (tens of lookups), and the
    only way across a topology change. Falls back to the closest triangle in UV
    space when the point lands in a gap between shells.
    """
    best = None
    best_dist = None
    for face_id in range(mesh_fn.numPolygons):
        verts = mesh_fn.getPolygonVertices(face_id)
        try:
            uvs = [mesh_fn.getPolygonUV(face_id, i) for i in range(len(verts))]
        except Exception:
            continue
        for i in range(1, len(verts) - 1):
            tri = [verts[0], verts[i], verts[i + 1]]
            a, b, c = uvs[0], uvs[i], uvs[i + 1]
            bary = _barycentric(om.MPoint(u, v, 0.0),
                                om.MPoint(a[0], a[1], 0.0),
                                om.MPoint(b[0], b[1], 0.0),
                                om.MPoint(c[0], c[1], 0.0))
            if min(bary) >= -1e-6:
                return tri, bary
            # Track the nearest miss so a UV in a shell gap still resolves.
            miss = -min(bary)
            if best_dist is None or miss < best_dist:
                best, best_dist = (tri, bary), miss
    return best


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------

def solve_placements(joints: List[str],
                     source_mesh: str,
                     target_mesh: str,
                     regime: Dict,
                     ) -> Tuple[Dict[str, om.MMatrix], List[str]]:
    """Where each solved joint belongs in asset space.

    Every regime returns the same thing - a world matrix per joint - so nothing
    downstream has to know which method produced it.

    The non-rigid regimes express the joint in the local frame of the surface
    it sits over (``L = A * inverse(F_source)``) and rebuild it against the same
    frame on the target (``B = L * F_target``). Position and orientation travel
    together; there is no separate normal offset to maintain.

    Args:
        joints:      Solved joints, in solve space.
        source_mesh: The mesh they were solved against.
        target_mesh: The asset mesh.
        regime:      A :func:`classify` result.

    Returns:
        ``(placements, failed)`` - ``{joint: MMatrix}`` and the joints that
        could not be resolved.
    """
    placements: Dict[str, om.MMatrix] = {}
    failed: List[str] = []

    if regime["regime"] == "rigid":
        offset = om.MMatrix(regime["matrix"])
        for joint in joints:
            world = om.MMatrix(cmds.xform(joint, query=True, matrix=True,
                                          worldSpace=True))
            placements[joint] = world * offset
        return placements, failed

    src_fn = _mesh_fn(source_mesh)
    tgt_fn = _mesh_fn(target_mesh)
    src_points = src_fn.getPoints(om.MSpace.kWorld)
    tgt_points = tgt_fn.getPoints(om.MSpace.kWorld)
    use_uv = regime["regime"] == "uv"

    for joint in joints:
        world = om.MMatrix(cmds.xform(joint, query=True, matrix=True,
                                      worldSpace=True))
        position = om.MPoint(world[12], world[13], world[14])

        found = _closest_triangle(src_fn, src_points, position)
        if not found:
            failed.append(joint)
            continue
        src_tri, bary = found

        frame_src = _frame_from_triangle(src_points[src_tri[0]],
                                         src_points[src_tri[1]],
                                         src_points[src_tri[2]], bary)
        if frame_src is None:
            failed.append(joint)
            continue

        if use_uv:
            # Point order is gone: cross over through UV space instead.
            try:
                u, v = src_fn.getUVAtPoint(position, om.MSpace.kWorld)[:2]
            except Exception as e:
                logger.warning(f"No UV at '{joint}': {e}")
                failed.append(joint)
                continue
            resolved = _uv_triangle(tgt_fn, u, v)
            if not resolved:
                failed.append(joint)
                continue
            tgt_tri, tgt_bary = resolved
        else:
            tgt_tri, tgt_bary = src_tri, bary

        frame_tgt = _frame_from_triangle(tgt_points[tgt_tri[0]],
                                         tgt_points[tgt_tri[1]],
                                         tgt_points[tgt_tri[2]], tgt_bary)
        if frame_tgt is None:
            failed.append(joint)
            continue

        placements[joint] = world * frame_src.inverse() * frame_tgt

    return placements, failed


# ---------------------------------------------------------------------------
# Joints, bind, weights
# ---------------------------------------------------------------------------

def create_asset_joints(placements: Dict[str, om.MMatrix],
                        joint_prefix: str = "assetBone",
                        group_name: str = "assetBones_GRP",
                        ) -> Tuple[Dict[str, str], str]:
    """Create a fresh joint per solved joint, at its asset-space matrix.

    Fresh joints rather than moved ones: the solve's skeleton keeps carrying the
    animation (it is the reference the bake reads from), and the influence
    correspondence downstream becomes identity by construction.

    Args:
        placements:   ``{solved_joint: asset-space MMatrix}``.
        joint_prefix: Prefix for the created joints.
        group_name:   Group the new joints are parented under.

    Returns:
        ``(pairs, group)`` - ``{solved_joint: new_joint}`` and the group name.
    """
    group = cmds.group(empty=True, name=group_name)
    pairs: Dict[str, str] = {}

    for index, (source, matrix) in enumerate(sorted(placements.items())):
        cmds.select(clear=True)
        name = f"{joint_prefix}_{index}"
        joint = cmds.joint(name=name)
        joint = cmds.parent(joint, group)[0]
        cmds.xform(joint, matrix=list(matrix), worldSpace=True)
        # A solved joint cloud has no meaningful joint orient; keep it clean so
        # the baked rotations mean what they say.
        cmds.setAttr(f"{joint}.jointOrientX", 0.0)
        cmds.setAttr(f"{joint}.jointOrientY", 0.0)
        cmds.setAttr(f"{joint}.jointOrientZ", 0.0)
        cmds.xform(joint, matrix=list(matrix), worldSpace=True)
        pairs[source] = joint

    return pairs, group


def bind_asset_mesh(target_mesh: str,
                    joints: List[str],
                    max_influences: int = 8,
                    skin_name: Optional[str] = None,
                    replace_existing: bool = False,
                    ) -> Optional[str]:
    """Bind the asset mesh to the new joints, at the asset pose.

    ``removeUnusedInfluence`` is forced off: it defaults ON and prunes, at bind
    time, every joint the bind method gave no weight to - bind 56 and silently
    get 35. Since the weights are overwritten immediately afterwards, a joint
    dropped here would be gone before it ever received its column.

    ``maximumInfluences`` is matched to the solve's ``nnz`` for the same reason:
    a narrower cap than the incoming data prunes it on arrival.
    """
    if not joints:
        logger.error("No joints to bind to.")
        return None

    existing = dem_cmds.find_skin_cluster(target_mesh)
    if existing:
        if not replace_existing:
            logger.error(
                f"'{target_mesh}' already has '{existing}'. Binding again "
                f"would stack a second skinCluster - pass replace_existing.")
            return None
        cmds.delete(existing)

    try:
        skin = cmds.skinCluster(joints, target_mesh,
                                toSelectedBones=True,
                                bindMethod=0,
                                skinMethod=0,
                                normalizeWeights=1,
                                maximumInfluences=max_influences,
                                obeyMaxInfluences=False,
                                removeUnusedInfluence=False,
                                name=skin_name or "assetBones_skinCluster")[0]
    except Exception as e:
        logger.error(f"Bind failed: {e}")
        return None
    return skin


def copy_solved_weights(src_skin: str,
                        source_mesh: str,
                        tgt_skin: str,
                        target_mesh: str,
                        pairs: Dict[str, str],
                        vertex_mode: str = "index",
                        ) -> Tuple[bool, str]:
    """Move the solved weights onto the fresh bind.

    The influence mapping is identity by construction (one new joint per solved
    joint), so this is a straight re-column through :mod:`SkinMatch`, which also
    zeroes any target influence with no source rather than leaving stale weights
    underneath.
    """
    import dw_maya.dw_deformers.SkinMatch.skin_match_cmds as smc

    return smc.transfer_weights(src_skin, source_mesh,
                                tgt_skin, target_mesh,
                                mapping=dict(pairs),
                                vertex_mode=vertex_mode,
                                add_missing_influences=False,
                                normalize=True)


# ---------------------------------------------------------------------------
# Animation
# ---------------------------------------------------------------------------

def link_animation(pairs: Dict[str, str],
                   mode: str = "relink",
                   start: Optional[float] = None,
                   end: Optional[float] = None,
                   ) -> Tuple[bool, str]:
    """Carry the solved animation onto the new joints.

    ``relink`` parents each new joint under an offset group holding
    ``inverse(A) * B`` and connects the solved curves verbatim, giving
    ``B(t) = A(t) * inverse(A) * B``. Under a rigid difference every offset is
    the same matrix and this is exact - no sampling, nothing to drift.

    ``bake`` writes ``B * inverse(A) * A(t)`` per frame: each joint's motion in
    its OWN rest frame, re-applied at its new rest. This is the correct
    retarget once the joints have moved non-rigidly relative to each other, and
    a parent cannot express it - parenting multiplies on the right, and this
    offset has to land on the left. A solved joint cloud is flat, so unlike an
    FK chain nothing compounds down a hierarchy.

    Args:
        pairs: ``{solved_joint: new_joint}``.
        mode:  ``relink`` or ``bake``.
        start: Bake range start (defaults to the playback range).
        end:   Bake range end.
    """
    if mode not in ("relink", "bake"):
        return False, f"Unknown animation mode '{mode}'."

    if mode == "relink":
        for source, target in pairs.items():
            source_world = om.MMatrix(cmds.xform(source, query=True,
                                                 matrix=True, worldSpace=True))
            target_world = om.MMatrix(cmds.xform(target, query=True,
                                                 matrix=True, worldSpace=True))
            offset = source_world.inverse() * target_world

            group = cmds.group(empty=True, name=f"{target}_offset_GRP")
            parents = cmds.listRelatives(target, parent=True,
                                         fullPath=True) or []
            if parents:
                group = cmds.parent(group, parents[0])[0]
            cmds.xform(group, matrix=list(offset), worldSpace=False)
            target_new = cmds.parent(target, group)[0]

            for channel in _CHANNELS:
                source_plug = f"{source}.{channel}"
                inputs = cmds.listConnections(source_plug, source=True,
                                              destination=False,
                                              plugs=True) or []
                if inputs:
                    cmds.connectAttr(inputs[0], f"{target_new}.{channel}",
                                     force=True)
                else:
                    cmds.setAttr(f"{target_new}.{channel}",
                                 cmds.getAttr(source_plug))
        return True, f"Relinked {len(pairs)} joints through offset groups."

    # -- bake ------------------------------------------------------------
    if start is None:
        start = cmds.playbackOptions(query=True, minTime=True)
    if end is None:
        end = cmds.playbackOptions(query=True, maxTime=True)

    rest: Dict[str, Tuple[om.MMatrix, om.MMatrix]] = {}
    for source, target in pairs.items():
        rest[source] = (
            om.MMatrix(cmds.xform(source, query=True, matrix=True,
                                  worldSpace=True)),
            om.MMatrix(cmds.xform(target, query=True, matrix=True,
                                  worldSpace=True)))

    current = cmds.currentTime(query=True)
    try:
        frame = start
        while frame <= end:
            cmds.currentTime(frame, edit=True)
            for source, target in pairs.items():
                source_rest, target_rest = rest[source]
                source_now = om.MMatrix(cmds.xform(source, query=True,
                                                   matrix=True,
                                                   worldSpace=True))
                world = target_rest * source_rest.inverse() * source_now
                cmds.xform(target, matrix=list(world), worldSpace=True)
                for channel in _CHANNELS:
                    cmds.setKeyframe(f"{target}.{channel}", time=frame)
            frame += 1.0
    finally:
        cmds.currentTime(current, edit=True)

    return True, (f"Baked {len(pairs)} joints over frames "
                  f"{int(start)}-{int(end)}.")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

#: The build, as the artist sees it. Index order is the execution order.
STEPS = ("Classify the two meshes",
         "Place joints in asset space",
         "Create fresh joints",
         "Bind the asset mesh",
         "Copy the solved weights",
         "Transfer the animation")


def bones_to_asset(source_mesh: str,
                   target_mesh: str,
                   anim_mode: str = "auto",
                   joint_prefix: str = "assetBone",
                   max_influences: int = 8,
                   replace_existing: bool = False,
                   progress=None,
                   ) -> Dict:
    """Full return leg: solve space -> asset space, joints + skin + animation.

    Args:
        source_mesh:    The simulated / solved mesh, carrying the solve's
                        skinCluster.
        target_mesh:    The asset mesh, in asset space.
        anim_mode:      ``auto`` picks relink for a rigid difference and bake
                        otherwise; ``relink`` / ``bake`` force one; ``none``
                        skips the animation entirely.
        joint_prefix:   Prefix for the created joints.
        max_influences: Should match the solve's ``nnz``.
        replace_existing: Delete an existing skinCluster on the asset first.
        progress:       Optional ``callable(index, status, detail)`` called as
                        each :data:`STEPS` entry starts and finishes, so a UI
                        can show the build advancing rather than freezing.

    Returns:
        Report dict: ``regime``, ``detail``, ``joints``, ``skin``, ``failed``,
        ``messages``, and ``ok``.
    """
    report = {"regime": None, "detail": "", "joints": {}, "skin": None,
              "failed": [], "messages": [], "ok": False}

    def step(index, status, detail=""):
        if progress:
            try:
                progress(index, status, detail)
            except Exception as e:
                logger.warning(f"progress callback failed: {e}")

    src_skin = dem_cmds.find_skin_cluster(source_mesh)
    if not src_skin:
        report["detail"] = f"No skinCluster on '{source_mesh}'."
        step(0, "fail", report["detail"])
        return report

    step(0, "run")
    regime = classify(source_mesh, target_mesh)
    report["regime"] = regime["regime"]
    report["detail"] = regime["detail"]
    logger.info(f"bones_to_asset regime: {regime['regime']} - {regime['detail']}")
    step(0, "ok", f"{regime['regime']} - {regime['detail']}")

    step(1, "run")
    joints = cmds.skinCluster(src_skin, query=True, influence=True) or []
    placements, failed = solve_placements(joints, source_mesh, target_mesh,
                                          regime)
    report["failed"] = failed
    if not placements:
        report["detail"] = "No joint could be placed in asset space."
        step(1, "fail", report["detail"])
        return report
    if failed:
        report["messages"].append(
            f"{len(failed)} joints could not be placed and were skipped.")
        step(1, "warn", f"{len(placements)} placed, {len(failed)} skipped")
    else:
        step(1, "ok", f"{len(placements)} joints placed")

    step(2, "run")
    pairs, group = create_asset_joints(placements, joint_prefix=joint_prefix)
    report["joints"] = pairs
    report["messages"].append(f"Created {len(pairs)} joints under '{group}'.")
    step(2, "ok", f"{len(pairs)} joints under '{group}'")

    step(3, "run")
    skin = bind_asset_mesh(target_mesh, list(pairs.values()),
                           max_influences=max_influences,
                           replace_existing=replace_existing)
    if not skin:
        report["detail"] = "Bind failed - see the script editor."
        step(3, "fail", report["detail"])
        return report
    report["skin"] = skin
    step(3, "ok", skin)

    step(4, "run")
    vertex_mode = "index" if regime["regime"] != "uv" else "closestPoint"
    ok, message = copy_solved_weights(src_skin, source_mesh, skin, target_mesh,
                                      pairs, vertex_mode=vertex_mode)
    report["messages"].append(message)
    step(4, "ok" if ok else "fail", message)
    if not ok:
        return report

    if anim_mode == "none":
        step(5, "skip", "skipped")
    else:
        step(5, "run")
        mode = anim_mode
        if mode == "auto":
            mode = "relink" if regime["regime"] == "rigid" else "bake"
        ok, message = link_animation(pairs, mode=mode)
        report["messages"].append(message)
        step(5, "ok" if ok else "fail", message)
        if not ok:
            return report

    report["ok"] = True
    return report