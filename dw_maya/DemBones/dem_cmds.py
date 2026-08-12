"""
dem_cmds.py - DemBones tool commands: scene discovery, validation, FBX export,
exe argument building, generation (fbx + sidecar json) I/O, and a QProcess-based
solve runner.

This module holds every non-UI operation so the widgets stay thin. Maya calls
live here; the exe call is wrapped in :class:`SolveRunner` (QProcess) so the UI
never blocks during a solve.

Layout on disk
--------------
    <output_dir>/
        curtain_b100_1001-1052.fbx
        curtain_b100_1001-1052.json   <- sidecar: params + range + rmse

Author:
    DrWeeny
"""

from __future__ import annotations

import os
import re
import sys
import json
import glob
import shutil
import tempfile
import functools
from typing import Dict, List, Optional, Tuple

from maya import cmds, mel

from dw_maya.DemBones.compat import QtCore
from dw_maya.dw_decorators import dw_undo, dw_generic_undo, dw_viewportOff
from dw_logger import get_logger

logger = get_logger()


# ============================================================================
# EXE RESOLUTION
# ============================================================================

# Where to get the precompiled binaries when none is found. DemBones is an
# Electronic Arts project under BSD-3 - the binaries are not redistributed with
# this repo, so the artist points the tool at their own copy (PATH or env var).
DEMBONES_DOWNLOAD_URL = "https://github.com/electronicarts/dem-bones/releases"

# Maya optionVar that stores a user-located exe path (set via "Locate DemBones"
# in the UI). Persists across Maya sessions, per user.
_EXE_PREF_KEY = "dw_dembones_exe"


def get_saved_exe() -> Optional[str]:
    """Return the user-located exe path saved in the Maya prefs, if any."""
    try:
        if cmds.optionVar(exists=_EXE_PREF_KEY):
            path = cmds.optionVar(query=_EXE_PREF_KEY)
            if path and os.path.isfile(path):
                return path
    except Exception as e:
        logger.warning(f"Could not read DemBones exe pref: {e}")
    return None


def set_saved_exe(path: str) -> None:
    """Persist a user-located exe path to the Maya prefs."""
    try:
        cmds.optionVar(stringValue=(_EXE_PREF_KEY, path))
    except Exception as e:
        logger.error(f"Could not save DemBones exe pref: {e}")


def _exe_name() -> str:
    """Platform executable file name."""
    return "DemBones.exe" if sys.platform.startswith("win") else "DemBones"


def _bundled_exe_path() -> str:
    """Expected path of a binary dropped under ``<package>/bin/<OS>/``."""
    here = os.path.dirname(os.path.abspath(__file__))
    if sys.platform.startswith("win"):
        sub = "Windows"
    elif sys.platform.startswith("linux"):
        sub = "Linux"
    else:
        sub = "macOS"
    return os.path.join(here, "bin", sub, _exe_name())


def get_exe_path() -> Optional[str]:
    """Resolve the DemBones executable for the current platform.

    Resolution order, first hit wins:
        1. ``DEMBONES_EXE`` env var - an explicit path (pipeline / tool deploy).
        2. A path the artist located via the UI (saved in Maya prefs).
        3. The system ``PATH`` (artist installed DemBones globally).
        4. A binary dropped under ``<package>/bin/<OS>/DemBones[.exe]``.

    The binaries themselves are not committed (BSD-3, large, platform specific);
    see :data:`DEMBONES_DOWNLOAD_URL`.

    Returns:
        str path to the executable, or ``None`` if it can't be found.
    """
    # 1. Explicit override (pipeline / tool deploy).
    override = os.environ.get("DEMBONES_EXE")
    if override and os.path.isfile(override):
        return override
    if override:
        logger.warning(f"DEMBONES_EXE is set but not a file: {override}")

    # 2. User-located path saved in the Maya prefs.
    saved = get_saved_exe()
    if saved:
        return saved

    # 3. On PATH.
    on_path = shutil.which(_exe_name())
    if on_path:
        return on_path

    # 4. Bundled alongside the tool.
    candidate = _bundled_exe_path()
    if os.path.isfile(candidate):
        return candidate

    logger.warning(
        f"DemBones exe not found (env DEMBONES_EXE, saved pref, PATH, or "
        f"{candidate}). Download from {DEMBONES_DOWNLOAD_URL}")
    return None


# ============================================================================
# SCENE DISCOVERY (Alembic + rig from the target mesh history)
# ============================================================================

def find_alembic_node(mesh: str) -> Optional[str]:
    """Find the AlembicNode driving ``mesh`` by walking its history.

    Args:
        mesh: Mesh transform or shape name.

    Returns:
        The AlembicNode name, or ``None`` if the mesh isn't abc-driven.
    """
    try:
        history = cmds.listHistory(mesh) or []
    except Exception as e:
        logger.warning(f"listHistory failed on '{mesh}': {e}")
        return None
    abc_nodes = cmds.ls(history, type="AlembicNode") or []
    return abc_nodes[0] if abc_nodes else None


def alembic_file_path(abc_node: str) -> Optional[str]:
    """Return the .abc file path stored on an AlembicNode."""
    try:
        return cmds.getAttr(f"{abc_node}.abc_File")
    except Exception as e:
        logger.warning(f"Could not read abc_File on '{abc_node}': {e}")
        return None


def alembic_frame_range(abc_node: str) -> Optional[Tuple[int, int]]:
    """Return (start, end) frames stored on an AlembicNode, if available."""
    try:
        start = cmds.getAttr(f"{abc_node}.startFrame")
        end = cmds.getAttr(f"{abc_node}.endFrame")
        return int(round(start)), int(round(end))
    except Exception:
        return None


def find_skin_cluster(mesh: str) -> Optional[str]:
    """Find the skinCluster in the history of ``mesh`` (None if unskinned)."""
    try:
        history = cmds.listHistory(mesh) or []
    except Exception as e:
        logger.warning(f"listHistory failed on '{mesh}': {e}")
        return None
    skins = cmds.ls(history, type="skinCluster") or []
    return skins[0] if skins else None


def skin_influences(skin_cluster: str) -> List[str]:
    """Return the influence joints of a skinCluster, in influence order."""
    try:
        return cmds.skinCluster(skin_cluster, query=True, influence=True) or []
    except Exception as e:
        logger.warning(f"Could not query influences on '{skin_cluster}': {e}")
        return []


def find_joints_from_mesh(mesh: str) -> List[str]:
    """Best-effort joint discovery: influences if skinned, else None.

    For the sparse / external-bone case (joints present but no skinCluster yet)
    the joints can't be derived from the mesh; the caller falls back to the
    current selection.
    """
    skin = find_skin_cluster(mesh)
    if skin:
        return skin_influences(skin)
    return []


# ============================================================================
# SKIN COPY (same joints, another mesh - seeding a rest mesh from a generation)
# ============================================================================

def _skin_fn(skin_cluster: str):
    """Return the API 2.0 MFnSkinCluster for a skinCluster node."""
    import maya.api.OpenMaya as om
    import maya.api.OpenMayaAnim as oma
    sel = om.MSelectionList()
    sel.add(skin_cluster)
    return oma.MFnSkinCluster(sel.getDependNode(0))


def _vertex_component(mesh: str, n_vtx: int):
    """Return (dagPath-to-shape, complete vertex component) for a mesh."""
    import maya.api.OpenMaya as om
    sel = om.MSelectionList()
    sel.add(mesh)
    dag = sel.getDagPath(0)
    dag.extendToShape()
    comp_fn = om.MFnSingleIndexedComponent()
    components = comp_fn.create(om.MFn.kMeshVertComponent)
    comp_fn.setCompleteData(n_vtx)
    return dag, components


def _influence_logical_indices(skin_cluster: str) -> Dict[str, int]:
    """Map each influence name to its logical index in the skinCluster arrays.

    The ``matrix`` / ``bindPreMatrix`` plug arrays are sparse - a joint's slot
    is whatever index it was connected on, not its position in influence order -
    so per-influence attributes must be addressed through this map rather than
    by enumerating influence order.
    """
    fn = _skin_fn(skin_cluster)
    return {path.partialPathName(): fn.indexForInfluenceObject(path)
            for path in fn.influenceObjects()}


def _read_skin_weights(skin_cluster: str,
                       mesh: str,
                       n_vtx: int,
                       ) -> Tuple[List[float], List[str]]:
    """Read every weight of a skinCluster in one call.

    Returns:
        (flat weights, influence names). The weights are row-major -
        ``[v0_i0, v0_i1, ..., v1_i0, ...]`` - with the columns in the order of
        the returned influence names.
    """
    fn = _skin_fn(skin_cluster)
    influences = [path.partialPathName() for path in fn.influenceObjects()]
    dag, components = _vertex_component(mesh, n_vtx)
    weights, _ = fn.getWeights(dag, components)
    return list(weights), influences


SURFACE_ASSOCIATIONS = ["closestPoint", "closestComponent", "rayCast"]


def bind_space_shape(mesh: str) -> str:
    """The shape a new skinCluster would actually deform.

    On an already-deformed mesh that is the intermediate ("Orig") shape, not
    the visible one: deformers read the original geometry and write the
    displayed result. The two can be far apart - a prop modelled at the origin
    and carried into the set by its rig shows up in the set while the geometry
    a fresh bind would consume is still at the origin.

    Args:
        mesh: Mesh transform or shape.

    Returns:
        The intermediate shape when the mesh has one, else the visible shape,
        else ``mesh`` unchanged.
    """
    node = mesh
    try:
        if cmds.objectType(node, isAType="shape"):
            parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
            node = parents[0] if parents else node
        shapes = cmds.listRelatives(node,
                                    shapes=True,
                                    fullPath=True,
                                    noIntermediate=False) or []
    except Exception as e:
        logger.warning(f"Could not resolve the bind shape of '{mesh}': {e}")
        return mesh

    if not shapes:
        return mesh
    for shape in shapes:
        try:
            if cmds.getAttr(f"{shape}.intermediateObject"):
                return shape
        except Exception:
            continue
    return shapes[0]


def meshes_share_space(mesh_a: str,
                       mesh_b: str,
                       tolerance: float = 0.01,
                       undeformed: bool = True,
                       ) -> Tuple[bool, float]:
    """Are two meshes sitting in the same place in BIND space?

    A precondition for copying skinning between them: the weights are scalars
    and carry over fine, but the target ends up bound to the SOURCE's joints,
    which live wherever the solve put them. If the target sits somewhere else,
    binding snaps it over to the joints as soon as the animation evaluates -
    the "my mesh jumped back to the origin" symptom. Nothing in the skinCluster
    can compensate for that; the two have to be brought together first.

    Both meshes are measured through :func:`bind_space_shape`, NOT through what
    the viewport shows. An already-rigged pipeline mesh displays its deformed
    position while a new skinCluster binds the undeformed shape underneath, and
    the two are routinely in different places - the asset modelled at the origin
    and placed in the set by its rig. Comparing the visible boxes says "same
    place" and the bind still snaps.

    Compared as the distance between bounding-box centres, relative to the
    first mesh's diagonal, so the tolerance means the same thing at any scale.

    Args:
        mesh_a: First mesh (transform or shape).
        mesh_b: Second mesh.
        tolerance: Allowed offset as a fraction of mesh_a's bbox diagonal.
        undeformed: Measure the bind-space (intermediate) shapes. False
            measures what the viewport shows, which is the right question when
            checking whether a closest-point weight transfer has the two
            surfaces on top of each other.

    Returns:
        (share_space, distance_between_centres). Falls back to (True, 0.0)
        when a bounding box cannot be read - unknown is not a mismatch.
    """
    resolve = bind_space_shape if undeformed else (lambda mesh: mesh)
    try:
        # exactWorldBoundingBox, not xform(boundingBox): xform refuses a shape
        # ("No valid objects supplied"), which sent this straight to the except
        # branch and reported every mesh pair as fine.
        box_a = cmds.exactWorldBoundingBox(resolve(mesh_a))
        box_b = cmds.exactWorldBoundingBox(resolve(mesh_b))
    except Exception as e:
        logger.warning(f"Could not compare world space: {e}")
        return True, 0.0

    centre_a = [(box_a[i] + box_a[i + 3]) * 0.5 for i in range(3)]
    centre_b = [(box_b[i] + box_b[i + 3]) * 0.5 for i in range(3)]
    distance = sum((centre_a[i] - centre_b[i]) ** 2 for i in range(3)) ** 0.5
    diagonal = sum((box_a[i + 3] - box_a[i]) ** 2 for i in range(3)) ** 0.5
    limit = (diagonal or 1.0) * tolerance
    return distance <= limit, distance


