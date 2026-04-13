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

import maya.cmds
import maya.OpenMaya
import maya.OpenMayaAnim


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
    vert = maya.cmds.polyListComponentConversion(geoFaces, toVertex=True)
    maya.cmds.select(vert, r=True)

    # get soft-select weights if falloffRadius is specified, else default to 1.0
    if falloffRadius:
        maya.cmds.softSelect(e=True, softSelectEnabled=True, ssd=falloffRadius)
        components, weights = query_soft_selection()
    else:
        components = maya.cmds.ls(vert, flatten=True)
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
