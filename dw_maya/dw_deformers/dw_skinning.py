import maya.cmds as cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
from typing import List, Tuple, Dict

# ---------------------------------------------------------------------------
# Shared internal helper
# ---------------------------------------------------------------------------

def _get_skin_fn(skin_node: str):
    """Return (MFnSkinCluster, [influence_names]) — shared by all functions."""
    sel = om.MSelectionList()
    sel.add(skin_node)
    skin_fn = oma.MFnSkinCluster(sel.getDependNode(0))
    influences = [p.partialPathName() for p in skin_fn.influenceObjects()]
    return skin_fn, influences


# ---------------------------------------------------------------------------
# get_vertex_influence_weights
# ---------------------------------------------------------------------------

def get_vertex_influence_weights(
        skin_node: str,
        soft_mask: List[float],
        mesh_transform: str) -> Dict[str, List[float]]:
    """Per-bone weight arrays for a mesh, aligned to its full vertex list.

    Returns one flat array per bone (length == vertex count of the mesh).
    Unaffected vertices carry 0.0.  Only a single OpenMaya getWeights call
    is made for the whole mesh — no per-vertex Python loop.

    Args:
        skin_node:       skinCluster node name.
        soft_mask:       Full-length float list from ``list_soft_selection_mask``
                         (index == vertex index, 0.0 for unselected verts).
        mesh_transform:  Transform name of the mesh (e.g. ``'pSphere1'``).

    Returns:
        ``{bone_name: [float, ...]}``  — parallel to vertex order.

    Example::

        mask   = list_soft_selection_mask()['pSphere1']
        data   = get_vertex_influence_weights('skinCluster1', mask, 'pSphere1')
        totals = {b: sum(data[b]) for b in data}   # participation in O(n)
    """
    skin_fn, influences = _get_skin_fn(skin_node)
    num_influences = len(influences)

    vtx_count = len(soft_mask)

    # Initialise one zero-filled array per influence
    result: Dict[str, List[float]] = {inf: [0.0] * vtx_count for inf in influences}

    if vtx_count == 0 or num_influences == 0:
        return result

    # Build DAG path + full-mesh component object (MObject() == all verts)
    sel = om.MSelectionList()
    sel.add(mesh_transform)
    dag_path = sel.getDagPath(0)
    # push to shape so getWeights resolves correctly
    dag_path.extendToShape()

    # Single C++ call: flat array [vtx0_inf0, vtx0_inf1, …, vtxN_infM-1]
    weights, _ = skin_fn.getWeights(dag_path, om.MObject())

    # Scatter weights into per-bone arrays — only for vertices in soft mask
    for vtx_idx in range(vtx_count):
        if soft_mask[vtx_idx] <= 0.0:
            continue
        base = vtx_idx * num_influences
        for inf_i, bone in enumerate(influences):
            w = weights[base + inf_i]
            if w > 1e-6:
                result[bone][vtx_idx] = w

    return result


# ---------------------------------------------------------------------------
# compute_weight_delta
# ---------------------------------------------------------------------------

def compute_weight_delta(
        vertex_influence_data: Dict[str, Dict[str, float]],
        soft_weights: Dict[str, float],
        selected_bones: List[str]
) -> Dict[str, object]:
    """Compute per-vertex weight redistribution toward the new jiggle joint.

    For each vertex v in the soft selection:

        jiggle_w[v]   = soft_w[v] * Σ(original_bone_w[v][b] for b in selected_bones)
        new_bone_w[v] = original_bone_w[v][b] * (1 - soft_w[v])

    Total per-vertex weight stays exactly 1.0.

    Args:
        vertex_influence_data: Output of get_vertex_influence_weights().
        soft_weights:          {vtx: soft_sel_weight}  (0–1 normalised).
        selected_bones:        Bones to punch weight from.

    Returns:
        {
            'jiggle': {vtx: float},                   # weight for new joint
            'bones':  {bone: {vtx: float}},            # updated bone weights
        }
    """
    selected_set = set(selected_bones)
    jiggle_weights: Dict[str, float] = {}
    bone_new_weights: Dict[str, Dict[str, float]] = {b: {} for b in selected_bones}

    for vtx, bone_data in vertex_influence_data.items():
        soft_w = soft_weights.get(vtx, 0.0)
        if soft_w <= 0.0:
            continue

        selected_total = sum(bone_data.get(b, 0.0) for b in selected_set)
        if selected_total <= 0.0:
            continue

        jiggle_weights[vtx] = soft_w * selected_total

        for bone in selected_bones:
            orig = bone_data.get(bone, 0.0)
            if orig > 0.0:
                bone_new_weights[bone][vtx] = orig * (1.0 - soft_w)

    return {'jiggle': jiggle_weights, 'bones': bone_new_weights}


# ---------------------------------------------------------------------------
# apply_weight_delta
# ---------------------------------------------------------------------------

