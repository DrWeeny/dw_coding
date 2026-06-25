"""
dw_chain_guide.py  -  Phase 1
==============================
Build a joint chain along an edge loop via a NurbsCurve intermediate.

Workflow:
    # 1. Select an edge loop in Maya
    guide = ChainGuide.from_edge_selection(n_joints=12, name="cape_A")
    guide.build()

    # 2. Rebuild with more joints (the source curve is kept)
    guide.rebuild(n_joints=20)

    # 3. From an existing curve
    guide = ChainGuide.from_existing_curve("my_crv", n_joints=15, name="rope_B")
    guide.build()
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

import maya.cmds as cmds
import maya.api.OpenMaya as om2


# -----------------------------------------------------------------------------
# Edge Extraction
# -----------------------------------------------------------------------------

def get_selected_edges() -> tuple[om2.MDagPath, list[int]]:
    """
    Return (mesh_dag, [edge_ids]) from the active selection.
    Raise ValueError if the selection is not edges.
    """
    sel = om2.MGlobal.getActiveSelectionList()
    if sel.isEmpty():
        raise ValueError("Nothing selected. Select an edge loop.")

    dag, component = sel.getComponent(0)

    if component.apiType() != om2.MFn.kMeshEdgeComponent:
        raise ValueError(
            "The selection must be edges (MeshEdgeComponent)."
        )

    dag.extendToShape()
    edge_comp = om2.MFnSingleIndexedComponent(component)
    edge_ids  = list(edge_comp.getElements())  # MIntArray -> list

    if len(edge_ids) < 2:
        raise ValueError(f"At least 2 edges required, {len(edge_ids)} found.")

    return dag, edge_ids


def _build_edge_vert_map(mesh_dag: om2.MDagPath,
                         edge_ids: list[int]) -> dict[int, tuple[int, int]]:
    """
    Build {edge_id: (v0, v1)} in a single pass over the iterator.
    Complexity O(total_edges), acceptable for normal meshes.
    """
    target = set(edge_ids)
    result: dict[int, tuple[int, int]] = {}
    it = om2.MItMeshEdge(mesh_dag)
    while not it.isDone():
        idx = it.index()
        if idx in target:
            result[idx] = (it.vertexId(0), it.vertexId(1))
            if len(result) == len(edge_ids):
                break
        it.next()
    return result


def order_edge_loop(mesh_dag: om2.MDagPath,
                    edge_ids: list[int]) -> tuple[list[int], bool]:
    """
    Reorder the edges into a connected sequence.

    Returns
    -------
    ordered_edges : list[int]
    is_closed     : bool  - True if the loop closes back on itself
    """
    e2v = _build_edge_vert_map(mesh_dag, edge_ids)

    # Adjacency: vertex -> [edge_ids]
    v2e: dict[int, list[int]] = defaultdict(list)
    for eid, (v0, v1) in e2v.items():
        v2e[v0].append(eid)
        v2e[v1].append(eid)

    # Start point: a terminal edge (one of its vertices belongs to a single
    # selected edge) -> open chain. Otherwise -> closed loop.
    #
    # IMPORTANT: we remember *which* vertex is the dead-end (start_vert) so we
    # can start the traversal from the CONNECTED vertex of the terminal edge.
    # If we start from the dead-end (the old `e2v[start_edge][1]` chosen blindly),
    # the only incident edge is already visited -> the traversal stops after 1
    # edge -> 1 single CV -> "Curve/Surface degree cannot be less than 1". The
    # v0/v1 orientation of an edge depends on the mesh, hence the intermittent bug.
    start_edge = edge_ids[0]
    start_vert: Optional[int] = None
    is_closed  = True
    for eid in edge_ids:
        v0, v1 = e2v[eid]
        if len(v2e[v0]) == 1:
            start_edge, start_vert, is_closed = eid, v0, False
            break
        if len(v2e[v1]) == 1:
            start_edge, start_vert, is_closed = eid, v1, False
            break

    # Linked-list style traversal
    ordered: list[int] = [start_edge]
    visited: set[int]  = {start_edge}

    v0, v1 = e2v[start_edge]
    if is_closed:
        current_vert = v1  # loop: any direction works
    else:
        # Move away from the dead-end: start from the vertex OPPOSITE the terminal.
        current_vert = v1 if start_vert == v0 else v0

    while len(ordered) < len(edge_ids):
        advanced = False
        for eid in v2e[current_vert]:
            if eid not in visited:
                ordered.append(eid)
                visited.add(eid)
                v0, v1     = e2v[eid]
                current_vert = v1 if v0 == current_vert else v0
                advanced   = True
                break
        if not advanced:
            break  # incomplete chain / disconnected edges

    if len(ordered) != len(edge_ids):
        import warnings
        warnings.warn(
            f"order_edge_loop: {len(ordered)}/{len(edge_ids)} edges ordered. "
            "Check that the edges are properly connected.",
            RuntimeWarning
        )

    return ordered, is_closed


def extract_edge_midpoints(mesh_dag: om2.MDagPath,
                           ordered_edges: list[int]) -> list[om2.MPoint]:
    """
    Return the world-space midpoint of each edge, in order.
    """
    e2v    = _build_edge_vert_map(mesh_dag, ordered_edges)
    mesh   = om2.MFnMesh(mesh_dag)
    points = []
    for eid in ordered_edges:
        v0, v1 = e2v[eid]
        p0 = mesh.getPoint(v0, om2.MSpace.kWorld)
        p1 = mesh.getPoint(v1, om2.MSpace.kWorld)
        points.append(om2.MPoint(
            (p0.x + p1.x) * 0.5,
            (p0.y + p1.y) * 0.5,
            (p0.z + p1.z) * 0.5,
        ))
    return points


# -----------------------------------------------------------------------------
# Face Extraction
# -----------------------------------------------------------------------------

def get_selected_faces() -> tuple[om2.MDagPath, list[int]]:
    """
    Return (mesh_dag, [face_ids]) from the active selection.
    Raise ValueError if the selection is not faces.
    """
    sel = om2.MGlobal.getActiveSelectionList()
    if sel.isEmpty():
        raise ValueError("Nothing selected. Select faces.")

    dag, component = sel.getComponent(0)

    if component.apiType() != om2.MFn.kMeshPolygonComponent:
        raise ValueError(
            "The selection must be faces (MeshPolygonComponent)."
        )

    dag.extendToShape()
    face_comp = om2.MFnSingleIndexedComponent(component)
    face_ids  = list(face_comp.getElements())

    if len(face_ids) < 2:
        raise ValueError(f"At least 2 faces required, {len(face_ids)} found.")

    return dag, face_ids


def _collect_face_data(mesh_dag: om2.MDagPath,
                       face_ids: list[int],) -> dict[int, tuple[om2.MPoint, list[int]]]:
    """
    Single pass over MItMeshPolygon.
    Return {face_id: (centroid_world, [adjacent_selected_face_ids])}

    Used by order_face_strip() and extract_face_centroids()
    to avoid walking the mesh twice.
    """
    face_set = set(face_ids)
    data: dict[int, tuple[om2.MPoint, list[int]]] = {}

    it = om2.MItMeshPolygon(mesh_dag)
    while not it.isDone():
        fid = it.index()
        if fid in face_set:
            centroid  = it.center(om2.MSpace.kWorld)
            neighbors = [f for f in it.getConnectedFaces() if f in face_set]
            data[fid] = (centroid, neighbors)
        it.next()

    return data


def order_face_strip(mesh_dag: om2.MDagPath,
                     face_ids: list[int],) -> tuple[list[int], bool]:
    """
    Reorder the faces into a connected strip.

    Expects a linear strip: each face has at most 2 selected neighbors.
    If the strip forms a ring (skirt), is_closed is True.

    Returns
    -------
    ordered_faces : list[int]
    is_closed     : bool
    """
    face_data = _collect_face_data(mesh_dag, face_ids)

    # Terminal face = 0 or 1 selected neighbor -> open chain
    # No terminal -> closed loop
    start     = face_ids[0]
    is_closed = True
    for fid, (_, neighbors) in face_data.items():
        if len(neighbors) <= 1:
            start     = fid
            is_closed = False
            break

    ordered: list[int] = [start]
    visited: set[int]  = {start}
    current = start

    while len(ordered) < len(face_ids):
        _, neighbors = face_data[current]
        advanced = False
        for nb in neighbors:
            if nb not in visited:
                ordered.append(nb)
                visited.add(nb)
                current = nb
                advanced = True
                break
        if not advanced:
            break

    if len(ordered) != len(face_ids):
        import warnings
        warnings.warn(
            f"order_face_strip: {len(ordered)}/{len(face_ids)} faces ordered. "
            "The strip must be connected and without branching.",
            RuntimeWarning,
        )

    return ordered, is_closed


def extract_face_centroids(mesh_dag: om2.MDagPath,
                           ordered_faces: list[int],) -> list[om2.MPoint]:
    """
    Return the world-space centroid of each face, in order.
    """
    face_data = _collect_face_data(mesh_dag, ordered_faces)
    return [face_data[fid][0] for fid in ordered_faces]


# -----------------------------------------------------------------------------
# Curve Creation
# -----------------------------------------------------------------------------

def build_curve_from_positions(positions: list[om2.MPoint],
                               name: str  = "chainGuide_crv",
                               degree: int = 3,
                               closed: bool = False,) -> str:
    """
    Create a NurbsCurve through the given positions.
    For a closed loop, the first CVs are duplicated to ensure
    tangential continuity.

    Returns
    -------
    curve_transform : str  - name of the Maya transform node
    """
    pts = [(p.x, p.y, p.z) for p in positions]
    n   = len(pts)

    if n < 2:
        raise ValueError(
            f"build_curve_from_positions: {n} point(s) received, at least 2 are "
            "required. Edge/face ordering probably failed (disconnected "
            "selection?) - see order_edge_loop / order_face_strip."
        )

    d   = min(degree, n - 1)  # degree cannot exceed nPoints-1

    if closed and n >= d + 1:
        # Wrapping: add the first d points to the end
        wrapped = pts + pts[:d]
        crv = cmds.curve(point=wrapped, degree=d)
        # closeCurve to get a real periodic curve
        crv = cmds.closeCurve(crv, preserveShape=False,
                               replaceOriginal=True)[0]
    else:
        crv = cmds.curve(point=pts, degree=d)

    crv = cmds.rename(crv, name)
    return crv


def resample_curve(curve_name: str,
                   cv_count:   int,
                   degree:     int = 3,) -> str:
    """
    Rebuild a curve in place to have `cv_count` CVs (uniform, keeping the end
    points), so a coarse curve becomes smooth and editable. For an open degree-d
    curve, CVs = spans + degree, hence spans = cv_count - degree (min 1).
    """
    spans = max(int(cv_count) - degree, 1)
    cmds.rebuildCurve(
        curve_name,
        constructionHistory = False,
        replaceOriginal     = True,
        rebuildType         = 0,    # uniform
        endKnots            = 1,    # multiple end knots
        keepRange           = 0,
        keepControlPoints   = False,
        keepEndPoints       = True,
        keepTangents        = False,
        spans               = spans,
        degree              = degree,
    )
    return curve_name


def reverse_curve_direction(curve_name: str) -> str:
    """
    Reverse a curve's direction in place (reverseCurve -replaceOriginal).
    All following rebuilds will start from the other end.

    Returns
    -------
    curve_name : str  - same name (the curve is modified in-place)
    """
    result = cmds.reverseCurve(curve_name, replaceOriginal=True)
    # reverseCurve returns [shape] or [transform, shape] depending on the version
    return curve_name


# -----------------------------------------------------------------------------
# Joint Distribution
# -----------------------------------------------------------------------------

_UP_REMAP = {
    "x": "xup", "y": "yup", "z": "zup",
    "-x": "xdown", "-y": "ydown", "-z": "zdown",
}


def distribute_joints(curve_name: str,
                      n_joints:   int,
                      chain_name: str = "chain",
                      up_axis:    str = "y",) -> list[str]:
    """
    Distribute n_joints uniformly along the curve
    (arc-length parameterization).

    Orientation convention (via Maya orientJoint):
        X -> along the bone (tangent)
        Y -> up_axis (world)
        Z -> cross product

    Parameters
    ----------
    up_axis : "x" | "y" | "z" | "-x" | "-y" | "-z"

    Returns
    -------
    joints : list[str]  (root at [0], tip at [-1])
    """
    # -- Get the OM2 curve ------------------------------------------------
    sel = om2.MSelectionList()
    sel.add(curve_name)
    dag = sel.getDagPath(0)
    dag.extendToShape()
    curve_fn     = om2.MFnNurbsCurve(dag)
    total_length = curve_fn.length()

    if total_length < 1e-6:
        raise ValueError(f"The curve '{curve_name}' has zero length.")

    # -- Compute arc-length positions -------------------------------------
    positions: list[om2.MPoint] = []
    for i in range(n_joints):
        t       = i / max(n_joints - 1, 1)
        arc_len = t * total_length
        # Clamp to avoid floating-point errors at the ends
        arc_len = max(0.0, min(arc_len, total_length * (1.0 - 1e-7)))
        param   = curve_fn.findParamFromLength(arc_len)
        pos     = curve_fn.getPointAtParam(param, om2.MSpace.kWorld)
        positions.append(pos)

    return place_joint_chain(positions, chain_name=chain_name, up_axis=up_axis)


def _orient_chain(joints:  list[str],
                  up_axis: str = "y",) -> None:
    """
    Orient a joint chain in place: X down the bone, secondary axis = up_axis,
    and zero the tip's joint orient. Positions are untouched.
    """
    if not joints:
        return
    sec_axis = _UP_REMAP.get(up_axis.lower(), "yup")
    cmds.joint(
        joints[0],
        edit=True,
        orientJoint="xyz",
        secondaryAxisOrient=sec_axis,
        children=True,
        zeroScaleOrient=True,
    )
    for attr in ("jointOrientX", "jointOrientY", "jointOrientZ"):
        cmds.setAttr(f"{joints[-1]}.{attr}", 0.0)


def place_joint_chain(positions:  list[om2.MPoint],
                      chain_name: str = "chain",
                      up_axis:    str = "y",) -> list[str]:
    """
    Create one joint per position, exactly at it, as an oriented chain. The root
    carries the _PIN suffix; index padding is 1. Returns [root, ..., tip].
    """
    joints: list[str] = []
    cmds.select(clear=True)
    for i, pos in enumerate(positions):
        if joints:
            cmds.select(joints[-1])   # new joint becomes the previous one's child
        suffix = "_PIN" if i == 0 else ""
        jnt = cmds.joint(
            name=f"{chain_name}_jnt_{i}{suffix}",
            position=(pos.x, pos.y, pos.z),
        )
        joints.append(jnt)
    _orient_chain(joints, up_axis)
    cmds.select(clear=True)
    return joints


def chain_from_joints(joint_nodes: list[str],
                      chain_name:  str = "chain",
                      up_axis:     str = "y",) -> list[str]:
    """
    Turn already-placed joints (any parenting) into an oriented chain IN PLACE,
    reusing the exact nodes the artist positioned: detach, re-parent root->tip,
    rename (_PIN root, padding 1) and orient. Positions are preserved.

    `joint_nodes` must already be in the desired root->tip order. Returns the
    renamed nodes in that same order.
    """
    ordered = list(joint_nodes)
    if not ordered:
        return []
    for jnt in ordered:
        if cmds.listRelatives(jnt, parent=True):
            cmds.parent(jnt, world=True)
    for i in range(1, len(ordered)):
        ordered[i] = cmds.parent(ordered[i], ordered[i - 1])[0]
    renamed: list[str] = []
    for i, jnt in enumerate(ordered):
        suffix = "_PIN" if i == 0 else ""
        renamed.append(cmds.rename(jnt, f"{chain_name}_jnt_{i}{suffix}"))
    _orient_chain(renamed, up_axis)
    cmds.select(clear=True)
    return renamed


def build_curve_through_positions(positions: list[om2.MPoint],
                                  name:      str = "chainGuide_crv",
                                  degree:    int = 3,) -> str:
    """
    Create a NURBS curve that passes EXACTLY through every position, using
    edit-point construction (an EP curve interpolates its points at any degree,
    unlike a CV curve whose interior CVs only pull on the shape). Used for the
    data-only curve in exact mode.
    """
    pts = [(p.x, p.y, p.z) for p in positions]
    n = len(pts)
    if n < 2:
        raise ValueError(
            f"build_curve_through_positions: {n} point(s), at least 2 required."
        )
    d = min(degree, n - 1)   # degree cannot exceed nEditPoints - 1
    crv = cmds.curve(editPoint=pts, degree=d)
    crv = cmds.rename(crv, name)
    return crv


# -----------------------------------------------------------------------------
# Locator Guides
# -----------------------------------------------------------------------------
#
# Locator creation flow: the artist spawns guide locators (min 3), positions
# them by hand, then a source curve is built through them. The locators are kept
# (under a tagged group) so the guide stays editable; world positions are read
# straight off the locators when the curve is built.

_LOCATOR_GROUP_TAG = "cgLocGuide"   # marker attr added on the locator group
_GUIDE_LOCATOR_SCALE = 10.0         # default locator localScale (visibility)


def ensure_locator_group(name: str) -> str:
    """
    Return the (existing or freshly created) tagged guide-point group, parented
    under the main guide group - the points belong to the setup (they are cleaned
    later, keeping only the curve + its metadata).
    """
    grp = f"{name}_locGuide_GRP"
    if not cmds.objExists(grp):
        grp = cmds.group(empty=True, name=grp)
    if not cmds.attributeQuery(_LOCATOR_GROUP_TAG, node=grp, exists=True):
        cmds.addAttr(grp, longName=_LOCATOR_GROUP_TAG, attributeType="bool")
    cmds.setAttr(f"{grp}.{_LOCATOR_GROUP_TAG}", True)

    # Keep guide points inside the main guide group, next to the curves.
    ChainGuide._ensure_guide_group()
    parents = cmds.listRelatives(grp, parent=True) or []
    if parents != [ChainGuide.GRP_NAME]:
        grp = cmds.parent(grp, ChainGuide.GRP_NAME)[0]
    return grp


def create_guide_locators(n_locators: int = 3,
                          name:       str = "chain",
                          spacing:    float = 1.0,) -> list[str]:
    """
    Create n_locators guide locators spread along world +Y, grouped under one
    tagged transform. Used by the locator creation flow before any curve exists.

    Returns
    -------
    locators : list[str]  - transform names, root at [0]
    """
    if n_locators < 3:
        raise ValueError(
            f"create_guide_locators: at least 3 locators required, got {n_locators}."
        )
    grp = ensure_locator_group(name)

    locators: list[str] = []
    for i in range(n_locators):
        loc = cmds.spaceLocator(name=f"{name}_loc_{i:02d}")[0]
        for axis in "XYZ":
            cmds.setAttr(f"{loc}.localScale{axis}", _GUIDE_LOCATOR_SCALE)
        cmds.setAttr(f"{loc}.translateY", i * spacing)
        loc = cmds.parent(loc, grp)[0]
        locators.append(loc)

    cmds.select(clear=True)
    return locators


def get_selection_center() -> Optional[tuple]:
    """
    Return the world-space center of the current selection, or None if nothing
    usable is selected. Mesh components are converted to vertices and averaged
    (so an edge ring / face patch gives its centroid); otherwise the selected
    objects' world pivots are averaged.
    """
    sel = cmds.ls(selection=True, flatten=True) or []
    if not sel:
        return None

    verts = cmds.polyListComponentConversion(sel, toVertex=True)
    verts = cmds.ls(verts, flatten=True) or []
    if verts:
        coords = cmds.xform(verts, query=True, translation=True, worldSpace=True)
        count = len(coords) // 3
        if count == 0:
            return None
        return (sum(coords[0::3]) / count,
                sum(coords[1::3]) / count,
                sum(coords[2::3]) / count)

    points = []
    for node in sel:
        if cmds.objExists(node):
            points.append(cmds.xform(node, query=True, translation=True, worldSpace=True))
    if not points:
        return None
    count = len(points)
    return (sum(p[0] for p in points) / count,
            sum(p[1] for p in points) / count,
            sum(p[2] for p in points) / count)


def create_guide_point(node_type: str   = "locator",
                       name:      str   = "chain",
                       index:     int   = 0,
                       position:  Optional[tuple] = None,
                       scale:     float = _GUIDE_LOCATOR_SCALE,
                       group:     Optional[str] = None,) -> str:
    """
    Create a single guide point (a locator or a joint) under the tagged guide
    group and return its node name. Locators get localScale = `scale` so they
    are easy to see / grab; joints get their radius set to `scale`.
    """
    if group is None:
        group = ensure_locator_group(name)

    if node_type == "joint":
        cmds.select(clear=True)
        node = cmds.createNode("joint", name=f"{name}_gpt_{index:02d}")
        cmds.setAttr(f"{node}.radius", scale)
    else:
        node = cmds.spaceLocator(name=f"{name}_loc_{index:02d}")[0]
        for axis in "XYZ":
            cmds.setAttr(f"{node}.localScale{axis}", scale)

    if position is not None:
        cmds.xform(node, worldSpace=True, translation=position)

    current = cmds.listRelatives(node, parent=True) or []
    if current != [group] and cmds.objExists(group):
        node = cmds.parent(node, group)[0]
    cmds.select(clear=True)
    return node


def snap_node_to_selection_center(node: str) -> tuple:
    """Move `node` to the current selection center (see get_selection_center)."""
    center = get_selection_center()
    if center is None:
        raise ValueError("Select mesh components (or objects) to snap to.")
    cmds.xform(node, worldSpace=True, translation=center)
    return center


def unique_group_name(base: str = "chainGuides_GRP") -> str:
    """Return `base`, or `base1`/`base2`/... if a node by that name already exists."""
    if not cmds.objExists(base):
        return base
    index = 1
    while cmds.objExists(f"{base}{index}"):
        index += 1
    return f"{base}{index}"


def detect_guide_groups() -> list:
    """
    Return the long paths of the groups holding tagged guide curves in the scene
    (typically one or more 'chainGuides_GRP', e.g. across namespaces). Used to
    populate a 'load from Maya' picker.
    """
    groups: list = []
    seen: set = set()
    for shape in cmds.ls(type="nurbsCurve", long=True) or []:
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        if not parents:
            continue
        transform = parents[0]
        if not cmds.objExists(f"{transform}.cgName"):
            continue
        grp_parents = cmds.listRelatives(transform, parent=True, fullPath=True) or []
        group = grp_parents[0] if grp_parents else transform
        if group not in seen:
            seen.add(group)
            groups.append(group)
    return groups


def add_guide_locator(locators: list[str],
                     name:      str = "chain",) -> str:
    """
    Append one guide locator just past the last one (extrapolating the last
    segment direction, or +Y if only one exists). Returns the new locator name.
    """
    if not locators:
        raise ValueError("add_guide_locator: empty locator list.")
    parents = cmds.listRelatives(locators[-1], parent=True) or []
    grp     = parents[0] if parents else None

    idx = len(locators)
    loc = cmds.spaceLocator(name=f"{name}_loc_{idx:02d}")[0]

    last = cmds.xform(locators[-1], query=True, worldSpace=True, translation=True)
    if len(locators) >= 2:
        prev    = cmds.xform(locators[-2], query=True, worldSpace=True, translation=True)
        new_pos = [last[i] + (last[i] - prev[i]) for i in range(3)]
    else:
        new_pos = [last[0], last[1] + 1.0, last[2]]
    cmds.xform(loc, worldSpace=True, translation=new_pos)

    if grp:
        cmds.parent(loc, grp)
    cmds.select(clear=True)
    return loc


def get_locator_positions(locators: list[str]) -> list[om2.MPoint]:
    """Return the world-space position of each locator, in order."""
    points: list[om2.MPoint] = []
    for loc in locators:
        pos = cmds.xform(loc, query=True, worldSpace=True, translation=True)
        points.append(om2.MPoint(pos[0], pos[1], pos[2]))
    return points


def build_curve_from_locators(locators: list[str],
                             name:      str = "chainGuide_crv",
                             degree:    int = 3,
                             closed:    bool = False,) -> str:
    """
    Build a source NURBS curve through the given guide locators (min 3).
    """
    if len(locators) < 3:
        raise ValueError(
            f"build_curve_from_locators: at least 3 locators required, "
            f"{len(locators)} given."
        )
    positions = get_locator_positions(locators)
    return build_curve_from_positions(positions,
                                      name   = name,
                                      degree = degree,
                                      closed = closed,)


def delete_guide_locators(locators: list[str]) -> None:
    """Delete the guide locators and their group transform (if any)."""
    alive = [loc for loc in locators if cmds.objExists(loc)]
    if not alive:
        return
    parents = cmds.listRelatives(alive[0], parent=True) or []
    target  = parents[0] if parents else alive[0]
    if cmds.objExists(target):
        cmds.delete(target)


def get_selected_mesh() -> Optional[str]:
    """
    Return the transform of the first polygon mesh in the active selection,
    or None. Accepts a transform, a mesh shape or a vertex/component selection.
    """
    sel = cmds.ls(selection=True, long=True) or []
    for node in sel:
        # Component selection (e.g. mesh.vtx[3]) -> strip the component part.
        base = node.split(".")[0]
        if cmds.nodeType(base) == "mesh":
            parents = cmds.listRelatives(base, parent=True, fullPath=True) or []
            if parents:
                return parents[0]
        shapes = cmds.listRelatives(base, shapes=True, type="mesh", fullPath=True) or []
        if shapes:
            return base
    return None


def snap_locators_to_mesh(locators: list[str],
                          mesh:     str,) -> None:
    """
    Snap each guide locator to the nearest vertex of `mesh` (world space).

    Uses the closest surface point to find the owning face, then picks the
    nearest vertex of that face - cheap and robust on dense meshes (no full
    vertex scan).
    """
    if not locators:
        raise ValueError("snap_locators_to_mesh: no locators to snap.")
    sel = om2.MSelectionList()
    sel.add(mesh)
    dag = sel.getDagPath(0)
    dag.extendToShape()
    mesh_fn = om2.MFnMesh(dag)

    for loc in locators:
        if not cmds.objExists(loc):
            continue
        p = cmds.xform(loc, query=True, worldSpace=True, translation=True)
        point = om2.MPoint(p[0], p[1], p[2])
        _, face_id = mesh_fn.getClosestPoint(point, om2.MSpace.kWorld)
        best_pos: Optional[om2.MPoint] = None
        best_dist: Optional[float]     = None
        for vid in mesh_fn.getPolygonVertices(face_id):
            vpos = mesh_fn.getPoint(vid, om2.MSpace.kWorld)
            dist = (vpos - point).length()
            if best_dist is None or dist < best_dist:
                best_dist, best_pos = dist, vpos
        if best_pos is not None:
            cmds.xform(loc, worldSpace=True,
                       translation=(best_pos.x, best_pos.y, best_pos.z))


# -----------------------------------------------------------------------------
# ChainGuide
# -----------------------------------------------------------------------------

class ChainGuide:
    """
    Represents a joint chain built from a source NurbsCurve.

    The curve is the "source of truth": it can be edited by hand
    in Maya, then rebuild() recreates the chain without touching the curve.

    Metadata stored as attributes on the curve:
        .cgName     (string)  - logical name of the guide
        .cgJoints   (int)     - number of joints
        .cgUpAxis   (string)  - up axis used
    """

    GRP_NAME = "chainGuides_GRP"

    # -- Constructor -------------------------------------------------------

    def __init__(self,
                 curve_name: str,
                 n_joints:   int = 10,
                 name:       str = "chain",
                 up_axis:    str = "y",
                 group:      Optional[str] = None,) -> None:
        self.curve_name = curve_name
        self.n_joints   = n_joints
        self.name       = name
        self.up_axis    = up_axis
        # Group the built nodes live under. Defaults to the shared working group;
        # a loaded version can pass its own unique group to stay separate.
        self.group_name = group or self.GRP_NAME
        self.joints:   list[str]       = []

    # -- Factories ---------------------------------------------------------

    @classmethod
    def from_edge_selection(cls,
                            n_joints: int  = 10,
                            name:     str  = "chain",
                            degree:   int  = 3,
                            up_axis:  str  = "y",
                            reverse:  bool = False,) -> "ChainGuide":
        """
        Create a ChainGuide from the current edge selection in Maya.

        Parameters
        ----------
        reverse : bool
            Reverse the chain direction (root <-> tip).
            Can also be changed afterward via guide.flip().

        Example
        -------
        # Select an edge loop in the viewport, then:
        guide = ChainGuide.from_edge_selection(n_joints=12, name="cape_A")
        guide.build()

        # If the chain goes the wrong way:
        guide = ChainGuide.from_edge_selection(n_joints=12, name="cape_A", reverse=True)
        guide.build()
        """
        mesh_dag, edge_ids = get_selected_edges()
        ordered, is_closed = order_edge_loop(mesh_dag, edge_ids)
        positions          = extract_edge_midpoints(mesh_dag, ordered)

        if reverse:
            positions = positions[::-1]

        crv = build_curve_from_positions(
            positions,
            name   = f"{name}_src_crv",
            degree = degree,
            closed = is_closed,
        )

        # Store inside the guides group
        cls._ensure_guide_group()
        cmds.parent(crv, cls.GRP_NAME)

        # Store metadata on the curve so it can be rebuilt
        cls._tag_curve(crv, name, n_joints, up_axis)

        return cls(curve_name=crv, n_joints=n_joints, name=name, up_axis=up_axis)

    @classmethod
    def from_face_selection(cls,
                            n_joints: int  = 10,
                            name:     str  = "chain",
                            degree:   int  = 3,
                            up_axis:  str  = "y",
                            reverse:  bool = False,) -> "ChainGuide":
        """
        Create a ChainGuide from a face selection in Maya.

        The centroid of each face is used as a curve waypoint -
        suited to face strips along a garment.

        Notes
        -----
        - The strip must be linear (no branching).
        - For a face ring (skirt hem), is_closed is detected
          automatically and the curve will be periodic.

        Example
        -------
        # Select a face strip along a scarf, then:
        guide = ChainGuide.from_face_selection(n_joints=14, name="scarf_A")
        guide.build()
        """
        mesh_dag, face_ids = get_selected_faces()
        ordered, is_closed = order_face_strip(mesh_dag, face_ids)
        positions          = extract_face_centroids(mesh_dag, ordered)

        if reverse:
            positions = positions[::-1]

        crv = build_curve_from_positions(
            positions,
            name   = f"{name}_src_crv",
            degree = degree,
            closed = is_closed,
        )

        cls._ensure_guide_group()
        cmds.parent(crv, cls.GRP_NAME)
        cls._tag_curve(crv, name, n_joints, up_axis)

        return cls(curve_name=crv, n_joints=n_joints, name=name, up_axis=up_axis)

    @classmethod
    def from_existing_curve(cls,
                            curve_name: str,
                            n_joints:   int = 10,
                            name:       str = "chain",
                            up_axis:    str = "y",
                            group:      Optional[str] = None,) -> "ChainGuide":
        """
        Use a curve already present in the scene as the source.
        Lets you draw / sculpt the curve by hand before building.

        `group` lets a loaded version place its nodes in a dedicated group rather
        than the shared working group.
        """
        if not cmds.objExists(curve_name):
            raise ValueError(f"Curve not found: '{curve_name}'.")
        cls._tag_curve(curve_name, name, n_joints, up_axis)
        return cls(curve_name=curve_name, n_joints=n_joints, name=name,
                   up_axis=up_axis, group=group)

    @classmethod
    def from_locators(cls,
                      locators:         list[str],
                      n_joints:         int  = 10,
                      name:             str  = "chain",
                      degree:           int  = 3,
                      up_axis:          str  = "y",
                      reverse:          bool = False,
                      cleanup_locators: bool = False,
                      cv_count:         Optional[int] = None,) -> "ChainGuide":
        """
        Create a ChainGuide from a set of guide locators (min 3).

        The source curve is built through the locator world positions and tagged
        like any other ChainGuide curve, so rebuild() / flip() work afterwards.

        Parameters
        ----------
        cv_count : Optional[int]
            If given (and > degree), resample the curve to this many CVs. A curve
            built straight through 3 locators only has 3 CVs - too coarse to edit;
            resampling gives a smooth, editable curve the artist can then tweak.
        cleanup_locators : bool
            If True, delete the locators and their group once the curve is built.
            Default keeps them so the guide stays editable.
        """
        if len(locators) < 2:
            raise ValueError(
                f"from_locators: at least 2 guide points required, {len(locators)} given."
            )
        positions = get_locator_positions(locators)
        if reverse:
            positions = positions[::-1]

        crv = build_curve_from_positions(
            positions,
            name   = f"{name}_src_crv",
            degree = degree,
            closed = False,
        )
        if cv_count is not None:
            resample_curve(crv, cv_count, degree=degree)
        cls._ensure_guide_group()
        cmds.parent(crv, cls.GRP_NAME)
        cls._tag_curve(crv, name, n_joints, up_axis)

        if cleanup_locators:
            delete_guide_locators(locators)

        return cls(curve_name=crv, n_joints=n_joints, name=name, up_axis=up_axis)

    @classmethod
    def from_scene_curve(cls, curve_name: str) -> "ChainGuide":
        """
        Rebuild a ChainGuide from a curve already tagged in the scene
        (after reopening a file, for example).
        """
        if not cmds.objExists(f"{curve_name}.cgName"):
            raise ValueError(
                f"'{curve_name}' does not look like a ChainGuide curve "
                "(.cgName attribute missing)."
            )
        name     = cmds.getAttr(f"{curve_name}.cgName")
        n_joints = cmds.getAttr(f"{curve_name}.cgJoints")
        up_axis  = cmds.getAttr(f"{curve_name}.cgUpAxis")
        return cls(curve_name=curve_name, n_joints=n_joints, name=name, up_axis=up_axis)

    # -- Build / Rebuild ---------------------------------------------------

    def build(self) -> list[str]:
        """
        Build the joint chain from the source curve.
        Delete the old chain if it exists.
        """
        self._cleanup_joints()
        self.joints = distribute_joints(
            curve_name = self.curve_name,
            n_joints   = self.n_joints,
            chain_name = self.name,
            up_axis    = self.up_axis,
        )
        self._organize_joints()
        return self.joints

    def rebuild(self,
                n_joints: Optional[int] = None,
                up_axis:  Optional[str] = None,) -> list[str]:
        """
        Rebuild the chain. The source curve is left intact.
        Passed parameters override the guide's and are persisted.
        """
        if n_joints is not None:
            self.n_joints = n_joints
        if up_axis is not None:
            self.up_axis = up_axis

        # Update the metadata on the curve
        self._tag_curve(self.curve_name, self.name, self.n_joints, self.up_axis)

        return self.build()

    def flip(self) -> list[str]:
        """
        Reverse the source curve direction and rebuild the chain.

        Useful when the direction is wrong after a from_edge_selection()
        without recreating everything. The curve is modified in-place:
        all following rebuilds will start from the right side.

        Example
        -------
        guide = ChainGuide.from_edge_selection(n_joints=12, name="scarf")
        guide.build()
        # -> root at the bottom, wrong way
        guide.flip()
        # -> root at the top, correct
        """
        reverse_curve_direction(self.curve_name)
        return self.build()

    # -- Internal helpers --------------------------------------------------

    def _cleanup_joints(self) -> None:
        """Delete the existing chain (from the root, automatic cascade)."""
        alive = [j for j in self.joints if cmds.objExists(j)]
        if alive:
            root = alive[0]
            # Walk back up to the real root in case it was reparented
            parents = cmds.listRelatives(root, allParents=True, type="joint") or []
            root = parents[-1] if parents else root
            cmds.delete(root)
        self.joints = []

    def _organize_joints(self) -> None:
        """Place the root under this guide's group."""
        if not self.joints:
            return
        root = self.joints[0]
        self.ensure_group()
        current_parent = cmds.listRelatives(root, parent=True) or []
        if current_parent != [self.group_name]:
            cmds.parent(root, self.group_name)

    def ensure_group(self) -> str:
        """Create this guide's group if missing and return its name."""
        if not cmds.objExists(self.group_name):
            cmds.group(empty=True, name=self.group_name)
        return self.group_name

    @classmethod
    def _ensure_guide_group(cls) -> None:
        if not cmds.objExists(cls.GRP_NAME):
            cmds.group(empty=True, name=cls.GRP_NAME)

    @staticmethod
    def _tag_curve(curve: str, name: str, n_joints: int, up_axis: str) -> None:
        """Add / update the metadata attributes on the curve."""
        def _ensure_attr(node, ln, typ, **kw):
            if not cmds.attributeQuery(ln, node=node, exists=True):
                cmds.addAttr(node, longName=ln, **kw)

        _ensure_attr(curve, "cgName",   "string", dataType="string")
        _ensure_attr(curve, "cgJoints", "long",   attributeType="long")
        _ensure_attr(curve, "cgUpAxis", "string", dataType="string")

        cmds.setAttr(f"{curve}.cgName",   name,     type="string")
        cmds.setAttr(f"{curve}.cgJoints", n_joints)
        cmds.setAttr(f"{curve}.cgUpAxis", up_axis,  type="string")

    # -- Properties --------------------------------------------------------

    @property
    def root_joint(self) -> Optional[str]:
        return self.joints[0] if self.joints else None

    @property
    def tip_joint(self) -> Optional[str]:
        return self.joints[-1] if self.joints else None

    @property
    def is_built(self) -> bool:
        return bool(self.joints) and cmds.objExists(self.joints[0])

    def __repr__(self) -> str:
        status = f"joints={len(self.joints)}" if self.is_built else "not built"
        return (
            f"ChainGuide(name={self.name!r}, "
            f"n_joints={self.n_joints}, "
            f"up='{self.up_axis}', "
            f"curve={self.curve_name!r}, "
            f"{status})"
        )