def _vertex_position(mesh: str, index: int) -> List[float]:
    """World position of one vertex."""
    return cmds.xform(f"{mesh}.vtx[{index}]",
                      query=True,
                      worldSpace=True,
                      translation=True)


def _orthonormal_frame(p0: List[float],
                       p1: List[float],
                       p2: List[float],
                       ) -> Optional[List[float]]:
    """Build a 4x4 frame from three points, or None if they are collinear.

    Rows 0-2 are the orthonormal axes, row 3 the origin - Maya's row-vector
    convention, so a point in frame coordinates maps out with ``p * frame``.
    """
    def sub(a, b):
        return [a[i] - b[i] for i in range(3)]

    def cross(a, b):
        return [a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0]]

    def norm(a):
        length = sum(c * c for c in a) ** 0.5
        return None if length < 1e-9 else [c / length for c in a]

    axis_x = norm(sub(p1, p0))
    if axis_x is None:
        return None
    axis_z = norm(cross(axis_x, sub(p2, p0)))
    if axis_z is None:
        return None
    axis_y = cross(axis_z, axis_x)
    return (axis_x + [0.0] + axis_y + [0.0] + axis_z + [0.0]
            + list(p0) + [1.0])


def visible_shape(mesh: str) -> str:
    """The shape actually drawn - the deformed one when a deformer exists."""
    node = mesh
    try:
        if cmds.objectType(node, isAType="shape"):
            parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
            node = parents[0] if parents else node
        shapes = cmds.listRelatives(node, shapes=True, fullPath=True,
                                    noIntermediate=True) or []
    except Exception as e:
        logger.warning(f"Could not resolve the visible shape of '{mesh}': {e}")
        return mesh
    return shapes[0] if shapes else mesh


def derive_bind_offset(target_mesh: str) -> Optional[List[float]]:
    """The transform from a mesh's bind space into the space it is drawn in.

    Removes the one hand-made prerequisite the return leg used to need. A
    bind-pose *mesh* was never the requirement - the transform was, and both
    shapes needed to solve it are already on the asset: its intermediate
    ("Orig") shape holds the undeformed geometry in bind space, and its visible
    shape holds the same geometry where the rig puts it. Same topology, so the
    vertices correspond by index and the fit is exact.

    Valid whenever the rig's placement is rigid at the frame this is called on,
    which is the ordinary case at rest - a prop carried into the set does not
    deform on the way. :func:`rigid_transform_between` verifies it and returns
    None rather than approximating, so a genuinely deforming rest pose falls
    back to the manual override instead of being fudged.

    Args:
        target_mesh: The asset mesh, at its rest frame.

    Returns:
        A flat 16-float matrix, or None when there is nothing to correct (no
        deformer, so bind space is already the drawn space) or when the
        difference is not rigid.
    """
    bind = bind_space_shape(target_mesh)
    drawn = visible_shape(target_mesh)
    if bind == drawn:
        logger.info(f"'{target_mesh}' has no intermediate shape - its bind "
                    f"space is the space it is drawn in, no offset needed.")
        return None
    return rigid_transform_between(bind, drawn)


