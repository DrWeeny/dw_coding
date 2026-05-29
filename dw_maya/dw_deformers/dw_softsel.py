"""Soft-selection utilities for cluster weight transfer.

Features:
    - Query the current Maya soft selection and return components with weights.
    - Apply those weights (or flat 1.0 weights) to a cluster deformer via the OpenMaya API.

Functions:
    set_cluster_weights_from_soft_selection: Apply soft-selection weights to a cluster deformer.
    query_soft_selection: Return selected components and their soft-selection weights.

Example:
    import dw_maya.dw_deformers.dw_softsel as dw_softsel
    components, weights = dw_softsel.query_soft_selection()
    dw_softsel.set_cluster_weights_from_soft_selection(
        clusterDeformer="cluster1", mesh="pSphere1", geoFaces=components
    )

TODO:
    - Support non-mesh geometry types.

Author: dw_tools
"""
from typing import Union

from maya import cmds
import maya.OpenMaya
import maya.OpenMayaAnim

from enum import IntEnum

from dw_maya.dw_maya_utils import component_in_list

# --- Soft Select Modes ---
class FalloffMode(IntEnum):
    Volume = 0
    Surface = 1
    Global = 2
    Object = 3

def __selection_to_vertex(selection: Union[str, list]) -> list:
    """
    helper because doing this all the time
    """
    to_vertex = cmds.polyListComponentConversion(selection, toVertex=True)
    return cmds.ls(to_vertex, long=True, flatten=True)

def get_soft_selection_mode()->FalloffMode:
    value = cmds.softSelect(q=True, softSelectFalloff=True)
    return FalloffMode(value)

def get_soft_selection_state()->dict:
    """
    store the current soft selection state in tool settings
    """
    output = {}
    sse_was_enabled = cmds.softSelect(q=True, softSelectEnabled=True)
    output["sse_was_enabled"] = sse_was_enabled

    softSelectFalloff          = cmds.softSelect(q=True, softSelectFalloff=True)
    output["softSelectFalloff"] = softSelectFalloff
    # Save falloff curve if needed
    softSelectColorCurve          = cmds.softSelect(q=True, softSelectColorCurve=True)
    output["softSelectColorCurve"] = softSelectColorCurve

    softSelectDistance = cmds.softSelect(q=True, softSelectDistance=True)
    output["softSelectDistance"] = softSelectDistance

    softSelectCurve = cmds.softSelect(q=True, softSelectCurve=True)
    output["softSelectCurve"] = softSelectCurve

    return output

def set_soft_selection_state(selection:list,
                             softSelectDistance:float=None,
                             softSelectFalloff:FalloffMode=None,
                             **kwargs):
    """
    if soft selection is not enabled and values are set throught ui, we will need to activate the soft selection
    for the query

    kwargs :
        any soft select attribute we would like to edit/set
        mainly for falloff curve if supported in ui
    """
    # conform selection component to vertex
    if component_in_list(selection) not in ["vtx"]:
        selection =  __selection_to_vertex(selection)

    cmds.select(selection, replace=True)

    # enable soft select
    enabled = kwargs.get("softSelectEnabled", True)
    cmds.softSelect(edit=True, softSelectEnabled=enabled)
    kwargs.pop("softSelectEnabled", None)

    # set main values
    if softSelectDistance is not None:
        cmds.softSelect(edit=True, softSelectFalloff=softSelectFalloff)
    if softSelectFalloff is not None:
        cmds.softSelect(edit=True, softSelectDistance=softSelectDistance)
    for key, value in kwargs.items():
        sub_kwargs = {key: value}
        cmds.softSelect(edit=True, **sub_kwargs)


def restore_soft_selection_state(output:dict):
    """
    Args:
        output: dictionnary with cmds.softSelect kwargs to edit with their values
    """
    for key in output:
        kwargs = {key:output[key]}
        cmds.softSelect(edit=True, **kwargs)

