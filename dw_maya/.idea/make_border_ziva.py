
import maya.cmds as cmds
import maya.OpenMaya as om

def make_border():
    """ Creates a mesh between the edges of two objects with matching topology

      args:
          None

      returns:
          Name of the newly created mesh
    """

    border_mFnMesh = om.MFnMesh()
    border_mObject = om.MObject()

    selectedObjects = cmds.ls(os=True)
    cmds.select(selectedObjects[0], r=True)
    select_border_edges()
    mesh_1_borderEdges = cmds.ls(sl=True)
    cmds.select(selectedObjects[1], r=True)
    select_border_edges()
    cmds.select(mesh_1_borderEdges, add=True)

    selection_mSelectionList = om.MSelectionList()
    om.MGlobal.getActiveSelectionList(selection_mSelectionList)

    mesh_1_mDagPath = om.MDagPath()
    mesh_2_mDagPath = om.MDagPath()
    components_mObject = om.MObject()
    selection_mItSelectionList = om.MItSelectionList(selection_mSelectionList)

    selection_mItSelectionList.getDagPath(mesh_1_mDagPath, components_mObject)
    selection_mItSelectionList.next()
    selection_mItSelectionList.getDagPath(mesh_2_mDagPath)

    mesh_1_mItMeshEdge = om.MItMeshEdge(mesh_1_mDagPath, components_mObject)

    prevIndex_util = om.MScriptUtil()

    mesh_1_mItMeshVertex = om.MItMeshVertex(mesh_1_mDagPath)
    mesh_2_mItMeshVertex = om.MItMeshVertex(mesh_2_mDagPath)

    init_vertexArray_mFloatPointArray = om.MFloatPointArray()
    init_polygonCounts_mIntArray = om.MIntArray()
    init_polygonCounts_mIntArray.append(4)
    init_polygonConnects_mIntArray = om.MIntArray()
    for i in xrange(4):
        init_polygonConnects_mIntArray.append(i)

    while not mesh_1_mItMeshEdge.isDone():

        mesh_1_edgeVertices_list = list()

        mesh_1_edgeVertices_list.append(mesh_1_mItMeshEdge.index(0))
        mesh_1_edgeVertices_list.append(mesh_1_mItMeshEdge.index(1))

        mesh_1_mItMeshVertex.setIndex(mesh_1_edgeVertices_list[0],
                                      prevIndex_util.asIntPtr())
        mesh_1_edgeVertex_1_mPoint = mesh_1_mItMeshVertex.position(
            om.MSpace.kWorld)
        mesh_1_mItMeshVertex.setIndex(mesh_1_edgeVertices_list[1],
                                      prevIndex_util.asIntPtr())
        mesh_1_edgeVertex_2_mPoint = mesh_1_mItMeshVertex.position(
            om.MSpace.kWorld)

        mesh_2_mItMeshVertex.setIndex(mesh_1_edgeVertices_list[0],
                                      prevIndex_util.asIntPtr())
        mesh_2_edgeVertex_1_mPoint = mesh_2_mItMeshVertex.position(
            om.MSpace.kWorld)
        mesh_2_mItMeshVertex.setIndex(mesh_1_edgeVertices_list[1],
                                      prevIndex_util.asIntPtr())
        mesh_2_edgeVertex_2_mPoint = mesh_2_mItMeshVertex.position(
            om.MSpace.kWorld)

        # note: order reversed!!

        if mesh_1_mItMeshEdge.index() == 0:
            init_vertexArray_mFloatPointArray.append(
                om.MFloatPoint(mesh_1_edgeVertex_1_mPoint))
            init_vertexArray_mFloatPointArray.append(
                om.MFloatPoint(mesh_1_edgeVertex_2_mPoint))
            init_vertexArray_mFloatPointArray.append(
                om.MFloatPoint(mesh_2_edgeVertex_2_mPoint))
            init_vertexArray_mFloatPointArray.append(
                om.MFloatPoint(mesh_2_edgeVertex_1_mPoint))

            border_mObject = border_mFnMesh.create(4,
                                                   1,
                                                   init_vertexArray_mFloatPointArray,
                                                   init_polygonCounts_mIntArray,
                                                   init_polygonConnects_mIntArray)

        else:

            vertices_mPointArray = om.MPointArray()
            vertices_mPointArray.append(mesh_1_edgeVertex_1_mPoint)
            vertices_mPointArray.append(mesh_1_edgeVertex_2_mPoint)
            vertices_mPointArray.append(mesh_2_edgeVertex_2_mPoint)
            vertices_mPointArray.append(mesh_2_edgeVertex_1_mPoint)

            border_mFnMesh.addPolygon(vertices_mPointArray)

        mesh_1_mItMeshEdge.next()

    cmds.polyNormal(border_mFnMesh.name(), normalMode=2, userNormalMode=0, ch=0)
    assign_lambert1_to_mesh(border_mFnMesh.name())
    cmds.select(border_mFnMesh.name(), r=True)
    return border_mFnMesh.name()


def assign_lambert1_to_mesh(mesh_name):
    cmds.sets(mesh_name, e=True, forceElement='initialShadingGroup')


def select_border_edges():
    """ Selects the border edges of the currently selected mesh

      args:
          None

      returns:
          None
    """

    selection_mSelectionList = om.MSelectionList()
    om.MGlobal.getActiveSelectionList(selection_mSelectionList)
    mesh_mDagPath = om.MDagPath()

    selection_mSelectionList.getDagPath(0, mesh_mDagPath)

    mesh_mItMeshEdge = om.MItMeshEdge(mesh_mDagPath)
    borderEdges_list = list()

    numTriangles_mScriptUtil = om.MScriptUtil()
    numTriangles_intPtr = numTriangles_mScriptUtil.asIntPtr()

    while not mesh_mItMeshEdge.isDone():

        numConnectedFaces = int()
        mesh_mItMeshEdge.numConnectedFaces(numTriangles_intPtr)
        numConnectedFaces_int = numTriangles_mScriptUtil.getInt(
            numTriangles_intPtr)
        if numConnectedFaces_int < 2:
            borderEdges_list.append(mesh_mItMeshEdge.index())

        mesh_mItMeshEdge.next()

    borderEdges_mIntArray = om.MIntArray()
    for index in borderEdges_list:
        borderEdges_mIntArray.append(index)

    edges_mfnSIC = om.MFnSingleIndexedComponent()
    components_mObject = edges_mfnSIC.create(om.MFn.kMeshEdgeComponent)

    edges_mfnSIC.addElements(borderEdges_mIntArray)
    newSelectionList = om.MSelectionList()
    newSelectionList.add(mesh_mDagPath, components_mObject)

    om.MGlobal.setActiveSelectionList(newSelectionList)