def rigid_transform_between(mesh_from: str,
                            mesh_to: str,
                            tolerance: float = 0.001,
                            ) -> Optional[List[float]]:
    """The rigid transform mapping one mesh's points onto another's.

    For the case where a mesh has been moved (and only moved) - the solved rest
    mesh placed onto the target's bind pose, say. The two must share topology:
    vertices are paired by index, three of them build a frame on each side, and
    the result is verified against further samples so a non-rigid difference is
    reported rather than silently approximated.

    Args:
        mesh_from: Mesh whose space the result maps OUT of.
        mesh_to: Mesh whose space the result maps INTO.
        tolerance: Allowed verification error as a fraction of the sample
            spread.

    Returns:
        A flat 16-float matrix (row-major), or None when the vertex counts
        differ, the samples are degenerate, or the difference is not rigid.
    """
    n_from = mesh_vertex_count(mesh_from) or 0
    n_to = mesh_vertex_count(mesh_to) or 0
    if not n_from or n_from != n_to:
        logger.error(
            f"Cannot solve a rigid transform: '{mesh_from}' has {n_from} "
            f"vertices, '{mesh_to}' has {n_to}. They must share topology.")
        return None

    # Spread the samples over the whole mesh: nearby vertices make a poor
    # frame and a verification that proves nothing.
    indices = sorted({0, n_from // 5, 2 * n_from // 5, 3 * n_from // 5,
                      4 * n_from // 5, n_from - 1})
    try:
        points_from = [_vertex_position(mesh_from, i) for i in indices]
        points_to = [_vertex_position(mesh_to, i) for i in indices]
    except Exception as e:
        logger.error(f"Could not read vertex positions: {e}")
        return None

    frame_from = _orthonormal_frame(*points_from[:3])
    frame_to = _orthonormal_frame(*points_to[:3])
    if frame_from is None or frame_to is None:
        logger.error("The sampled vertices are collinear - cannot build a "
                     "frame. The meshes may be degenerate.")
        return None

    import maya.api.OpenMaya as om
    matrix = om.MMatrix(frame_from).inverse() * om.MMatrix(frame_to)

    # Verify on the samples that did not build the frame.
    spread = max(
        sum((points_from[0][k] - p[k]) ** 2 for k in range(3)) ** 0.5
        for p in points_from[1:]) or 1.0
    worst = 0.0
    for source_point, target_point in zip(points_from, points_to):
        mapped = om.MPoint(source_point) * matrix
        worst = max(worst, (om.MPoint(target_point) - mapped).length())
    if worst > spread * tolerance:
        logger.error(
            f"'{mesh_from}' and '{mesh_to}' do not differ by a rigid "
            f"transform (worst sample error {worst:.4f} over a {spread:.1f} "
            f"spread). A single matrix cannot express the difference.")
        return None

    logger.info(f"Solved the rigid transform '{mesh_from}' -> '{mesh_to}' "
                f"(worst sample error {worst:.6f}).")
    return list(matrix)


@dw_undo.singleUndoChunk
def copy_skin_cluster(source_mesh: str,
                      target_mesh: str,
                      replace: bool = True,
                      copy_bind_pose: bool = True,
                      surface_association: str = "closestPoint",
                      bind_pose_mesh: Optional[str] = None,
                      new_skin_name: Optional[str] = None,
                      ) -> Optional[str]:
    """Copy a skinCluster from one mesh to another, binding the SAME joints.

    The shortcut for reusing an earlier generation's weights: bind the rest mesh
    to the joints of a solved DemBones result so an "Animation only" solve has
    weights to keep. Unlike :func:`transfer_skin_by_name` there is no name
    matching - the target is bound to the very influence nodes the source uses,
    so both meshes end up driven by one skeleton.

    When the two meshes share a vertex count the weights are copied index to
    index through the API (exact, and immune to the two meshes sitting in
    different places). Otherwise it falls back to ``copySkinWeights`` with
    closest-point association, which is an approximation.

    ``copy_bind_pose`` carries the source's ``bindPreMatrix`` values over, so the
    result does not depend on where the joints happen to be right now. Without
    it, binding to an animated skeleton would freeze the current frame's pose as
    the bind pose and the mesh would jump.

    Args:
        source_mesh: Skinned mesh to read from (transform or shape).
        target_mesh: Mesh to receive the skinning.
        replace: Delete an existing skinCluster on the target first. When False
            an existing one is kept and only its weights are overwritten (any
            missing influence is added).
        copy_bind_pose: Copy the source's bindPreMatrix values onto the target.
        surface_association: ``copySkinWeights`` association used when the
            topologies differ (see ``SURFACE_ASSOCIATIONS``). ``closestPoint``
            suits a mesh that lost or gained points, ``closestComponent``
            respects shell boundaries, ``rayCast`` suits offset surfaces.
            Ignored on the exact path.
        bind_pose_mesh: A copy of ``source_mesh`` moved onto the target's own
            bind pose. Use it when the target's undeformed geometry is not
            where the solve happened - the rigid transform between the two is
            solved and folded into the copied bindPreMatrix values, so the
            target binds correctly in ITS space while the animation still plays
            out in the solve's space. Must share topology with ``source_mesh``.
        new_skin_name: Name for a newly created target skinCluster.

    Returns:
        The target skinCluster name, or None on failure.
    """
    src_skin = find_skin_cluster(source_mesh)
    if not src_skin:
        logger.error(f"No skinCluster found on source mesh '{source_mesh}'.")
        return None

    influences = skin_influences(src_skin)
    if not influences:
        logger.error(f"skinCluster '{src_skin}' has no influences.")
        return None

    bind_offset = None
    if bind_pose_mesh:
        bind_offset = rigid_transform_between(bind_pose_mesh, source_mesh)
        if bind_offset is None:
            logger.error(
                f"Could not solve the bind-pose offset from "
                f"'{bind_pose_mesh}'. Aborting rather than binding into the "
                f"wrong space.")
            return None

    # A bind-pose mesh is the answer to a space mismatch, so only complain
    # about one when no offset is being applied.
    same_space, distance = (True, 0.0) if bind_offset is not None \
        else meshes_share_space(source_mesh, target_mesh)
    if not same_space:
        logger.warning(
            f"'{source_mesh}' and '{target_mesh}' are {distance:.3f} units "
            f"apart in world space. The target is about to be bound to the "
            f"source's joints, which stay where they are - expect it to snap "
            f"over to them. Move one onto the other first (placing the "
            f"generation's group is usually the way).")

    tgt_skin = find_skin_cluster(target_mesh)
    if tgt_skin and replace:
        logger.info(f"Removing existing skinCluster '{tgt_skin}' on the target.")
        cmds.delete(tgt_skin)
        tgt_skin = None

    if not tgt_skin:
        name = new_skin_name or f"{_leaf_name(target_mesh)}_skinCluster"
        # obeyMaxInfluences off: a DemBones solve can hand out more influences
        # per vertex than Maya's default cap, and the cap would silently prune
        # them as the weights are written.
        tgt_skin = cmds.skinCluster(influences,
                                    target_mesh,
                                    toSelectedBones=True,
                                    obeyMaxInfluences=False,
                                    normalizeWeights=1,
                                    name=name)[0]
        logger.info(f"Created skinCluster '{tgt_skin}' on '{target_mesh}'.")
    else:
        existing = set(skin_influences(tgt_skin))
        for joint in influences:
            if joint not in existing:
                cmds.skinCluster(tgt_skin,
                                 edit=True,
                                 addInfluence=joint,
                                 weight=0.0)

    if copy_bind_pose:
        _copy_bind_pre_matrices(src_skin, tgt_skin, influences, bind_offset)

    # 0 stands for "could not be counted" and takes the approximate path.
    src_n = mesh_vertex_count(source_mesh) or 0
    tgt_n = mesh_vertex_count(target_mesh) or 0
    if src_n and src_n == tgt_n:
        _copy_weights_exact(src_skin, source_mesh, tgt_skin, target_mesh, src_n)
        logger.info(
            f"Copied {len(influences)} influences '{src_skin}' -> '{tgt_skin}' "
            f"(exact, {src_n} verts).")
    else:
        # copySkinWeights pairs vertices by their CURRENT positions, so the two
        # surfaces have to be on top of each other at this moment. They are at
        # the rest frame - the target has just been bound and the joints sit at
        # their bind pose - and they are not at any other frame.
        overlapping, apart = meshes_share_space(source_mesh, target_mesh,
                                                undeformed=False)
        if not overlapping:
            logger.warning(
                f"The two surfaces are {apart:.2f} units apart as they stand, "
                f"so the closest-point pairing has nothing sensible to match. "
                f"Go to the rest frame (where the solved joints are at their "
                f"bind pose) and copy again.")

        # "name" first, never "closestJoint": both skinClusters are bound to the
        # very same joints, so the pairing is already known. closestJoint would
        # re-derive it by proximity and a DemBones joint cloud is dense enough
        # that it pairs a joint with its neighbour, smearing the weights.
        cmds.copySkinWeights(sourceSkin=src_skin,
                             destinationSkin=tgt_skin,
                             noMirror=True,
                             surfaceAssociation=surface_association,
                             influenceAssociation=["name", "oneToOne"])
        logger.warning(
            f"Vertex counts differ ({src_n} vs {tgt_n}) - fell back to "
            f"{surface_association} copySkinWeights; the weights are "
            f"approximate.")
    return tgt_skin


def _copy_bind_pre_matrices(src_skin: str,
                            tgt_skin: str,
                            influences: List[str],
                            offset: Optional[List[float]] = None,
                            ) -> None:
    """Copy the per-influence bindPreMatrix values between two skinClusters.

    ``offset`` pre-multiplies each matrix. Maya deforms with
    ``p * bindPreMatrix * jointWorldMatrix``, so an ``offset`` mapping the
    target's bind space into the source's turns that into
    ``p * offset * bindPre * jointWorld`` - the point is carried into the space
    the solve happened in, deformed there, and the animation is untouched.
    That is the whole trick: the bind moves, the motion does not.
    """
    import maya.api.OpenMaya as om
    offset_matrix = om.MMatrix(offset) if offset else None

    src_idx = _influence_logical_indices(src_skin)
    tgt_idx = _influence_logical_indices(tgt_skin)
    for joint in influences:
        key = _leaf_name(joint)
        s = src_idx.get(joint, src_idx.get(key))
        t = tgt_idx.get(joint, tgt_idx.get(key))
        if s is None or t is None:
            logger.warning(f"No bindPreMatrix slot found for '{joint}'.")
            continue
        try:
            matrix = cmds.getAttr(f"{src_skin}.bindPreMatrix[{s}]")
            if offset_matrix is not None:
                matrix = list(offset_matrix * om.MMatrix(matrix))
            cmds.setAttr(f"{tgt_skin}.bindPreMatrix[{t}]", matrix, type="matrix")
        except Exception as e:
            logger.warning(f"Could not copy bindPreMatrix for '{joint}': {e}")


def _copy_weights_exact(src_skin: str,
                        source_mesh: str,
                        tgt_skin: str,
                        target_mesh: str,
                        n_vtx: int,
                        ) -> None:
    """Copy every weight index to index (both meshes share a vertex count).

    Registered through ``push_undo``: the write is a raw API ``setWeights``,
    which is not a command and never reaches the undo queue on its own - the
    surrounding undo chunk would group the skinCluster creation and leave the
    weights behind. The target's current weights are read first and become the
    undo state, so overwriting an existing skinCluster is reversible too.
    """
    from dw_maya.dw_deformers import dw_skinning
    flat, influences = _read_skin_weights(src_skin, source_mesh, n_vtx)
    old_flat, old_influences = _read_skin_weights(tgt_skin, target_mesh, n_vtx)

    def _write(columns: List[str], values: List[float]) -> None:
        # The target carries the same influence nodes, so the source's column
        # order resolves directly against it.
        dw_skinning.write_influence_columns(tgt_skin,
                                            target_mesh,
                                            n_vtx,
                                            columns,
                                            values,
                                            normalize=False)

    dw_generic_undo.push_undo(functools.partial(_write, influences, flat),
                              functools.partial(_write, old_influences,
                                                old_flat))


# ============================================================================
# SKIN TRANSFER (DemBones result -> pipeline mesh, influences differ by namespace)
# ============================================================================

def _leaf_name(node: str) -> str:
    """Strip dag path and namespace, leaving the bare node name."""
    return node.split("|")[-1].split(":")[-1]


def _resolve_target_joint(short_name: str,
                          exclude: str,
                          target_namespace: Optional[str],
                          ) -> Optional[str]:
    """Find the target joint matching a source influence by short name.

    Args:
        short_name: Namespace-stripped influence name (e.g. ``SSDR_JNT_8``).
        exclude: The source influence's full name, so it can't map to itself.
        target_namespace: When given, look only for ``<ns>:<short_name>`` (or
            the root-namespace name when an empty string is passed). When None,
            search the scene for any joint with that short name.

    Returns:
        The target joint's full name, or None if it can't be resolved uniquely.
    """
    if target_namespace is not None:
        candidate = f"{target_namespace}:{short_name}" if target_namespace else short_name
        return candidate if cmds.objExists(candidate) else None

    matches = cmds.ls(f"*:{short_name}", short_name, type="joint", long=True) or []
    matches = [m for m in matches if m != exclude and _leaf_name(m) == short_name]
    if not matches:
        return None
    if len(matches) > 1:
        logger.warning(
            f"'{short_name}' resolves to {len(matches)} joints {matches}; using "
            f"the first. Pass target_namespace to disambiguate.")
    return matches[0]


def build_influence_map(source_influences: List[str],
                        target_namespace: Optional[str] = None,
                        ) -> Tuple[Dict[str, str], List[str]]:
    """Map each source influence to its target counterpart by short name.

    Only the namespace differs between the two skeletons, so influences are
    paired on their namespace-stripped name.

    Args:
        source_influences: Influences of the source skinCluster, in order.
        target_namespace: Namespace of the target joints. None to auto-search
            the scene by short name; an empty string for the root namespace.

    Returns:
        (mapping src->tgt, list of unresolved source influences).
    """
    mapping: Dict[str, str] = {}
    missing: List[str] = []
    for inf in source_influences:
        tgt = _resolve_target_joint(_leaf_name(inf), inf, target_namespace)
        if tgt:
            mapping[inf] = tgt
        else:
            missing.append(inf)
    return mapping, missing


def _match_scene_joints(solved_joints: List[str],
                        ) -> Tuple[List[str], List[str]]:
    """Pair each generation joint with the scene joint it came from.

    Leaf names alone are NOT enough. A generation import nests the original
    namespace inside its own (``dem009:_SKL_ACC_SHELTER_CURTAIN_I_:BB_M_0_Root``),
    and other rigs in the shot follow the same joint-naming convention - a
    scene with a camera rig also holding a ``BB_M_0_Root`` will hand the
    curtain the camera's root and the mismatch is invisible afterwards.

    So the leading generation namespace is dropped and the remainder matched
    exactly; the leaf name is a fallback for a generation imported flat, and
    then only when the answer is unambiguous.

    Args:
        solved_joints: Influences of the generation's skinCluster.

    Returns:
        (matched scene joints in the given order, unmatched leaf names).
    """
    leaf_index: Dict[str, List[str]] = {}
    for joint in cmds.ls(type="joint", long=True) or []:
        leaf_index.setdefault(_leaf_name(joint), []).append(joint)

    matched: List[str] = []
    missing: List[str] = []
    for inf in solved_joints:
        leaf = inf.split("|")[-1]
        # Exact: everything after the generation's own namespace.
        original = leaf.split(":", 1)[1] if ":" in leaf else leaf
        exact = [j for j in cmds.ls(original, long=True, type="joint") or []
                 if j.split("|")[-1] == original]
        if exact:
            matched.append(exact[0])
            continue

        source_ns = leaf.split(":")[0] if ":" in leaf else ""
        candidates = [j for j in leaf_index.get(_leaf_name(inf), [])
                      if not (source_ns and f"{source_ns}:" in j)]
        if len(candidates) == 1:
            matched.append(candidates[0])
        elif candidates:
            missing.append(f"{_leaf_name(inf)} (ambiguous: "
                           f"{len(candidates)} candidates)")
        else:
            missing.append(_leaf_name(inf))
    return matched, missing


@dw_undo.singleUndoChunk
def copy_skin_to_own_joints(source_mesh: str,
                            target_mesh: str,
                            bind_pose_mesh: Optional[str] = None,
                            replace: bool = True,
                            surface_association: str = "closestPoint",
                            new_skin_name: Optional[str] = None,
                            ) -> Optional[str]:
    """Copy solved weights onto a mesh bound to ITS OWN joints.

    The return leg, and the opposite of :func:`copy_skin_cluster`. That one
    binds the target to the source's own joint nodes, which is right when
    seeding a rest mesh from a generation and badly wrong when sending a solve
    back: the published asset has to be driven by its own rig, not by the
    joints of an imported fbx. Binding to the source's joints leaves the asset
    depending on a `demNNN:` namespace that will be deleted.

    So each source influence is paired to the scene joint of the same leaf
    name, the target is bound to those, and only the WEIGHTS come across.

    The geometric problem this has to solve: with differing vertex counts the
    weights move by ``copySkinWeights``, which pairs vertices by their current
    world positions - but the solved mesh sits in the solve's space while the
    target's undeformed geometry sits in the asset's bind space. So when a
    ``bind_pose_mesh`` is given, the source is moved into the target's bind
    space for the duration of the copy and put back afterwards.

    Args:
        source_mesh: The solved, skinned mesh (an imported generation).
        target_mesh: The published asset mesh.
        bind_pose_mesh: A copy of ``source_mesh`` placed on the target's bind
            pose, used to solve the rigid offset between the two spaces. Not
            needed when both already sit in the same space.
        replace: Delete the target's existing skinCluster first. Leaving this
            off on the return leg is what produces a cluster bound to both
            skeletons at once.
        surface_association: ``copySkinWeights`` association for the differing
            topology case.
        new_skin_name: Name for a newly created target skinCluster.

    Returns:
        The target skinCluster name, or None on failure.
    """
    src_skin = find_skin_cluster(source_mesh)
    if not src_skin:
        logger.error(f"No skinCluster on source mesh '{source_mesh}'.")
        return None

    src_infs = skin_influences(src_skin)
    if not src_infs:
        logger.error(f"skinCluster '{src_skin}' has no influences.")
        return None

    target_infs, missing = _match_scene_joints(src_infs)
    if missing:
        logger.error(
            f"{len(missing)} influence(s) have no counterpart in the scene: "
            f"{missing[:10]}. Aborting rather than binding a partial "
            f"skeleton.")
        return None

    # Derived from the target itself unless overridden: its Orig shape against
    # its drawn shape gives the same transform a hand-placed bind-pose mesh
    # does, with no preparation step for the artist.
    if bind_pose_mesh:
        offset = rigid_transform_between(bind_pose_mesh, source_mesh)
        if offset is None:
            logger.error("Could not solve the bind-pose offset from "
                         f"'{bind_pose_mesh}'. Aborting.")
            return None
        logger.info(f"Bind-space offset taken from '{bind_pose_mesh}'.")
    else:
        offset = derive_bind_offset(target_mesh)

    tgt_skin = find_skin_cluster(target_mesh)

    if tgt_skin and replace:
        logger.info(f"Removing existing skinCluster '{tgt_skin}'.")
        cmds.delete(tgt_skin)
        tgt_skin = None
    if not tgt_skin:
        name = new_skin_name or f"{_leaf_name(target_mesh)}_skinCluster"
        tgt_skin = cmds.skinCluster(target_infs,
                                    target_mesh,
                                    toSelectedBones=True,
                                    obeyMaxInfluences=False,
                                    normalizeWeights=1,
                                    name=name)[0]
        logger.info(f"Bound '{target_mesh}' to {len(target_infs)} of its own "
                    f"joints -> '{tgt_skin}'.")
    else:
        # Compare on full paths: `skinCluster -q -influence` answers with the
        # shortest unique name while the joints were matched as full paths, so
        # a plain set test never hits and every existing influence is re-added
        # - which Maya refuses with "is already attached".
        existing = set()
        for joint in skin_influences(tgt_skin):
            existing.update(cmds.ls(joint, long=True) or [joint])
        for joint in target_infs:
            long_name = (cmds.ls(joint, long=True) or [joint])[0]
            if long_name not in existing:
                cmds.skinCluster(tgt_skin, edit=True, addInfluence=joint,
                                 weight=0.0)
                existing.add(long_name)

    # The bind comes from the SOLVE, not from the asset's authored skin. The
    # point of the return leg is to replace the asset's deformation with the
    # solved one, so every influence takes bindPreMatrix from the generation -
    # offset into the asset's space - and the result reproduces the solve
    # rather than approximating it.
    #
    # It also removes the failure this replaced. Preserving the asset's bind
    # can only cover influences that asset already had; joints added for the
    # solve (contact joints, typically) had to come from somewhere else, and a
    # rig's bindPose node is NOT that somewhere - it holds the current pose,
    # not the authored one. Half the skeleton then binds in modelling space and
    # the rest in set space, which reads as one joint flinging a slab of mesh
    # away. One source for all of them, and the question does not arise.
    _copy_bind_pre_matrices_by_name(src_skin, tgt_skin, src_infs, offset)

    # Both meshes have to sit in one space for a positional lookup. Rather than
    # depend on where the rig happens to be posed, the target is switched off
    # (showing its undeformed geometry) for the duration.
    envelope = None
    try:
        try:
            envelope = cmds.getAttr(f"{tgt_skin}.envelope")
            cmds.setAttr(f"{tgt_skin}.envelope", 0.0)
        except Exception as e:
            logger.warning(f"Could not mute '{tgt_skin}' for the copy: {e}")
        if not transfer_weights_by_surface(src_skin, source_mesh,
                                           tgt_skin, target_mesh, offset):
            logger.warning(
                "Falling back to copySkinWeights; its influence pairing is a "
                "guess, so check the result.")
            moved = _place_in_bind_space(source_mesh, offset) if offset else None
            try:
                cmds.copySkinWeights(
                    sourceSkin=src_skin,
                    destinationSkin=tgt_skin,
                    noMirror=True,
                    surfaceAssociation=surface_association,
                    influenceAssociation=["name", "closestJoint"])
            finally:
                if moved is not None:
                    cmds.xform(moved[0], worldSpace=True, matrix=moved[1])
    finally:
        if envelope is not None:
            cmds.setAttr(f"{tgt_skin}.envelope", envelope)

    logger.info(
        f"Copied weights '{src_skin}' -> '{tgt_skin}' across "
        f"{len(target_infs)} name-matched influences "
        f"({surface_association}).")
    return tgt_skin


def _copy_bind_pre_matrices_by_name(src_skin: str,
                                    tgt_skin: str,
                                    src_influences: List[str],
                                    offset: Optional[List[float]] = None,
                                    ) -> None:
    """Carry the solve's bind matrices onto a skinCluster bound to other joints.

    Like :func:`_copy_bind_pre_matrices`, but the two clusters are bound to
    different nodes - the generation's joints on one side, the asset's own on
    the other - so the slots are paired on the leaf name they share.

    ``offset`` maps the target's bind space into the solve's and is
    pre-multiplied in, exactly as on the inbound leg: Maya deforms with
    ``p * bindPreMatrix * jointWorldMatrix``, so the point is carried into the
    space the solve happened in, deformed there, and the animation is left
    alone.
    """
    import maya.api.OpenMaya as om
    offset_matrix = om.MMatrix(offset) if offset else None

    src_by_leaf = {_leaf_name(name): logical for name, logical
                   in _influence_logical_indices(src_skin).items()}
    tgt_by_leaf = {_leaf_name(name): logical for name, logical
                   in _influence_logical_indices(tgt_skin).items()}

    copied = 0
    missing: List[str] = []
    for inf in src_influences:
        leaf = _leaf_name(inf)
        source_slot = src_by_leaf.get(leaf)
        target_slot = tgt_by_leaf.get(leaf)
        if source_slot is None or target_slot is None:
            missing.append(leaf)
            continue
        try:
            matrix = cmds.getAttr(f"{src_skin}.bindPreMatrix[{source_slot}]")
            if offset_matrix is not None:
                matrix = list(offset_matrix * om.MMatrix(matrix))
            cmds.setAttr(f"{tgt_skin}.bindPreMatrix[{target_slot}]",
                         matrix, type="matrix")
            copied += 1
        except Exception as e:
            logger.warning(f"Could not set bindPreMatrix for '{leaf}': {e}")

    logger.info(f"Installed the solve's bind pose on {copied} influence(s)"
                f"{' with a bind-space offset' if offset_matrix else ''}.")
    if missing:
        logger.warning(
            f"{len(missing)} influence(s) had no matching bind slot: "
            f"{missing[:10]}{' ...' if len(missing) > 10 else ''}. Those keep "
            f"Maya's bind-time value and will not follow the solve.")


def transfer_weights_by_surface(src_skin: str,
                                source_mesh: str,
                                tgt_skin: str,
                                target_mesh: str,
                                offset: Optional[List[float]] = None,
                                ) -> bool:
    """Copy weights vertex to vertex, resolving influences by NAME.

    ``copySkinWeights`` has to be told how to pair influences, and every option
    is a guess when the two skinClusters are bound to different skeletons:
    ``closestJoint`` re-derives the pairing by proximity and smears a dense
    joint cloud, ``oneToOne`` pairs by index and the two clusters do not share
    an ordering - measured at 98% of vertices ending up on the wrong joint.

    The pairing is already known: the influences share leaf names. So the
    weights are read, re-columned by name, and written directly. Geometry is
    matched by closest point on the source surface, then the nearest vertex of
    that face - exact when the target is the source with points removed, which
    is the case this exists for.

    Args:
        src_skin: The generation's skinCluster.
        source_mesh: Its mesh.
        tgt_skin: The asset's skinCluster.
        target_mesh: The asset mesh.
        offset: Maps the target's bind space into the solve's, applied to the
            target points before the lookup.

    Returns:
        True when the weights were written.
    """
    import maya.api.OpenMaya as om
    from dw_maya.dw_deformers import dw_skinning

    n_source = mesh_vertex_count(source_mesh) or 0
    n_target = mesh_vertex_count(target_mesh) or 0
    if not n_source or not n_target:
        logger.error("Could not read vertex counts for the weight transfer.")
        return False

    flat, names = _read_skin_weights(src_skin, source_mesh, n_source)
    columns = len(names)

    # Same joints, different namespaces: pair on the leaf name.
    target_by_leaf = {_leaf_name(i): i for i in skin_influences(tgt_skin)}
    target_columns = [target_by_leaf.get(_leaf_name(n)) for n in names]
    missing = [_leaf_name(n) for n, c in zip(names, target_columns)
               if c is None]
    if missing:
        logger.error(f"No target influence for {missing[:10]}; aborting.")
        return False

    # Matching topology is the ordinary case - the artist did not touch the
    # mesh - and then the correspondence is the vertex index itself. No
    # geometry query, no closest-point tolerance, and it stays exact on a mesh
    # whose surface doubles back on itself.
    if n_source == n_target:
        out = list(flat)
        previous, previous_names = _read_skin_weights(tgt_skin, target_mesh,
                                                      n_target)

        def _write_indexed(cols: List[str], values: List[float]) -> None:
            dw_skinning.write_influence_columns(tgt_skin, target_mesh,
                                                n_target, cols, values,
                                                normalize=False)

        dw_generic_undo.push_undo(
            functools.partial(_write_indexed, target_columns, out),
            functools.partial(_write_indexed, previous_names, previous))
        logger.info(
            f"Transferred weights for {n_target} vertices index to index "
            f"(topologies match) across {columns} name-matched influences.")
        return True

    selection = om.MSelectionList()
    selection.add(source_mesh)
    source_dag = selection.getDagPath(0)
    source_dag.extendToShape()
    source_fn = om.MFnMesh(source_dag)

    selection = om.MSelectionList()
    selection.add(target_mesh)
    target_dag = selection.getDagPath(0)
    target_dag.extendToShape()
    target_points = om.MFnMesh(target_dag).getPoints(om.MSpace.kWorld)

    offset_matrix = om.MMatrix(offset) if offset else None
    out: List[float] = []
    for point in target_points:
        probe = point * offset_matrix if offset_matrix else point
        _, face = source_fn.getClosestPoint(probe, om.MSpace.kWorld)
        best, best_distance = -1, None
        for vertex in source_fn.getPolygonVertices(face):
            d = (source_fn.getPoint(vertex, om.MSpace.kWorld)
                 - probe).length()
            if best_distance is None or d < best_distance:
                best, best_distance = vertex, d
        row = best * columns
        out.extend(flat[row:row + columns])

    previous, _ = _read_skin_weights(tgt_skin, target_mesh, n_target)
    previous_names = skin_influences(tgt_skin)

    def _write(cols: List[str], values: List[float]) -> None:
        dw_skinning.write_influence_columns(tgt_skin, target_mesh, n_target,
                                            cols, values, normalize=False)

    dw_generic_undo.push_undo(
        functools.partial(_write, target_columns, out),
        functools.partial(_write, previous_names, previous))
    logger.info(f"Transferred weights for {n_target} vertices across "
                f"{columns} name-matched influences (vertex to vertex).")
    return True


def _place_in_bind_space(mesh: str, offset: List[float]):
    """Temporarily move a mesh by the inverse of ``offset``.

    ``offset`` maps the target's bind space INTO the solve's space, so its
    inverse brings the solved mesh back to where the target's geometry lives.

    Returns:
        ``(transform, original world matrix)`` to restore, or None on failure.
    """
    import maya.api.OpenMaya as om
    transforms = cmds.ls(mesh, long=True, type="transform") or []
    if not transforms:
        parents = cmds.listRelatives(mesh, parent=True, fullPath=True) or []
        transforms = parents[:1]
    if not transforms:
        logger.warning(f"No transform to move for '{mesh}'.")
        return None

    node = transforms[0]
    try:
        original = cmds.xform(node, query=True, worldSpace=True, matrix=True)
        current = om.MMatrix(original)
        cmds.xform(node, worldSpace=True,
                   matrix=list(current * om.MMatrix(offset).inverse()))
    except Exception as e:
        logger.warning(f"Could not move '{node}' into bind space: {e}")
        return None
    return node, original


def transfer_skin_by_name(source_mesh: str,
                          target_mesh: str,
                          target_namespace: Optional[str] = None,
                          new_skin_name: Optional[str] = None,
                          ) -> Optional[str]:
    """Copy skinning from ``source_mesh`` to ``target_mesh`` by influence name.

    Built for the DemBones-result -> pipeline-mesh case where the two skeletons
    are the same joints under a different namespace. Influences are paired on
    their short name, a skinCluster is built on the target bound to the matching
    joints (in source order), and weights are copied with Maya's
    ``copySkinWeights`` using closest-point surface association - exact when the
    meshes share topology, nearest-point otherwise. Influence association is
    closest-joint, which is robust here since the joints sit at identical world
    positions.

    Args:
        source_mesh: The skinned DemBones-result mesh (transform or shape).
        target_mesh: The pipeline mesh to receive the skinning.
        target_namespace: Namespace of the target joints (None = auto-search by
            short name; "" = root namespace).
        new_skin_name: Optional name for a newly created target skinCluster.

    Returns:
        The target skinCluster name, or None on failure.
    """
    src_skin = find_skin_cluster(source_mesh)
    if not src_skin:
        logger.error(f"No skinCluster found on source mesh '{source_mesh}'.")
        return None

    src_infs = skin_influences(src_skin)
    mapping, missing = build_influence_map(src_infs, target_namespace)
    if missing:
        logger.error(
            f"{len(missing)} influence(s) could not be matched on the target: "
            f"{missing}. Aborting transfer.")
        return None

    target_infs = [mapping[inf] for inf in src_infs]   # keep source order

    tgt_skin = find_skin_cluster(target_mesh)
    if not tgt_skin:
        name = new_skin_name or f"{_leaf_name(target_mesh)}_skinCluster"
        tgt_skin = cmds.skinCluster(target_infs,
                                    target_mesh,
                                    toSelectedBones=True,
                                    normalizeWeights=1,
                                    name=name)[0]
        logger.info(f"Created skinCluster '{tgt_skin}' on '{target_mesh}'.")
    else:
        existing = set(skin_influences(tgt_skin))
        for joint in target_infs:
            if joint not in existing:
                cmds.skinCluster(tgt_skin,
                                 edit=True,
                                 addInfluence=joint,
                                 weight=0.0)

    cmds.copySkinWeights(sourceSkin=src_skin,
                         destinationSkin=tgt_skin,
                         noMirror=True,
                         surfaceAssociation="closestPoint",
                         influenceAssociation=["closestJoint", "oneToOne"])
    logger.info(
        f"Transferred {len(target_infs)} influences '{src_skin}' -> '{tgt_skin}'.")
    return tgt_skin


# ============================================================================
# BIND (prepare the rest mesh so every joint takes part in the solve)
# ============================================================================

@dw_undo.singleUndoChunk
def bind_mesh_to_joints(mesh: str,
                        joints: List[str],
                        max_influences: int = 8,
                        dropoff: float = 4.0,
                        replace: bool = False,
                        name: Optional[str] = None,
                        ) -> Optional[str]:
    """Smooth-bind a mesh to joints, keeping every joint as an influence.

    Written for seeding a solve. Weights are the only coupling between a joint
    and DemBones: a joint with no weight anywhere is invisible to the solver,
    its transform is never fitted, and it comes back with no animation. The
    seed does not have to be good - with ``nWeightsIters > 0`` the solve
    refines it - but it does have to be non-zero.

    Which is why ``removeUnusedInfluence`` is forced off. It defaults to ON in
    ``cmds.skinCluster``, and it prunes, at bind time, every joint the bind
    method gave no weight to: bind 56 joints to a cloth mesh and quietly get 35.

    Args:
        mesh: The rest mesh to bind.
        joints: Joints to bind it to (the root is usually left out - see
            :func:`add_zero_weight_influences`).
        max_influences: Influences per vertex. Match it to the solve's ``nnz``,
            or the seed is narrower than the budget the solve will use.
        dropoff: Weight falloff by distance.
        replace: Delete an existing skinCluster on the mesh first. When False
            an existing one is kept and the joints are added to it.
        name: Name for a newly created skinCluster.

    Returns:
        The skinCluster name, or None on failure.
    """
    if not joints:
        logger.error("No joints given to bind.")
        return None

    skin = find_skin_cluster(mesh)
    if skin and replace:
        logger.info(f"Removing existing skinCluster '{skin}'.")
        cmds.delete(skin)
        skin = None

    if skin:
        existing = set(skin_influences(skin))
        added = [j for j in joints if j not in existing]
        for joint in added:
            cmds.skinCluster(skin, edit=True, addInfluence=joint, weight=0.0)
        logger.info(
            f"Added {len(added)} influence(s) to the existing '{skin}'. They "
            f"carry no weight yet - flood or paint them, or rebind with "
            f"replace=True for a distance-based seed.")
        return skin

    try:
        skin = cmds.skinCluster(joints,
                                mesh,
                                toSelectedBones=True,
                                bindMethod=0,          # closest distance
                                skinMethod=0,          # classic linear
                                normalizeWeights=1,
                                maximumInfluences=max_influences,
                                obeyMaxInfluences=False,
                                removeUnusedInfluence=False,
                                dropoffRate=dropoff,
                                name=name or f"{_leaf_name(mesh)}_skinCluster",
                                )[0]
    except Exception as e:
        logger.error(f"Bind failed on '{mesh}': {e}")
        return None

    bound = skin_influences(skin)
    logger.info(f"Bound '{mesh}' to {len(bound)} of {len(joints)} joints "
                f"(maxInfluences={max_influences}).")
    if len(bound) < len(joints):
        logger.warning(
            f"{len(joints) - len(bound)} joint(s) did not survive the bind "
            f"even with removeUnusedInfluence off - check they are joints and "
            f"not already influencing another mesh.")
    return skin


@dw_undo.singleUndoChunk
def add_zero_weight_influences(mesh: str, joints: List[str]) -> List[str]:
    """Add joints to a mesh's skinCluster carrying no weight.

    For the joints that must be in the file but must not deform: a pipeline
    root, the intermediates between it and the real influences. They make the
    file's joint count match the influence count, which is what DemBones
    insists on, without touching the deformation.

    Args:
        mesh: Skinned mesh.
        joints: Joints to add.

    Returns:
        The joints actually added.
    """
    skin = find_skin_cluster(mesh)
    if not skin:
        logger.error(f"'{mesh}' has no skinCluster to add influences to.")
        return []
    existing = set(skin_influences(skin))
    pending = [j for j in joints if j not in existing]
    if not pending:
        logger.info("Every joint given is already an influence.")
        return []
    return _bind_zero_weight(skin, pending)


# ============================================================================
# SOLVE -> RIG (drive an existing rig from a solved generation)
# ============================================================================

# Constraint types whose targetList tells us which node drives another.
_TARGET_QUERIES = {
    "parentConstraint": "parentConstraint",
    "orientConstraint": "orientConstraint",
    "pointConstraint": "pointConstraint",
}


def driving_control(node: str) -> Optional[str]:
    """The node driving ``node`` through a constraint, if any.

    Read from the constraint's target list rather than from names: a rig's
    control and the joint it drives rarely share a naming rule end to end
    (``RESETFK_M_105_Shelter`` drives ``BB_M_105_Shelter``, but the root is
    ``M_0_HIERARCHY_MANIP_G`` driving ``BB_M_0_Root``), while the connection is
    always there and always right.

    Args:
        node: The driven node, typically a rig joint.

    Returns:
        The driving node, or None when nothing constrains it.
    """
    constraints = cmds.listConnections(node,
                                       source=True,
                                       destination=False,
                                       type="constraint") or []
    for constraint in dict.fromkeys(constraints):
        command = _TARGET_QUERIES.get(cmds.nodeType(constraint))
        if not command:
            continue
        try:
            targets = getattr(cmds, command)(constraint,
                                             query=True,
                                             targetList=True) or []
        except Exception as e:
            logger.warning(f"Could not query '{constraint}': {e}")
            continue
        targets = [t for t in targets if t != node]
        if targets:
            return targets[0]
    return None


def remap_name(node: str,
               find: str,
               replace: str,
               ) -> Optional[str]:
    """Derive a node name by substring substitution, if the result exists.

    The escape hatch for rigs with no constraint to follow: one find/replace
    pair over the whole name, namespace included, is enough for the usual
    convention gap - ``_SKL_ACC_X_:BB_`` -> ``_RIG_ACC_X_:MANIPFK_``.

    Args:
        node: Source node name.
        find: Substring to replace. Empty disables the remap.
        replace: What to put in its place.

    Returns:
        The remapped node when it exists in the scene, else None.
    """
    if not find:
        return None
    leaf = node.split("|")[-1]
    if find not in leaf:
        return None
    candidate = leaf.replace(find, replace)
    found = cmds.ls(candidate) or []
    return found[0] if found else None


def map_solved_to_targets(solved_joints: List[str],
                          to_controls: bool = True,
                          name_remap: Optional[Tuple[str, str]] = None,
                          ) -> Tuple[Dict[str, str], List[str]]:
    """Pair each solved joint with the node that should receive its animation.

    The first hop is always the same: the solved joint is matched to the scene
    joint of the same leaf name (the generation is an import of the same
    skeleton under its own namespace, so leaf names line up). ``to_controls``
    then decides whether to stop there or take a second hop to whatever
    constrains that joint.

    Args:
        solved_joints: Joints from the imported generation.
        to_controls: Resolve on to the rig control driving each joint. False
            targets the joints themselves - the case for a skeleton with no
            control rig over it.
        name_remap: ``(find, replace)`` applied to the scene joint's name to
            derive its control, for rigs that drive their joints by direct
            connection rather than by a constraint. Tried FIRST when given,
            with the constraint lookup as the fallback - never the other way
            round by default, because names lie: on a validated rig the
            drivers were ``MANIPFK_*`` where the convention said ``RESETFK_*``,
            and the root's was ``MANIP_M_0_Root``. An explicit remap is the
            artist overriding that, which is their call to make.

    Returns:
        ({solved joint: target}, list of solved joints left unresolved).
    """
    find, replace = name_remap if name_remap else ("", "")
    index: Dict[str, List[str]] = {}
    for joint in cmds.ls(type="joint", long=True) or []:
        index.setdefault(_leaf_name(joint), []).append(joint)

    mapping: Dict[str, str] = {}
    unresolved: List[str] = []
    for solved in solved_joints:
        # Everything under the generation's own namespace is off limits: that
        # is where the solved joint itself lives.
        solved_root_ns = solved.split(":")[0] if ":" in solved else ""
        candidates = [j for j in index.get(_leaf_name(solved), [])
                      if not (solved_root_ns and f"{solved_root_ns}:" in j)]
        if not candidates:
            unresolved.append(solved)
            continue
        if not to_controls:
            mapping[solved] = candidates[0]
            continue
        control = (remap_name(candidates[0], find, replace)
                   or driving_control(candidates[0]))
        if not control:
            unresolved.append(solved)
            continue
        mapping[solved] = control
    return mapping, unresolved


def _settable_axes(node: str, attribute: str) -> List[str]:
    """Which of x/y/z of an attribute can actually be written on a node."""
    axes = []
    for axis in "xyz":
        try:
            if cmds.getAttr(f"{node}.{attribute}{axis.upper()}", settable=True):
                axes.append(axis)
        except Exception:
            continue
    return axes


_ANIM_CHANNELS = ["translateX", "translateY", "translateZ",
                  "rotateX", "rotateY", "rotateZ"]


def _copy_animation(source: str,
                    target: str,
                    start: int,
                    end: int,
                    ) -> int:
    """Copy a node's anim curves onto another, channel by channel.

    Valid only when the two share a skeleton: an imported generation is the
    same joints in the same hierarchy with the same orientations, so their
    local values mean the same thing and can move across as they are.

    Returns:
        The number of channels copied.
    """
    copied = 0
    for channel in _ANIM_CHANNELS:
        try:
            if not cmds.getAttr(f"{target}.{channel}", settable=True):
                continue
            if not cmds.copyKey(source, attribute=channel, time=(start, end)):
                continue
            cmds.pasteKey(target,
                          attribute=channel,
                          option="replaceCompletely")
            copied += 1
        except Exception as e:
            logger.warning(f"Could not copy '{channel}' to '{target}': {e}")
    return copied


def channel_target(scene_joint: str,
                   channel: str,
                   control: Optional[str] = None,
                   ) -> Optional[str]:
    """Which node to write one channel on: the driving control, or the joint.

    Resolving per node is not enough, because a rig does not necessarily drive
    every channel the same way. The curtain rig is the ordinary case: its FK
    controls carry rotation into the joints through an ``orientConstraint``
    and have their translate **locked**, while the joints' own translate has no
    input at all. A solve that translates its bones - which a cloth solve
    always does, by 200 units here - therefore has to reach the joint directly
    while rotation still goes through the control.

    Args:
        scene_joint: The asset joint the solved joint corresponds to.
        channel: Attribute name, e.g. ``rotateX``.
        control: The joint's driving control, when already resolved.

    Returns:
        The node to write, or None when the channel is driven by something
        that cannot be fed and the value would be silently dropped.
    """
    plug = f"{scene_joint}.{channel}"
    constrained = cmds.listConnections(plug, source=True, destination=False,
                                       type="constraint") or []
    if constrained:
        driver = control or driving_control(scene_joint)
        if driver and cmds.getAttr(f"{driver}.{channel}", settable=True):
            return driver
        return None
    try:
        if cmds.getAttr(plug, settable=True):
            return scene_joint
    except Exception:
        pass
    return None


def _correct_translation(pairs: List[Tuple[str, str, str]]) -> int:
    """Shift each control's translate curves so its joint lands on the solve.

    Solved for, not derived. The value a control needs is its joint's motion
    expressed in the control's own parent space, and that space is whatever
    the rig happens to be - an offset group, a chain of them, or something
    with rotation in it. Two attempts to compute the shift from rest values
    (the joint's own, then the offset group's) were 300 and 428 units wrong
    respectively, because each assumed a relationship the rig does not owe us.

    So the error is measured instead: at the current frame, how far is the
    joint from where the solve puts it, converted into the control's parent
    space through ``parentInverseMatrix``. The residual was constant across
    the range, which is what makes a single correction valid everywhere.

    Args:
        pairs: ``(solved joint, scene joint, control)`` triples, with the
            curves already connected and the scene at the rest frame.

    Returns:
        The number of controls corrected.
    """
    import maya.api.OpenMaya as om
    corrected = 0
    for solved, joint, control in pairs:
        if not control:
            continue
        try:
            want = om.MPoint(cmds.xform(solved, query=True, worldSpace=True,
                                        translation=True))
            have = om.MPoint(cmds.xform(joint, query=True, worldSpace=True,
                                        translation=True))
            if (want - have).length() < 1e-6:
                continue
            parent_inverse = om.MMatrix(
                cmds.getAttr(f"{control}.parentInverseMatrix[0]"))
            delta = (want * parent_inverse) - (have * parent_inverse)
            for axis, value in zip("XYZ", (delta.x, delta.y, delta.z)):
                channel = f"translate{axis}"
                curves = cmds.listConnections(f"{control}.{channel}",
                                              source=True, destination=False,
                                              type="animCurve") or []
                if curves:
                    cmds.keyframe(curves[0], edit=True, relative=True,
                                  valueChange=value)
                elif cmds.getAttr(f"{control}.{channel}", settable=True):
                    cmds.setAttr(f"{control}.{channel}",
                                 cmds.getAttr(f"{control}.{channel}") + value)
            corrected += 1
        except Exception as e:
            logger.warning(f"Could not correct '{control}': {e}")
    return corrected


def _clear_animation(nodes: List[str]) -> int:
    """Delete anim curves driving a set of nodes.

    Relinking captures each target's REST value, so a target that still holds
    animation from a previous transfer would have its "rest" read off that
    animation and the offsets would compound - which is how a retarget quietly
    drifts further every time it is re-run.
    """
    curves = []
    for node in nodes:
        curves += cmds.listConnections(node, source=True, destination=False,
                                       type="animCurve") or []
    curves = sorted(set(curves))
    if curves:
        cmds.delete(curves)
    return len(curves)


def _relink_animation(source: str,
                      scene_joint: str,
                      control: Optional[str] = None,
                      duplicate: bool = True,
                      ) -> Tuple[int, List[str]]:
    """Drive a rig from a solved joint's existing anim curves, per channel.

    No sampling and no baking: the solved curve itself is connected to
    whichever node actually owns that channel - see :func:`channel_target`.
    Valid because the generation is an import of the same skeleton, so its
    local values mean the same thing on the asset's.

    Args:
        source: The generation joint holding the anim curves.
        scene_joint: The asset joint it corresponds to.
        control: The joint's driving control, when already resolved.
        duplicate: Copy the curve so the asset owns it. Without this the rig
            is driven by curves belonging to the imported generation, and
            deleting that generation takes the animation with it.

    Returns:
        (channels connected, channels that had a curve but nowhere to put it).
    """
    connected = 0
    dropped: List[str] = []
    for channel in _ANIM_CHANNELS:
        try:
            curves = cmds.listConnections(f"{source}.{channel}", source=True,
                                          destination=False,
                                          type="animCurve") or []
            if not curves:
                continue
            target = channel_target(scene_joint, channel, control)
            if not target:
                dropped.append(channel)
                continue
            curve = curves[0]
            if duplicate:
                curve = cmds.duplicate(
                    curve, name=f"{_leaf_name(target)}_{channel}")[0]

            cmds.connectAttr(f"{curve}.output", f"{target}.{channel}",
                             force=True)
            connected += 1
        except Exception as e:
            logger.warning(f"Could not relink '{channel}' to '{target}': {e}")
    return connected, dropped


def _rig_is_one_to_one(mapping: Dict[str, str],
                       tolerance: float = 0.01,
                       ) -> Tuple[bool, float]:
    """Do the controls hold the same local values as the joints they drive?

    The precondition for relinking. Compared on the joints' current state, so
    it answers the structural question - is this a plain FK rig - rather than
    anything about the animation.

    Returns:
        (one_to_one, median absolute rotate difference in degrees).
    """
    diffs = []
    for solved, control in mapping.items():
        joints, _ = _match_scene_joints([solved])
        if not joints:
            continue
        try:
            joint_rot = cmds.getAttr(f"{joints[0]}.rotate")[0]
            control_rot = cmds.getAttr(f"{control}.rotate")[0]
        except Exception:
            continue
        # 360-degree wraps are the same pose, not a mismatch.
        deltas = []
        for a, b in zip(joint_rot, control_rot):
            d = abs(a - b) % 360.0
            deltas.append(min(d, 360.0 - d))
        diffs.append(max(deltas))
    if not diffs:
        return False, 0.0
    diffs.sort()
    median = diffs[len(diffs) // 2]
    return median <= tolerance, median


@dw_viewportOff.viewportOff
@dw_undo.singleUndoChunk
def transfer_solve_animation(solved_joints: List[str],
                             start: int,
                             end: int,
                             to_controls: bool = True,
                             rest_frame: Optional[int] = None,
                             method: str = "auto",
                             name_remap: Optional[Tuple[str, str]] = None,
                             dry_run: bool = False,
                             ) -> Dict[str, str]:
    """Hand a solved generation's animation back to the rig it came from.

    Two mechanisms, because the two targets are not the same problem:

    - **Controls** (``to_controls=True``): constrain-bake-release. A control
      and the joint it drives sit at different places, in different
      orientations, under different parents, so its anim curves are NOT the
      solved joint's curves. Constraining with ``maintainOffset`` at the rest
      frame captures that relationship exactly and the bake turns it into the
      control's own keys. Channels the rig locks are skipped on both the
      constraint and the bake, and reported - what the solve needed from a
      locked channel is lost, and that is a property of the rig.
    - **Joints** (``to_controls=False``): a direct anim-curve copy. The
      generation is an import of the same skeleton, so local values transfer
      exactly - no baking, no constraints, no sampling error. Use it for a
      plain skeleton with no control rig over it. If the joints ARE driven by
      constraints, keys set on them will not win; target the controls instead.

    Args:
        solved_joints: The imported generation's joints.
        start: First frame.
        end: Last frame.
        to_controls: Target the driving controls rather than the joints.
        rest_frame: Frame at which to capture the control offsets (controls
            mode only). Defaults to ``start``, where the solve's bind pose is.
        dry_run: Resolve and log the pairing without touching anything.

    Returns:
        The {solved joint: target} pairing that was transferred (or would be).
    """
    mapping, unresolved = map_solved_to_targets(solved_joints, to_controls,
                                               name_remap)
    what = "rig controls" if to_controls else "scene joints"
    logger.info(f"Resolved {len(mapping)} of {len(solved_joints)} solved "
                f"joints to {what}.")
    if unresolved:
        logger.warning(
            f"{len(unresolved)} solved joint(s) unresolved: "
            f"{[_leaf_name(j) for j in unresolved[:10]]}"
            f"{' ...' if len(unresolved) > 10 else ''}")
    if dry_run or not mapping:
        return mapping

    if not to_controls:
        total = 0
        for solved, target in mapping.items():
            total += _copy_animation(solved, target, start, end)
        logger.info(f"Copied {total} channel(s) onto {len(mapping)} joint(s).")
        return mapping

    # An FK control whose local values ARE its joint's needs no world-space
    # work at all: the solved curve can drive it directly. Constrain-and-bake
    # re-derives that relationship per frame through the whole chain, and the
    # error compounds down it - measured at 0.06 units of joint drift at the
    # rest frame growing to 86 by the end of the range on a production rig.
    if method in ("auto", "relink"):
        one_to_one, median = _rig_is_one_to_one(mapping)
        if one_to_one or method == "relink":
            if not one_to_one:
                logger.warning(
                    f"Relinking was asked for but the controls do not hold "
                    f"their joints' local values (median {median:.3f} deg "
                    f"apart). The result will be wrong; 'bake' is the mode "
                    f"for this rig.")
            # Both the rest capture and the solve's own rest pose are read at
            # this frame, so get there before anything is connected.
            cmds.currentTime(start if rest_frame is None else rest_frame)

            pairs = []
            targets = []
            for solved, control in mapping.items():
                joints, _ = _match_scene_joints([solved])
                if not joints:
                    continue
                pairs.append((solved, joints[0], control))
                targets += [joints[0], control]
            cleared = _clear_animation(sorted(set(targets)))
            if cleared:
                logger.info(f"Cleared {cleared} existing anim curve(s) from "
                            f"the targets before relinking.")

            total = 0
            dropped: Dict[str, int] = {}
            for solved, joint, control in pairs:
                count, missed = _relink_animation(solved, joint, control)
                total += count
                for channel in missed:
                    dropped[channel] = dropped.get(channel, 0) + 1
            corrected = _correct_translation(pairs)
            logger.info(
                f"Relinked {total} channel(s) across {len(mapping)} joint(s) - "
                f"the solved curves drive the rig directly, with no baking. "
                f"{corrected} control(s) had their translation re-based into "
                f"the rig's own parent space.")
            if dropped:
                logger.warning(
                    f"The rig has nowhere to put these solved channels, so "
                    f"they are lost: {dropped}. A rotation-only control with "
                    f"a locked translate cannot carry a solve that translates "
                    f"its bones; the joint itself has to take it.")
            return mapping
        logger.info(
            f"The controls do not mirror their joints (median {median:.3f} "
            f"deg apart), so the animation is baked through constraints "
            f"instead of relinked.")

    if rest_frame is None:
        rest_frame = start
    cmds.currentTime(rest_frame)

    constraints: List[str] = []
    controls: List[str] = []
    channels: List[str] = []
    locked_report: List[str] = []
    try:
        for solved, control in mapping.items():
            translate_axes = _settable_axes(control, "translate")
            rotate_axes = _settable_axes(control, "rotate")
            if not translate_axes and not rotate_axes:
                logger.warning(f"'{control}' is fully locked - skipped.")
                continue
            if len(translate_axes) < 3 or len(rotate_axes) < 3:
                locked_report.append(_leaf_name(control))

            constraint = cmds.parentConstraint(
                solved,
                control,
                maintainOffset=True,
                skipTranslate=[a for a in "xyz" if a not in translate_axes]
                or "none",
                skipRotate=[a for a in "xyz" if a not in rotate_axes]
                or "none")
            constraints.append(constraint[0])
            controls.append(control)
            channels += [f"translate{a.upper()}" for a in translate_axes]
            channels += [f"rotate{a.upper()}" for a in rotate_axes]

        if not controls:
            logger.error("No control could be constrained; nothing to bake.")
            return {}

        if locked_report:
            logger.warning(
                f"{len(locked_report)} control(s) have locked channels the "
                f"solve may have needed: {locked_report[:10]}"
                f"{' ...' if len(locked_report) > 10 else ''}")

        cmds.bakeResults(controls,
                         simulation=True,
                         time=(start, end),
                         sampleBy=1,
                         disableImplicitControl=True,
                         preserveOutsideKeys=False,
                         sparseAnimCurveBake=False,
                         attribute=sorted(set(channels)))
        logger.info(f"Baked {len(controls)} control(s) over [{start}, {end}].")
    finally:
        if constraints:
            existing = cmds.ls(constraints) or []
            if existing:
                cmds.delete(existing)

    return mapping


_TRANSFORM_CHANNELS = [
    "translateX", "translateY", "translateZ",
    "rotateX", "rotateY", "rotateZ",
    "scaleX", "scaleY", "scaleZ",
]


@dw_viewportOff.viewportOff
def bake_target_skeleton(target_mesh: str,
                         start: int,
                         end: int,
                         clean_constraints: bool = True,
                         ) -> List[str]:
    """Bake the target skinCluster's joints so they no longer depend on the
    source skeleton.

    After a name-based skin transfer the target joints are usually still driven
    by the source bones (a connection or constraint), so deleting the source
    breaks the result. Baking over the frame range replaces that drive with the
    skeleton's own anim curves - ``cmds.bakeResults`` disconnects the driven
    inputs as it keys - making the target self-contained and the source safe to
    delete.

    Args:
        target_mesh: The skinned pipeline mesh whose skeleton to bake.
        start: First frame to bake.
        end: Last frame to bake.
        clean_constraints: Delete any leftover constraint nodes parented under
            the joints after baking.

    Returns:
        The list of baked joints (empty on failure).
    """
    skin = find_skin_cluster(target_mesh)
    if not skin:
        logger.error(f"No skinCluster found on '{target_mesh}'; nothing to bake.")
        return []

    joints = skin_influences(skin)
    if not joints:
        logger.error(f"skinCluster '{skin}' has no influences to bake.")
        return []

    cmds.bakeResults(joints,
                     simulation=True,
                     time=(start, end),
                     sampleBy=1,
                     disableImplicitControl=True,
                     preserveOutsideKeys=False,
                     sparseAnimCurveBake=False,
                     attribute=_TRANSFORM_CHANNELS)

    if clean_constraints:
        for joint in joints:
            cons = cmds.listRelatives(joint,
                                      children=True,
                                      type="constraint",
                                      fullPath=True) or []
            if cons:
                cmds.delete(cons)

    logger.info(
        f"Baked {len(joints)} joints on '{target_mesh}' over [{start}, {end}]; "
        f"target skeleton is now independent of the source.")
    return joints


# ============================================================================
# TOPOLOGY VALIDATION
# ============================================================================

def mesh_vertex_count(mesh: str) -> Optional[int]:
    """Vertex count of a mesh transform/shape, or None on failure."""
    try:
        return cmds.polyEvaluate(mesh, vertex=True)
    except Exception:
        return None


def _ensure_alembic_plugin() -> None:
    if not cmds.pluginInfo("AbcImport", query=True, loaded=True):
        cmds.loadPlugin("AbcImport")


def alembic_vertex_counts(abc_path: str) -> List[int]:
    """Vertex count of every mesh inside an .abc, read from the file itself.

    The scene mesh an AlembicNode feeds is NOT proof of what the file holds -
    points can be deleted downstream of the node, or the mesh edited after the
    cache was written. Both scene meshes then agree with each other while the
    file disagrees with both, the UI check passes, and the solve dies on a
    vertex count mismatch. So the file is opened for real: imported into a
    throwaway namespace, counted, and deleted again.

    Args:
        abc_path: Path to the .abc cache.

    Returns:
        One count per mesh found, in import order. Empty when the file cannot
        be read - the caller should treat that as "unknown", not as a mismatch.
    """
    if not abc_path or not os.path.isfile(abc_path):
        return []

    namespace = _unique_namespace("dembones_abccheck")
    new_nodes = []
    # The import and its cleanup are a query, not an edit: keep them off the
    # undo queue entirely, or a Ctrl+Z after the solve would bring the whole
    # temporary cache back into the scene.
    undo_state = cmds.undoInfo(query=True, state=True)
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        _ensure_alembic_plugin()
        new_nodes = cmds.file(abc_path,
                              i=True,
                              type="Alembic",
                              namespace=namespace,
                              mergeNamespacesOnClash=False,
                              returnNewNodes=True) or []
        meshes = cmds.ls(new_nodes, type="mesh", long=True) or []
        return [n for n in (mesh_vertex_count(m) for m in meshes)
                if n is not None]
    except Exception as e:
        logger.warning(f"Could not read vertex counts from '{abc_path}': {e}")
        return []
    finally:
        try:
            existing = cmds.ls(new_nodes) or []
            if existing:
                cmds.delete(existing)
            if cmds.namespace(exists=namespace):
                cmds.namespace(removeNamespace=namespace,
                               deleteNamespaceContent=True)
        except Exception as e:
            logger.warning(f"Could not clean up '{namespace}': {e}")
        cmds.undoInfo(stateWithoutFlush=undo_state)


def validate_topology(target_mesh: str,
                      source_mesh: Optional[str] = None,
                      ) -> Tuple[Optional[int], Optional[int], bool]:
    """Compare the target (rest) mesh vert count against the source (abc) mesh.

    When ``source_mesh`` is empty we can only return the target count and
    ``valid=True`` (nothing to compare against yet).

    Args:
        target_mesh: The rest mesh that will carry the skinCluster.
        source_mesh: The abc-driven deformed mesh the solve targets.

    Returns:
        (target_count, source_count, valid)
    """
    target_n = mesh_vertex_count(target_mesh)
    source_n = mesh_vertex_count(source_mesh) if source_mesh else None

    if target_n is None:
        return None, source_n, False
    if source_n is None:
        # Nothing to compare; treat as provisionally valid.
        return target_n, None, True
    return target_n, source_n, target_n == source_n


def create_rest_duplicate(source_mesh: str,
                          frame: Optional[int] = None,
                          ) -> str:
    """Duplicate the source mesh at ``frame`` to make a static rest mesh.

    The duplicate carries no upstream graph (no AlembicNode), so it stays put at
    the sampled frame - exactly the non-animated rest geometry DemBones wants
    for ``-i``.

    Args:
        source_mesh: The abc-driven deformed mesh.
        frame: Frame to sample (the alembic's first frame). When None the
            current time is used.

    Returns:
        The new rest mesh transform name.
    """
    if frame is not None:
        try:
            cmds.currentTime(frame)
        except Exception as e:
            logger.warning(f"Could not set time to {frame}: {e}")

    short = source_mesh.split("|")[-1].split(":")[-1]
    dup = cmds.duplicate(source_mesh,
                         name=f"{short}_rest",
                         returnRootsOnly=True)[0]
    # Make it fully static: drop any construction history that came along.
    try:
        cmds.delete(dup, constructionHistory=True)
    except Exception:
        pass
    return dup


# ============================================================================
# PATHS / FRAME RANGE
# ============================================================================

def timeline_range() -> Tuple[int, int]:
    """Return Maya's current playback range (start, end)."""
    start = int(cmds.playbackOptions(query=True, minTime=True))
    end = int(cmds.playbackOptions(query=True, maxTime=True))
    return start, end


def default_output_dir() -> str:
    """Default solve output dir: <project>/cache/dembones, tempdir fallback."""
    try:
        root = cmds.workspace(query=True, rootDirectory=True)
        if root:
            out = os.path.join(root, "cache", "dembones")
            os.makedirs(out, exist_ok=True)
            return out
    except Exception as e:
        logger.warning(f"Could not resolve project output dir: {e}")
    out = os.path.join(tempfile.gettempdir(), "dembones")
    os.makedirs(out, exist_ok=True)
    return out


# ============================================================================
# FBX EXPORT (the init -i file)
# ============================================================================

def _ensure_fbx_plugin() -> None:
    if not cmds.pluginInfo("fbxmaya", query=True, loaded=True):
        cmds.loadPlugin("fbxmaya")


def _long_name(node: str) -> str:
    """Full dag path of a node, or the name unchanged when it can't be found."""
    found = cmds.ls(node, long=True) or []
    return found[0] if found else node


def non_influence_ancestors(joints: List[str]) -> List[str]:
    """Joints pulled into an FBX export as ancestors without being influences.

    Selecting a joint is not enough to export it alone: FBX preserves the
    hierarchy, so every joint above it comes along. A pipeline root joint that
    exists only to give the skeleton a single parent therefore lands in the file
    while the skinCluster has never heard of it - and DemBones refuses the pair
    with "Scene has more joints than skinCluster has: 16/15".

    Args:
        joints: The influence joints being exported.

    Returns:
        The extra joints, ordered from the deepest upwards.
    """
    known = {_long_name(j) for j in joints}
    extra: List[str] = []
    for joint in joints:
        node = _long_name(joint)
        while True:
            parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
            if not parents:
                break
            node = parents[0]
            if cmds.nodeType(node) != "joint":
                continue   # a group in between - keep climbing
            if node not in known and node not in extra:
                extra.append(node)
    return extra


@dw_undo.singleUndoChunk
def export_target_fbx(mesh: str,
                      out_fbx: str,
                      with_rig: bool,
                      joints: Optional[List[str]] = None,
                      include_ancestors: bool = True,
                      ) -> str:
    """Export the rest mesh (optionally with its joints + skinCluster) to FBX.

    Args:
        mesh: Rest mesh (the non-animated target mesh).
        out_fbx: Destination .fbx path.
        with_rig: When True, export skin + skeleton; else mesh-only geometry.
        joints: Joints to include with the rig (defaults to skin influences).
        include_ancestors: Bind any joint the export drags in as an ancestor
            (a pipeline root, typically) to the skinCluster at weight 0.0 for
            the duration of the export, so the file's joint count matches the
            influence count. The influences are restored afterwards - the
            artist's skinCluster is left exactly as it was.

    Returns:
        The output path written.
    """
    _ensure_fbx_plugin()
    out_fbx = out_fbx.replace("\\", "/")

    # The selection is exported LITERALLY: descendants are not pulled in.
    # Default FBX behaviour is the opposite, and it is what puts a whole 57-joint
    # skeleton in a file that should hold 16 - selecting the root joint would
    # otherwise drag in every joint under it. Ancestors are still written (FBX
    # needs them to place a node), which is what `include_ancestors` handles.
    mel.eval("FBXExportIncludeChildren -v false")

    # Shapes come along explicitly: with children excluded, do not rely on the
    # transform alone carrying its geometry.
    selection = [mesh] + (cmds.listRelatives(mesh,
                                             shapes=True,
                                             fullPath=True) or [])
    borrowed: List[str] = []
    skin = None
    if with_rig:
        if joints is None:
            joints = find_joints_from_mesh(mesh)
        selection += joints

        skin = find_skin_cluster(mesh)
        if include_ancestors and skin and joints:
            borrowed = _bind_zero_weight(skin, non_influence_ancestors(joints))
            selection += borrowed

        mel.eval("FBXExportSkins -v true")
        mel.eval("FBXExportSkeletonDefinitions -v true")
    else:
        mel.eval("FBXExportSkins -v false")

    try:
        cmds.select(selection, replace=True)
        # Bake nothing here; the init FBX is a static rest pose.
        mel.eval("FBXExportInAscii -v false")
        mel.eval(f'FBXExport -f "{out_fbx}" -s')
    finally:
        if skin and borrowed:
            _unbind_influences(skin, borrowed)

    if with_rig and joints:
        # The two numbers DemBones compares: joints written vs influences bound.
        logger.info(
            f"Exported {len(joints) + len(borrowed)} joints "
            f"({len(joints)} influences + {len(borrowed)} ancestor(s) bound at "
            f"weight 0).")
    logger.info(f"Exported target FBX -> {out_fbx} (with_rig={with_rig})")
    return out_fbx


def _bind_zero_weight(skin_cluster: str, joints: List[str]) -> List[str]:
    """Add joints to a skinCluster at weight 0 (no effect on the deformation).

    Returns:
        The joints actually added - the ones to hand back to
        :func:`_unbind_influences` once the export is done.
    """
    added: List[str] = []
    for joint in joints:
        try:
            cmds.skinCluster(skin_cluster,
                             edit=True,
                             addInfluence=joint,
                             weight=0.0)
            added.append(joint)
        except Exception as e:
            logger.warning(f"Could not add '{joint}' to '{skin_cluster}': {e}")
    if added:
        logger.info(
            f"Bound {len(added)} non-influence ancestor joint(s) at weight 0 "
            f"for the export ({', '.join(_leaf_name(j) for j in added)}); "
            f"DemBones needs the file's joint count to match the influence "
            f"count. They are removed again afterwards.")
    return added


def _unbind_influences(skin_cluster: str, joints: List[str]) -> None:
    """Remove influences previously added by :func:`_bind_zero_weight`."""
    for joint in joints:
        try:
            cmds.skinCluster(skin_cluster,
                             edit=True,
                             removeInfluence=joint)
        except Exception as e:
            logger.warning(
                f"Could not remove '{joint}' from '{skin_cluster}': {e}")


# ============================================================================
# EXE ARGUMENT BUILDING
# ============================================================================

# UI param key -> DemBones CLI flag. Only emitted when present in the params.
_PARAM_FLAGS = {
    "nBones":           "-b",
    "nIters":           "-n",
    "nInitIters":       "--nInitIters",
    "nTransIters":      "--nTransIters",
    "nWeightsIters":    "--nWeightsIters",
    "nnz":              "--nnz",
    "weightsSmooth":    "--weightsSmooth",
    "weightsSmoothStep": "--weightsSmoothStep",
    "transAffine":      "--transAffine",
    "transAffineNorm":  "--transAffineNorm",
    "bindUpdate":       "--bindUpdate",
    "patience":         "--patience",
    "tolerance":        "--tolerance",
}


def build_args(abc_path: str,
               init_fbx: str,
               out_fbx: str,
               params: Dict,
               use_rig: bool,
               ) -> List[str]:
    """Build the DemBones.exe argument list.

    Args:
        abc_path: Animated cache (-a).
        init_fbx: Rest geometry FBX, optionally with bones/skin (-i).
        out_fbx: Output FBX (-o).
        params: UI param dict (keys from ``_PARAM_FLAGS``).
        use_rig: When True the init already has bones; drop -b so DemBones
            infers the bone count from the rig instead of re-clustering.

    Returns:
        Argument list (without the exe itself). Each entry is a single
        ``flag=value`` token - DemBones' Windows parser requires the ``=`` form
        (``-a=path``, ``--nnz=8``), not space-separated pairs. Paths are NOT
        wrapped in literal quotes here: QProcess quotes any argument containing
        spaces when it builds the command line, so embedding quotes would
        double-quote and break the path.
    """
    args: List[str] = [
        f"-a={abc_path.replace(chr(92), '/')}",
        f"-i={init_fbx.replace(chr(92), '/')}",
        f"-o={out_fbx.replace(chr(92), '/')}",
    ]
    for key, flag in _PARAM_FLAGS.items():
        if key == "nBones" and use_rig:
            # Let the solver infer bone count from the supplied rig.
            continue
        if key in params and params[key] is not None:
            args.append(f"{flag}={params[key]}")
    return args


# ============================================================================
# GENERATIONS (fbx + sidecar json)
# ============================================================================

def next_generation_index(out_dir: str) -> int:
    """Return the next free leading number for a generation file.

    Generations are named ``NNN_<...>.fbx`` so they always sort the same way
    and map to a stable ``demNNN`` namespace on import. This scans existing
    files and returns ``max(NNN) + 1`` (1 when the dir is empty).
    """
    max_n = 0
    if out_dir and os.path.isdir(out_dir):
        for fbx in glob.glob(os.path.join(out_dir, "*.fbx")):
            m = re.match(r"(\d+)_", os.path.basename(fbx))
            if m:
                max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def sidecar_path(fbx_path: str) -> str:
    """Return the sidecar .json path for a generation fbx."""
    return os.path.splitext(fbx_path)[0] + ".json"


def write_sidecar(fbx_path: str, meta: Dict) -> str:
    """Write a generation's metadata next to its fbx."""
    path = sidecar_path(fbx_path)
    try:
        with open(path, "w") as fh:
            json.dump(meta, fh, indent=2)
    except Exception as e:
        logger.error(f"Failed to write sidecar '{path}': {e}")
    return path


def log_path(fbx_path: str) -> str:
    """Return the .log path for a generation fbx."""
    return os.path.splitext(fbx_path)[0] + ".log"


def write_log(fbx_path: str, text: str) -> Optional[str]:
    """Dump the exe output next to the generation fbx.

    Written whether the solve succeeded or not - on failure it is usually the
    only record of why, since the UI log view may have been hidden.
    """
    path = log_path(fbx_path)
    try:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(path, "w") as fh:
            fh.write(text)
        return path
    except Exception as e:
        logger.error(f"Failed to write solve log '{path}': {e}")
        return None


def read_sidecar(fbx_path: str) -> Dict:
    """Read a generation's sidecar metadata (empty dict if missing/broken)."""
    path = sidecar_path(fbx_path)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r") as fh:
            return json.load(fh)
    except Exception as e:
        logger.warning(f"Failed to read sidecar '{path}': {e}")
        return {}


def scan_generations(out_dir: str) -> List[Dict]:
    """List solved generations in ``out_dir`` as metadata dicts.

    Only FBX files that have a sidecar json are returned - that is the solve
    output. Intermediate exports (the ``_rest`` init FBX, manual target dumps)
    have no sidecar and are skipped, so the list shows decompositions only.

    Each dict carries at least ``fbx`` (full path) and ``name`` plus whatever
    the sidecar stored (params, range, rmse).
    """
    results: List[Dict] = []
    if not out_dir or not os.path.isdir(out_dir):
        return results
    for fbx in sorted(glob.glob(os.path.join(out_dir, "*.fbx"))):
        meta = read_sidecar(fbx)
        if not meta:
            continue  # no sidecar -> not a solve output
        meta["fbx"] = fbx
        meta.setdefault("name", os.path.splitext(os.path.basename(fbx))[0])
        results.append(meta)
    return results


def _unique_namespace(base: str) -> str:
    """Return ``base`` or ``base_1``/``base_2``... if it already exists."""
    if not cmds.namespace(exists=base):
        return base
    i = 1
    while cmds.namespace(exists=f"{base}_{i}"):
        i += 1
    return f"{base}_{i}"


def import_generation(fbx_path: str,
                      namespace: Optional[str] = None,
                      group_under_root: bool = True,
                      ) -> List[str]:
    """Import a solved FBX (joints + skin + anim) back into the scene.

    The import goes into a short namespace (``dem001``, ``dem002``, ...) so a
    same-named mesh/joints already in the scene don't get merged - that merge is
    why a bare ``FBXImport`` looked like it skipped the mesh.

    Args:
        fbx_path: Generation fbx to import.
        namespace: Target namespace. When None it's derived from the file's
            leading number (``001_...fbx`` -> ``dem001``). Made unique if taken.
        group_under_root: Parent the imported nodes under one transform so the
            artist can place the whole result in local space.

    Returns:
        The newly created top-level nodes.
    """
    _ensure_fbx_plugin()
    fbx_path = fbx_path.replace("\\", "/")

    if namespace is None:
        m = re.match(r"(\d+)_", os.path.basename(fbx_path))
        namespace = f"dem{int(m.group(1)):03d}" if m else "dem001"
    namespace = _unique_namespace(namespace)

    # Make sure the FBX importer adds nodes (rather than updating existing).
    try:
        mel.eval("FBXImportMode -v add")
        mel.eval("FBXImportSkins -v true")
    except Exception:
        pass

    new_nodes = cmds.file(fbx_path,
                          i=True,
                          type="FBX",
                          namespace=namespace,
                          mergeNamespacesOnClash=False,
                          returnNewNodes=True,
                          ignoreVersion=True) or []

    roots = cmds.ls(new_nodes, assemblies=True) or []
    if group_under_root and roots:
        root = cmds.group(roots, name=f"{namespace}_GRP")
        return [root]
    return roots


# ============================================================================
# SOLVE RUNNER (non-blocking QProcess wrapper)
# ============================================================================

class SolveRunner(QtCore.QObject):
    """Run DemBones.exe via QProcess so the UI stays responsive.

    stdout and stderr are merged, so the exe's error messages arrive through
    ``log`` like everything else - they are the only explanation of a non-zero
    exit code, and worth keeping rather than only displaying.

    Signals
    -------
    log(str)       a line of stdout/stderr from the exe.
    finished(int)  process exit code (0 = success, -1 = never started).
    """

    log = QtCore.Signal(str)
    finished = QtCore.Signal(int)

    # QProcess.ProcessError -> what actually went wrong, in artist terms.
    _ERROR_REASONS = {
        QtCore.QProcess.FailedToStart:
            "The executable could not be started - wrong path, missing "
            "permissions, or a DLL it depends on is missing.",
        QtCore.QProcess.Crashed:
            "The executable crashed.",
        QtCore.QProcess.Timedout: "The process timed out.",
        QtCore.QProcess.WriteError: "Could not write to the process.",
        QtCore.QProcess.ReadError: "Could not read from the process.",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._proc: Optional[QtCore.QProcess] = None

    def is_running(self) -> bool:
        return (self._proc is not None
                and self._proc.state() != QtCore.QProcess.NotRunning)

    def start(self, exe: str, args: List[str]) -> bool:
        """Launch the exe with args. Returns False if one is already running."""
        if self.is_running():
            self.log.emit("A solve is already running.")
            return False

        self._proc = QtCore.QProcess(self)
        self._proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)

        self.log.emit(self._format_cmd(exe, args))
        self._proc.start(exe, args)
        return True

    @staticmethod
    def _format_cmd(exe: str, args: List[str]) -> str:
        """Render the command for the log, quoting tokens that contain spaces.

        Display only - QProcess does the real quoting when it runs the exe.
        """
        def q(token: str) -> str:
            # Quote the value part of a flag=value token if the value has spaces.
            if "=" in token:
                flag, _, value = token.partition("=")
                if " " in value:
                    return f'{flag}="{value}"'
                return token
            return f'"{token}"' if " " in token else token
        return "$ " + " ".join(q(t) for t in [exe] + args)

    def cancel(self) -> None:
        if self.is_running():
            self._proc.kill()
            self.log.emit("Solve cancelled.")

    def _on_output(self) -> None:
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in data.splitlines():
            self.log.emit(line)

    def _on_error(self, error) -> None:
        """Report a process-level failure (as opposed to a non-zero exit).

        ``finished`` never fires when the exe fails to start, so it is emitted
        here as -1 - without it the UI would sit with Solve disabled forever.
        """
        reason = self._ERROR_REASONS.get(error, f"Process error ({error}).")
        self.log.emit(reason)
        if error == QtCore.QProcess.FailedToStart:
            self.finished.emit(-1)

    def _on_finished(self, code, status) -> None:
        if status == QtCore.QProcess.CrashExit:
            self.log.emit("The process exited abnormally (crash or cancel).")
        self.finished.emit(int(code))


def parse_rmse(log_text: str) -> Optional[float]:
    """Pull the last rmse value out of the exe log, if present."""
    import re
    matches = re.findall(r"rmse[^0-9eE+\-.]*([0-9eE+\-.]+)", log_text, re.IGNORECASE)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None