def set_cluster_weights_from_soft_selection(
    clusterDeformer: str = "",
    mesh: str = "",
    geoFaces: list = None,
    falloffRadius: float = 0,
):
    """Set cluster weights based on soft selection values or provided vertex components.

    Args:
        clusterDeformer (str): Name of the cluster deformer.
        mesh (str): Mesh object to apply the weights on.
        geoFaces (list): List of mesh faces (components) to set weights for.
        falloffRadius (float): Radius for soft selection falloff. Defaults to 0.
    """
    if geoFaces is None:
        geoFaces = []

    # convert selection to verts
    vert = cmds.polyListComponentConversion(geoFaces, toVertex=True)
    cmds.select(vert, r=True)

    # get soft-select weights if falloffRadius is specified, else default to 1.0
    if falloffRadius:
        cmds.softSelect(e=True, softSelectEnabled=True, ssd=falloffRadius)
        components, weights = query_soft_selection()
    else:
        components = cmds.ls(vert, flatten=True)
        weights = [1.0] * len(components)

    # get cluster MObject
    o_m_sel = maya.OpenMaya.MSelectionList()
    o_m_sel.add(clusterDeformer)
    cluster_m_object = maya.OpenMaya.MObject()
    o_m_sel.getDependNode(0, cluster_m_object)

    # get geo MDagPath
    o_m_sel = maya.OpenMaya.MSelectionList()
    o_m_sel.add(mesh)
    geo_m_dag_path = maya.OpenMaya.MDagPath()
    o_m_sel.getDagPath(0, geo_m_dag_path)

    # build component MObject from vertex id list
    vert_ids = [int(c[c.rfind(".vtx[") + 5:-1]) for c in components]
    util = maya.OpenMaya.MScriptUtil()
    util.createFromList(vert_ids, len(vert_ids))
    vert_ids_m_int_array = maya.OpenMaya.MIntArray(util.asIntPtr(), len(vert_ids))

    single_index_comp_fn = maya.OpenMaya.MFnSingleIndexedComponent()
    vert_components_m_object = single_index_comp_fn.create(maya.OpenMaya.MFn.kMeshVertComponent)
    single_index_comp_fn.addElements(vert_ids_m_int_array)

    # set cluster weights
    util = maya.OpenMaya.MScriptUtil()
    util.createFromList(weights, len(weights))
    weights_m_float_array = maya.OpenMaya.MFloatArray(util.asFloatPtr(), len(weights))
    weight_fn = maya.OpenMayaAnim.MFnWeightGeometryFilter(cluster_m_object)
    weight_fn.setWeight(geo_m_dag_path, vert_components_m_object, weights_m_float_array)


def query_soft_selection() -> tuple:
    """Query the soft selection in Maya and return components with their weights.

    Returns:
        tuple: (components, weights) where components is a list of vertex strings
            and weights is a list of float influence values.
    """
    # retrieve rich (soft) selection
    soft_set = maya.OpenMaya.MRichSelection()
    maya.OpenMaya.MGlobal.getRichSelection(soft_set)

    sel = maya.OpenMaya.MSelectionList()
    soft_set.getSelection(sel)

    dag_path = maya.OpenMaya.MDagPath()
    component = maya.OpenMaya.MObject()

    components, weights = [], []
    it = maya.OpenMaya.MItSelectionList(sel, maya.OpenMaya.MFn.kMeshVertComponent)
    while not it.isDone():
        it.getDagPath(dag_path, component)
        # pop shape → get transform
        dag_path.pop()
        transform = dag_path.fullPathName()
        fn_component = maya.OpenMaya.MFnSingleIndexedComponent(component)

        def get_weight(index: int) -> float:
            if fn_component.hasWeights():
                return fn_component.weight(index).influence()
            return 1.0

        for index in range(fn_component.elementCount()):
            components.append(f"{transform}.vtx[{fn_component.element(index)}]")
            weights.append(get_weight(index))
        it.next()

    return components, weights

def list_soft_selection_mask() -> dict:
    """Return a per-transform full vertex mask from the current soft selection.

    For every transform that has selected vertices, builds a flat list of
    floats with length == vertex count.  Unselected vertices are 0.0,
    selected vertices carry their soft-selection weight.

    Returns:
        dict: {transform_name: [float, ...]}  one entry per affected mesh.

    Example::

        masks = list_soft_selection_mask()
        # masks['pSphere1'] → [0.0, 0.0, 0.7, 1.0, 0.0, ...]
    """
    soft_set = maya.OpenMaya.MRichSelection()
    maya.OpenMaya.MGlobal.getRichSelection(soft_set)

    sel = maya.OpenMaya.MSelectionList()
    soft_set.getSelection(sel)

    dag_path  = maya.OpenMaya.MDagPath()
    component = maya.OpenMaya.MObject()

    result: dict = {}

    it = maya.OpenMaya.MItSelectionList(sel, maya.OpenMaya.MFn.kMeshVertComponent)
    while not it.isDone():
        it.getDagPath(dag_path, component)
        dag_path.pop()                          # shape → transform
        transform = dag_path.fullPathName()

        # Build an all-zero mask sized to the full vertex count
        vtx_count = cmds.polyEvaluate(transform, vertex=True)
        if transform not in result:
            result[transform] = [0.0] * vtx_count

        fn_component = maya.OpenMaya.MFnSingleIndexedComponent(component)

        def _weight(idx: int) -> float:
            if fn_component.hasWeights():
                return fn_component.weight(idx).influence()
            return 1.0

        # Inject soft weights at the correct indices
        for idx in range(fn_component.elementCount()):
            vtx_idx = fn_component.element(idx)
            result[transform][vtx_idx] = _weight(idx)

        it.next()

    return result