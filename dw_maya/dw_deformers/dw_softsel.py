from maya import cmds, mel

import maya.OpenMaya as om
import maya.OpenMayaAnim as oma


def setClusterWeightsFromSoftSelection(clusterDeformer='', mesh='', geoFaces=[], falloffRadius=0):
    """
    Set cluster weights based on soft selection values or provided vertex components.

    Args:
        clusterDeformer (str): Name of the cluster deformer.
        mesh (str): Mesh object to apply the weights on.
        geoFaces (list): List of mesh faces (components) to set weights for.
        falloffRadius (float, optional): Radius for soft selection falloff. Defaults to 0.
    """

    # convert selection to verts
    vert = cmds.polyListComponentConversion(geoFaces, toVertex=True)
    cmds.select(vert, r=True)

    # Get soft select weights if falloffRadius is specified, else default to 1.0 weights
    if falloffRadius:
        cmds.softSelect(e=True, softSelectEnabled=True, ssd=falloffRadius)
        components, weights = querySoftSelection()
    else:
        # toVertex
        components = cmds.ls(vert, flatten=True)
        weights = [1.0] * len(components)

    # get cluster MObject
    oMSel = om.MSelectionList()
    oMSel.add(clusterDeformer)
    clusterMObject = om.MObject()
    oMSel.getDependNode(0, clusterMObject)

    # get geo MDagPath
    oMSel = om.MSelectionList()
    oMSel.add(mesh)
    geoMDagPath = om.MDagPath()
    oMSel.getDagPath(0, geoMDagPath)

    # create component MObject from list of components
    vertIds = [int(component[component.rfind('.vtx[') + 5:-1]) for component in components]
    util = om.MScriptUtil()
    util.createFromList(vertIds, len(vertIds))
    vertIdsPtr = util.asIntPtr()
    vertIdsMIntArray = om.MIntArray(vertIdsPtr, len(vertIds))

    singleIndexCompFn = om.MFnSingleIndexedComponent()
    vertComponentsMObject = singleIndexCompFn.create(om.MFn.kMeshVertComponent)
    singleIndexCompFn.addElements(vertIdsMIntArray)

    # set cluster weights
    util = om.MScriptUtil()
    util.createFromList(weights, len(weights))
    weightsPtr = util.asFloatPtr()
    weightsMFloatArray = om.MFloatArray(weightsPtr, len(weights))
    weightFn = oma.MFnWeightGeometryFilter(clusterMObject)
    weightFn.setWeight(geoMDagPath, vertComponentsMObject, weightsMFloatArray)


def querySoftSelection():
    """
    Query the soft selection in Maya and return the selected components and their corresponding weights.

    Returns:
        tuple: A tuple containing two lists:
            - components: A list of selected vertex components as strings.
            - weights: A list of corresponding weights for each vertex component.
    """
    # get the soft sel
    softSet = om.MRichSelection()
    om.MGlobal.getRichSelection(softSet)

    # get the sel
    sel = om.MSelectionList()
    softSet.getSelection(sel)

    dagPath = om.MDagPath()
    component = om.MObject()

    components, weights = [], []
    iter = om.MItSelectionList(sel, om.MFn.kMeshVertComponent)
    while not iter.isDone():
        iter.getDagPath(dagPath, component)
        dagPath.pop()  # popping the shape node off the path yields its parent (i.e the transform node)
        transform = dagPath.fullPathName()
        fnComponent = om.MFnSingleIndexedComponent(component)
        getWeight = lambda index: fnComponent.weight(index).influence() if fnComponent.hasWeights() else 1.0

        for index in range(fnComponent.elementCount()):
            components.append('%s.vtx[%i]' % (transform, fnComponent.element(index)))
            weights.append(getWeight(index))
        iter.next()
    return components, weights