def apply_weight_delta(skin_node: str,
                       jiggle_joint: str,
                       delta: Dict[str, object],
                       normalize: bool = True) -> None:
    """Apply the delta from compute_weight_delta() via skinPercent.

    jiggle_joint must already be added as an influence with weight 0
    before calling this.
    """
    jiggle_w: Dict[str, float] = delta['jiggle']
    bones_w: Dict[str, Dict[str, float]] = delta['bones']

    for vtx, jw in jiggle_w.items():
        tv_pairs = [(jiggle_joint, jw)]
        for bone, vtx_map in bones_w.items():
            if vtx in vtx_map:
                tv_pairs.append((bone, vtx_map[vtx]))
        cmds.skinPercent(skin_node, vtx,
                         transformValue=tv_pairs,
                         normalize=normalize)


# ---------------------------------------------------------------------------
# get_participation
# ---------------------------------------------------------------------------

def get_participation(
        bone_arrays: Dict[str, List[float]],
        soft_mask: List[float]
) -> Dict[str, float]:
    """Return each bone's soft-weighted participation percentage.

    Multiplies the bone weight at each vertex by the soft mask value then
    sums — one ``sum()`` call per bone, no inner loop visible in Python.

    Args:
        bone_arrays: Output of ``get_vertex_influence_weights``.
        soft_mask:   Full-length soft selection mask (parallel to vertex order).

    Returns:
        ``{bone_name: percentage}`` sorted descending, values sum ~100.
    """
    totals: Dict[str, float] = {}
    for bone, arr in bone_arrays.items():
        # element-wise multiply then sum — vectorised in CPython built-ins
        total = sum(w * s for w, s in zip(arr, soft_mask) if s > 0.0)
        if total > 0.0:
            totals[bone] = total

    grand = sum(totals.values()) or 1.0
    return dict(sorted(
        {b: (v / grand) * 100.0 for b, v in totals.items()}.items(),
        key=lambda x: x[1], reverse=True
    ))


# ---------------------------------------------------------------------------
# get_dominant_bone
# ---------------------------------------------------------------------------


def get_dominant_bone(accumulated: Dict[str, float], top_n: int = 1) -> List[str]:
    """Return the top_n bones by accumulated weight (highest first)."""
    return list(accumulated.keys())[:top_n]  # dict already sorted descending


def get_accumulated_influences(skin_node: str, components: List[str]) -> Dict[str, float]:
    """
    Calculates the accumulated weights for each influence across the given components
    to find the most dominant bones. Highly optimized using OpenMaya 2.0.
    Returns a dictionary sorted by highest accumulated weight.
    """
    sel = om.MSelectionList()
    sel.add(skin_node)
    skin_obj = sel.getDependNode(0)
    skin_fn = oma.MFnSkinCluster(skin_obj)

    # Get the influences directly from the node
    influence_paths = skin_fn.influenceObjects()
    influences = [path.partialPathName() for path in influence_paths]
    influence_weights = {inf: 0.0 for inf in influences}

    if not components:
        return influence_weights

    # Add components to a selection list to group them by dag path
    comp_sel = om.MSelectionList()
    for comp in components:
        comp_sel.add(comp)

    for i in range(comp_sel.length()):
        dag_path, comp_obj = comp_sel.getComponent(i)

        # Pull all weights for these specific components in one C++ call
        weights, num_influences = skin_fn.getWeights(dag_path, comp_obj)

        # weights is a flat array: [vtx0_inf0, vtx0_inf1, ..., vtx1_inf0, ...]
        for j, weight in enumerate(weights):
            if weight > 0:
                inf_name = influences[j % num_influences]
                influence_weights[inf_name] += weight

    # Sort dictionary by weight descending (highest weight first)
    sorted_influences = {k: v for k, v in sorted(influence_weights.items(), key=lambda item: item[1], reverse=True)}
    return sorted_influences


def create_jiggle_joints(parent_bone: str, centroid: List[float], name: str = "jiggle") -> Tuple[str, str]:
    """
    Creates the jiggle joint hierarchy:
    [parent_bone] -> [name_placeholder_jnt] (0 offset) -> [name_jnt] (offset to centroid).
    """
    cmds.select(clear=True)

    # 1. Create Placeholder Joint (matches parent_bone perfectly)
    placeholder = cmds.joint(name=f"{name}_placeholder_jnt")
    cmds.matchTransform(placeholder, parent_bone, pos=True, rot=True)

    # 2. Create the Jiggle Joint (offset to the centroid)
    jiggle = cmds.joint(name=f"{name}_jnt", position=centroid)

    # Optional: Orient the placeholder to point at the jiggle
    try:
        cmds.joint(placeholder, edit=True, orientJoint="xyz", secondaryAxisOrient="yup")
    except Exception:
        pass  # Orientation might fail if centroid perfectly overlaps parent

    # Parent the placeholder to the actual rig hierarchy
    if cmds.objExists(parent_bone):
        cmds.parent(placeholder, parent_bone)

    return placeholder, jiggle
