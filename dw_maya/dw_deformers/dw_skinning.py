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
def get_vertex_influence_weights(skin_node: str,
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

def compute_weight_delta(bone_arrays: Dict[str, List[float]],
                         soft_mask: List[float],
                         selected_bones: List[str],
                         mesh_transform: str) -> Dict[str, object]:
    """Compute per-vertex weight redistribution toward the new jiggle joint.

    For each vertex *v* in the soft selection the soft mask value controls how
    much influence is transferred **from** each selected bone **to** the new
    jiggle joint:

        taken[v][b]      = bone_arrays[b][v] * soft_mask[v]
        jiggle[v]        = Σ taken[v][b]           (for b in selected_bones)
        bones[b][v]      = bone_arrays[b][v] - taken[v][b]
                         = bone_arrays[b][v] * (1 - soft_mask[v])

    All weights that are not touched remain unchanged, so the per-vertex total
    stays exactly 1.0 — Maya normalisation is preserved.

    Args:
        bone_arrays:     Output of ``get_vertex_influence_weights()``
                         ``{bone_name: [weight_per_vtx, ...]}``.
        soft_mask:       Full-length soft selection mask, values in [0, 1],
                         parallel to vertex order (0.0 → vertex not selected).
        selected_bones:  Bones to pull weight from (donor bones).
        mesh_transform:  Unused — kept for API consistency.

    Returns:
        ::

            {
                'jiggle': [float, ...],               # full vtx list, len == vtx_count
                'bones':  {bone: [float, ...]},        # full vtx list per donor bone
            }

        Every list is parallel to vertex order and can be fed directly to
        ``apply_weight_delta`` / ``MFnSkinCluster.setWeights`` in one call.

    Example::

        # jiggle = [0,  .4, .8, 1,  .2, ...]
        # bone1  = [.5, .5, .1, 0,  .5, ...]
        # bone2  = [.5, .1, .1, 0,  .3, ...]
    """
    vtx_count = len(soft_mask)

    jiggle: List[float] = [0.0] * vtx_count
    # start from a copy of the original so unaffected indices stay correct
    bones: Dict[str, List[float]] = {
        b: list(bone_arrays.get(b, [0.0] * vtx_count))
        for b in selected_bones
    }

    for vtx_idx, soft_w in enumerate(soft_mask):
        if soft_w <= 0.0:
            continue

        total_taken = 0.0
        for bone in selected_bones:
            arr = bone_arrays.get(bone)
            if arr is None or vtx_idx >= len(arr):
                continue
            orig = arr[vtx_idx]
            if orig <= 0.0:
                continue
            taken = orig * soft_w
            total_taken += taken
            bones[bone][vtx_idx] = orig - taken  # orig * (1 - soft_w)

        if total_taken > 0.0:
            jiggle[vtx_idx] = total_taken

    return {'jiggle': jiggle, 'bones': bones}


# ---------------------------------------------------------------------------
# apply_weight_delta
# ---------------------------------------------------------------------------

def apply_weight_delta(skin_node: str,
                       jiggle_joint: str,
                       delta: Dict[str, object],
                       normalize: bool = True) -> None:
    """Apply the delta from ``compute_weight_delta()`` in a single C++ call.

    Uses the **API 1.0** ``MFnSkinCluster.setWeights`` overload that accepts
    ``MIntArray`` + ``MDoubleArray`` — API 2.0's Python bindings mis-dispatch
    that overload regardless of argument wrapping.

    Only the jiggle joint and the donor bones are written; all other influence
    columns remain untouched.  Because the math in ``compute_weight_delta``
    guarantees the per-vertex total stays 1.0, ``normalize=False`` is used
    during the write to avoid Maya drifting the other influences.

    ``jiggle_joint`` must already be added as an influence (weight 0) before
    calling this.
    """
    import maya.OpenMaya as om1  # API 1.0 — correct MIntArray dispatch
    import maya.OpenMayaAnim as oma1

    jiggle_arr: List[float] = delta['jiggle']  # full vtx list
    bones_arr: Dict[str, List[float]] = delta['bones']
    vtx_count = len(jiggle_arr)

    # ------------------------------------------------------------------ #
    # 1. Resolve skin cluster via API 1.0
    # ------------------------------------------------------------------ #
    sel1 = om1.MSelectionList()
    sel1.add(skin_node)
    skin_obj = om1.MObject()
    sel1.getDependNode(0, skin_obj)
    skin_fn = oma1.MFnSkinCluster(skin_obj)

    # Build influence-name → physical-index map
    infs_paths = om1.MDagPathArray()
    skin_fn.influenceObjects(infs_paths)
    inf_idx: Dict[str, int] = {
        infs_paths[i].partialPathName(): i
        for i in range(infs_paths.length())
    }

    jiggle_phys = inf_idx.get(jiggle_joint)
    if jiggle_phys is None:
        # jiggle_joint may be a long DAG path — try the leaf name
        jiggle_short = jiggle_joint.split('|')[-1]
        jiggle_phys = inf_idx.get(jiggle_short)
    if jiggle_phys is None:
        raise RuntimeError(
            f"apply_weight_delta: '{jiggle_joint}' is not an influence of "
            f"'{skin_node}'. Add it with cmds.skinCluster(edit=True, addInfluence=…) first.\n"
            f"Known influences: {list(inf_idx.keys())}"
        )

    # ------------------------------------------------------------------ #
    # 2. DAG path from the skin cluster's output geometry
    # ------------------------------------------------------------------ #
    output_geoms = cmds.skinCluster(skin_node, q=True, geometry=True) or []
    if not output_geoms:
        raise RuntimeError(f"apply_weight_delta: no geometry found for '{skin_node}'")
    shape = output_geoms[0]  # shape name

    mesh_sel = om1.MSelectionList()
    mesh_sel.add(shape)
    dag_path = om1.MDagPath()
    mesh_sel.getDagPath(0, dag_path)

    # Sanity check: make sure our weight array length matches the mesh
    actual_vtx = cmds.polyEvaluate(shape, vertex=True)
    if isinstance(actual_vtx, int) and actual_vtx != vtx_count:
        raise RuntimeError(
            f"apply_weight_delta: jiggle array length ({vtx_count}) != "
            f"mesh vertex count ({actual_vtx}) on '{shape}'. "
            "soft_mask was probably built from a different mesh."
        )

    # Explicit complete-vertex component — avoids the deformer-set member
    # mismatch that causes kFailure when partial membership is involved.
    fn_comp = om1.MFnSingleIndexedComponent()
    components = fn_comp.create(om1.MFn.kMeshVertComponent)
    fn_comp.setCompleteData(vtx_count)

    # ------------------------------------------------------------------ #
    # 3. Build MIntArray — physical indices of modified influences only
    #    (jiggle + donor bones that actually exist in this skin cluster)
    #    Keys in bones_arr may be long DAG paths — normalise to partial name.
    # ------------------------------------------------------------------ #
    def _resolve_inf(name: str) -> int:
        """Return physical index for name, trying long then leaf form."""
        idx = inf_idx.get(name)
        if idx is None:
            idx = inf_idx.get(name.split('|')[-1])
        return idx  # None if not found

    jiggle_key = jiggle_joint.split('|')[-1] if jiggle_phys is not None else jiggle_joint
    mod_names: List[str] = [jiggle_joint] + [
        b for b in bones_arr if _resolve_inf(b) is not None
    ]
    n_mod = len(mod_names)

    inf_arr = om1.MIntArray()
    inf_arr.setLength(n_mod)
    inf_arr.set(jiggle_phys, 0)
    for i, name in enumerate(mod_names[1:], start=1):
        inf_arr.set(_resolve_inf(name), i)

    # ------------------------------------------------------------------ #
    # 4. Build MDoubleArray — flat layout:
    #    [vtx0_inf0, vtx0_inf1, …, vtx0_infM,  vtx1_inf0, …, vtxN_infM]
    # ------------------------------------------------------------------ #
    wt_arr = om1.MDoubleArray()
    wt_arr.setLength(vtx_count * n_mod)

    for vi in range(vtx_count):
        base = vi * n_mod
        for ii, name in enumerate(mod_names):
            if name == jiggle_joint:
                w = jiggle_arr[vi]
            else:
                arr = bones_arr.get(name, [])
                w = arr[vi] if vi < len(arr) else 0.0
            wt_arr.set(w, base + ii)

    # ------------------------------------------------------------------ #
    # 5. Single C++ call — no per-vertex Python loop, no skinPercent
    # ------------------------------------------------------------------ #
    skin_fn.setWeights(dag_path, components, inf_arr, wt_arr, False)

    # Optional drift cleanup (floating-point only — our math is already exact)
    if normalize:
        cmds.skinCluster(skin_node, edit=True, forceNormalizeWeights=True)


# ---------------------------------------------------------------------------
# get_participation
# ---------------------------------------------------------------------------
def get_participation(bone_arrays: Dict[str, List[float]],
                      soft_mask: List[float],
                      heat_participation: float = 0) -> Dict[str, float]:
    """Return each bone's soft-weighted participation percentage.

    Multiplies the bone weight at each vertex by the soft mask value then
    sums — one ``sum()`` call per bone, no inner loop visible in Python.

    Args:
        bone_arrays: Output of ``get_vertex_influence_weights``.
        soft_mask:   Full-length soft selection mask (parallel to vertex order).
        heat_participation: if the soft selection is wide, you might want to evaluate the participation on a certain threshold value
                    within the soft selection weights

    Returns:
        ``{bone_name: percentage}`` sorted descending, values sum ~100.
    """
    totals: Dict[str, float] = {}
    if isinstance(heat_participation, (float, int)):
        # value should be between 0 and 1
        if not heat_participation >= 0 and not heat_participation <= 1.0:
            heat_participation = 0
    else:
        heat_participation = 0

    for bone, arr in bone_arrays.items():
        # element-wise multiply then sum — vectorised in CPython built-ins
        total = sum(w * s for w, s in zip(arr, soft_mask) if s > heat_participation)
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
