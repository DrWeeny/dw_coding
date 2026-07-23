from maya import cmds, mel
import maya.OpenMaya as om
import re

from dw_maya.dw_decorators import acceptString, singleUndoChunk
from dw_maya.dw_create import pointOnPolyConstraint


class _CycleCheckSuppressed:
    """Temporarily disable Maya's cycle check.
       During the creation setup, a cycle warning is resolved so lets not print it
       in the console
    """

    def __enter__(self):
        self._was_on = cmds.cycleCheck(query=True, evaluation=True)
        cmds.cycleCheck(evaluation=False)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        cmds.cycleCheck(evaluation=self._was_on)
        return False


@singleUndoChunk
def createSticky(componentSel=None,
                 parent=None,
                 _type='softMod',
                 before=True,
                 falloffRadius:float=.5,
                 **kwargs):
    """
    Args:
    Kwargs :
        ctrl_radius : default equal to falloffRadius but ctrl size can be set to another value
    """
    ctrl_radius = kwargs.get('ctrl_radius', None)

    # Get the selected components if not provided
    if not componentSel:
        componentSel = cmds.ls(sl=True, fl=True)

    # Ensure there is a valid selection
    if not componentSel:
        cmds.error("No components selected. Please select mesh components (faces, vertices, etc.).")
        return

    # Create a parent group if none is provided
    if not parent:
        if not cmds.objExists('sticky_grp'):
            grp = cmds.group(em=True, n='sticky_grp')
        else:
            grp = 'sticky_grp'
    else:
        grp = parent

    # Create sticky deformers (softMod, cluster, etc.)
    out = createStickyDeformers(_type, parent=grp, inputFaces=componentSel, before=before, ctrl_radius=ctrl_radius)

    # Set the falloff radius to 0.5 (adjust as needed)
    cmds.setAttr("{}.falloffRadius".format(out[0][0]), falloffRadius)

    return out


def createStickyDeformers(deformerType, name=None, parent=None, inputFaces=[], ssr=False, before=True, ctrl_radius=None):
    # Filter selection
    meshFaces, meshVerts, meshTransforms, nurbsSurfaceTransforms, nurbsCurvesTransforms = filterSelection(inputFaces)

    # Vertex input takes precedence when present; otherwise fall back to faces.
    if meshVerts:
        driverComponents = meshVerts
        componentType = 'vtx'
    else:
        driverComponents = meshFaces
        componentType = 'f'

    # Multi-face selection handling (Currently commented out logic for UI multi-mode)
    multiFaceMode = False
    driverComponent = driverComponents[-1] if driverComponents else None  # Default to last selected

    # Check user preferences for selection order tracking
    if not multiFaceMode:
        cmds.selectPref(trackSelectionOrder=True)

    # Find deformer members (geometry to which deformer will be applied)
    obj = cmds.ls(driverComponent, o=True)
    meshTransforms = cmds.listRelatives(obj, p=True)
    deformerMembers = list(set(meshTransforms + nurbsSurfaceTransforms + nurbsCurvesTransforms))

    # Set name prefix if not provided
    if not name:
        name = ''

    # Get the falloff radius for soft selection
    falloffRadius = getFalloffRadius(ssr)
    if not ctrl_radius:
        ctrl_radius = falloffRadius

    # Define parent group for controls if none exists
    stickyControlsParent = parent if parent else 'sticky_grp'
    if not cmds.objExists(stickyControlsParent):
        stickyControlsParent = cmds.group(empty=True, name=stickyControlsParent)

    # Create sticky controls
    stickyControls = createStickyControls(
        driverComponents=driverComponent,
        componentType=componentType,
        createControlParentGroupsOnly=False,
        stickyControlsParent=stickyControlsParent,
        radius=ctrl_radius,
        namePrefix=name,
        before=before
    )

    # Create deformers
    deformer_output = createDeformers(
        deformerType=deformerType,
        name='',
        parents=stickyControls,
        members=deformerMembers,
        falloffRadius=falloffRadius,
        createOffsetCtrls=False,
        before=before,
        ctrl_radius=ctrl_radius
    )

    return stickyControls, deformer_output


@acceptString('parents')
def createDeformers(deformerType, name='', parents=[], members=[],
                    falloffRadius=None, createOffsetCtrls=False, before=True, ctrl_radius=None ):


    falloffRadius = falloffRadius or 1.0
    ctrl_radius = ctrl_radius or falloffRadius

    if not members:
        print("No geometry provided. Nothing created")
        return None

    deformers = []
    offsetCtrls = []  # will be returned by this function
    baseName = name
    for parentNum, parent in enumerate(parents):
        if not createOffsetCtrls:
            uniqueOffsetCtrlName = getUniqueBaseName(srcObjName=parent, dstSuffixes=['_offset_ctrl'])
            parent = cmds.rename(parent, uniqueOffsetCtrlName + '_offset_ctrl')

        name = getUniqueBaseName(srcObjName=parent, dstSuffixes=['_' + deformerType, '_ctrl'])

        # create a curve for control
        print(f"debug ctrl radius {ctrl_radius}")
        ctrl = _create_control(deformerType, name, falloffRadius=ctrl_radius)

        # offset ctrl --------------------------------------------------------------------------------------------------
        offsetCtrl = _create_offset_control(name, ctrl_radius, createOffsetCtrls, parent)

        # Add locator shape to access worldPosition
        offsetCtrlLocatorShape = _add_locator_shape_to_offset_ctrl(offsetCtrl)

        verts = all(re.search(r"\.vtx\[", member) for member in members)

        # check if only verts are given as members, but no parent
        if not parent and verts:
            dummy = cmds.cluster(members, name="DELETE", bf=1)[1]
            pos = cmds.xform(dummy, q=1, ws=1, rp=1)
            cmds.delete(dummy)
            cmds.xform(offsetCtrl, ws=1, t=pos)
            cmds.xform(ctrl, ws=1, t=pos)
        elif parent:
            pos = cmds.xform(parent, q=1, ws=1, rp=1)
            cmds.xform(offsetCtrl, ws=1, t=pos)

            rot = cmds.xform(parent, q=1, ws=1, ro=1)
            cmds.xform(offsetCtrl, ws=1, ro=rot)

        # deformer creation
        deformer, ctrl = _deformer_setup(members, name,
                        weightNode=[ctrl, ctrl],
                        offsetCtrl=offsetCtrlLocatorShape,
                        falloffRadius=falloffRadius,
                        deformerType=deformerType,
                        before=before)

        _no_double_transform(members, deformer)

        cmds.parent(ctrl, offsetCtrl)

        axis = "tr"
        for a in axis:
            cmds.setAttr(f"{ctrl}.{a}", *[0,0,0])

        if createOffsetCtrls:
            cmds.parent(offsetCtrl, parent)

        deformers.append(deformer)
        offsetCtrls.append(offsetCtrl)

    return deformers, offsetCtrls

# Helper functions
def filterSelection(inputFaces=[]):
    if not inputFaces:
        sel = cmds.ls(orderedSelection=True, fl=True)
    else:
        sel = cmds.ls(inputFaces, fl=True)
    meshFaces = cmds.filterExpand(sel, expand=True, selectionMask=34) or []
    meshVerts = cmds.filterExpand(sel, expand=True, selectionMask=31) or []
    meshTransforms = cmds.filterExpand(expand=True, selectionMask=12) or []
    nurbsSurfaceTransforms = cmds.filterExpand(expand=True, selectionMask=10) or []
    nurbsCurvesTransforms = cmds.filterExpand(expand=True, selectionMask=9) or []
    return meshFaces, meshVerts, meshTransforms, nurbsSurfaceTransforms, nurbsCurvesTransforms


def getFalloffRadius(ssr):
    if ssr:
        if cmds.softSelect(q=True, softSelectEnabled=True):
            return cmds.softSelect(q=True, softSelectDistance=True)
        return 0.0
    return 0.5


def generate_control_name(geo_name, component, name_prefix=''):
    """
    Generates a unique control name based on the mesh and component information
    or using a provided name prefix.
    """
    if name_prefix:
        base_name = name_prefix
    else:
        base_name = geo_name.replace(":", "_") + "_" + component
    return getUniqueBaseName(base_name, dstSuffixes=['_zro', '_ctrl', '_follicle', '_follicleShape'])


def create_control_group(name, radius=1.0, create_control=False):
    """
    Creates a control and its parent zero group, or just the zero group if create_control is False.
    """
    ctrl_zro = ''
    if create_control:
        # only create (empty) groups
        ctrl_zro = cmds.group(empty=True, n=name + '_zro')

    else:
        # create control parent groups (_zro) and control (_ctrl) objects
        ctrl = cmds.circle(n=name + '_ctrl', ch=0, radius=radius)[0]
        cmds.rotate(-90, 0, 0, ctrl + ".cv[0:7]", os=True, r=True)
        cmds.setAttr(ctrl + '.v', keyable=False, channelBox=False)
        ctrlShape = cmds.listRelatives(ctrl, shapes=True)[0]
        cmds.setAttr((ctrlShape + ".overrideEnabled"), 1)
        cmds.setAttr((ctrlShape + ".overrideColor"), 27)

        ctrl_zro = cmds.group(ctrl, n=name + '_zro')

    return ctrl, ctrl_zro

def create_follicle_constraint(ctrl_zro, mesh_shape, uv, base_name, in_mesh_con):
    """
    Creates a follicle and sets it up to drive the control group.
    """
    from dw_maya.dw_nucleus_utils import create_follicles
    follicle = create_follicles(mesh_shape, uv, name=base_name + '_follicle')
    follicle_shape = cmds.listRelatives(follicle)[0]
    cmds.setAttr(follicle_shape + '.v', 0)
    cmds.connectAttr(in_mesh_con, follicle_shape + '.inputMesh', f=1)

    # Parent the control zero group to the follicle
    cmds.parent(ctrl_zro, follicle, relative=1)
    normal_cnt = cmds.normalConstraint(mesh_shape, ctrl_zro,
                                       weight=1, aimVector=(0, 1, 0), upVector=(0, 0, 1),
                                       worldUpVector=(0, 0, 1), worldUpType='scene')
    cmds.delete(normal_cnt)

    return follicle


def getFaceCenterPositions(meshFaces, returnMPoints=False):
    """
    Returns the center position of faces in world space for the given mesh faces.

    Args:
        meshFaces (list): A list of mesh face components (e.g., 'pSphereShape1.f[154]').
        returnMPoints (bool): If True, return MPoint objects; otherwise, return a list of [x, y, z].

    Returns:
        dict: A dictionary where keys are face components and values are either MPoints or lists of world coordinates.
    """
    dFaceVsFacePosition = {}
    selMSelectionList = om.MSelectionList()

    # Add each face to the MSelectionList
    for face in meshFaces:
        selMSelectionList.add(face)

    dagPathMDagPath = om.MDagPath()
    componentMObject = om.MObject()

    # Iterate over the selection list (mesh polygon components)
    iterSel = om.MItSelectionList(selMSelectionList, om.MFn.kMeshPolygonComponent)
    while not iterSel.isDone():
        iterSel.getDagPath(dagPathMDagPath, componentMObject)
        partialPath = dagPathMDagPath.partialPathName()  # Mesh name without the full DAG path

        # Iterator for the mesh polygons
        polyIter = om.MItMeshPolygon(dagPathMDagPath, componentMObject)
        while not polyIter.isDone():
            index = polyIter.index()
            centerMPoint = polyIter.center(om.MSpace.kWorld)  # Get center of the face in world space

            key = f'{partialPath}.f[{index}]'  # Create a key for the face

            # Store the center position either as an MPoint or a list of [x, y, z]
            if returnMPoints:
                dFaceVsFacePosition[key] = centerMPoint
            else:
                dFaceVsFacePosition[key] = [centerMPoint.x, centerMPoint.y, centerMPoint.z]

            polyIter.next()  # Move to the next face

        iterSel.next()  # Move to the next selected item

    return dFaceVsFacePosition


def getVertexPositions(meshVerts, returnMPoints=False):
    """
    Returns the world-space position of each given mesh vertex.

    Args:
        meshVerts (list): A list of mesh vertex components (e.g., 'pSphereShape1.vtx[12]').
        returnMPoints (bool): If True, return MPoint objects; otherwise, return a list of [x, y, z].

    Returns:
        dict: A dictionary where keys are vertex components and values are either MPoints or lists of world coordinates.
    """
    dVertexPosition = {}
    selMSelectionList = om.MSelectionList()

    # Add each vertex to the MSelectionList
    for vtx in meshVerts:
        selMSelectionList.add(vtx)

    dagPathMDagPath = om.MDagPath()
    componentMObject = om.MObject()

    # Iterate over the selection list (mesh vertex components)
    iterSel = om.MItSelectionList(selMSelectionList, om.MFn.kMeshVertComponent)
    while not iterSel.isDone():
        iterSel.getDagPath(dagPathMDagPath, componentMObject)
        partialPath = dagPathMDagPath.partialPathName()  # Mesh name without the full DAG path

        # Iterator for the mesh vertices
        vtxIter = om.MItMeshVertex(dagPathMDagPath, componentMObject)
        while not vtxIter.isDone():
            index = vtxIter.index()
            posMPoint = vtxIter.position(om.MSpace.kWorld)  # World-space position of the vertex

            key = f'{partialPath}.vtx[{index}]'  # Create a key for the vertex

            # Store the position either as an MPoint or a list of [x, y, z]
            if returnMPoints:
                dVertexPosition[key] = posMPoint
            else:
                dVertexPosition[key] = [posMPoint.x, posMPoint.y, posMPoint.z]

            vtxIter.next()  # Move to the next vertex

        iterSel.next()  # Move to the next selected item

    return dVertexPosition


def getUniqueBaseName(srcObjName, dstSuffixes=[]):
    """
    Finds a unique base name for all given destination suffixes "dstSuffixes", based on the given source object name.
    The source object name can contain a suffix itself, which will be ignored if it's part of the internal list "suffixes".

    Args:
        srcObjName (str): The name of the source object.
        dstSuffixes (list): A list of suffixes to append to the base name for uniqueness testing.

    Returns:
        str: The first unique base name that does not conflict with any existing Maya objects.
    """

    # Strip off common suffixes to get the baseName
    suffixes = ['_offset_ctrl', '_parent_ctrl', '_offset', '_ctrl', '_locator', '_zro', '_parent']
    baseName = srcObjName

    for suffix in suffixes:
        if srcObjName.endswith(suffix):
            baseName = srcObjName[:srcObjName.rfind(suffix)]
            break

    # Function to test if a name combined with any suffix already exists
    def nameExists(baseName):
        return any(cmds.objExists(f"{baseName}{dstSuffix}") for dstSuffix in dstSuffixes)

    # Check if the baseName is unique without appending a number
    if not nameExists(baseName):
        return baseName

    # If the baseName is not unique, append a number to make it unique
    match = re.search(r'(\d+)$', baseName)
    if match:
        count = int(match.group(1))
        baseName = baseName[:match.start()]  # Remove the trailing digits
    else:
        count = 1

    # Increment count until a unique name is found
    while True:
        testName = f"{baseName}{count}"
        if not nameExists(testName):
            return testName
        count += 1


def _resolve_history_source(mesh_shape, before):
    """Return (in_mesh_con, temp_cluster) -- the mesh-typed plug to feed a
    positioning follicle's inputMesh, and a throwaway cluster (or None) to
    delete afterward if one had to be created.

    When before is True, the new sticky deformer will sit upstream of
    anything already in mesh_shape's history (an existing skinCluster, an
    earlier sticky's softMod...). Tracking the CURRENT live output would
    create a cycle once inserted -- that output would end up depending on
    the new deformer, while the new deformer's positioning control depends
    on that same output via the follicle. Track the shape's true
    pre-deformation geometry instead: deformableShape's originalGeometry
    query reports it directly if a deformer has already forced its
    creation (confirmed: it does NOT depend on which deformer, so this is
    safe even with an existing skinCluster). If no deformer has ever
    touched this shape, Maya only creates the intermediate Orig shape when
    a real deformer is added, so a throwaway cluster is used to force it --
    deleting it afterward reconnects every listener of its output, not
    just the main deformation chain, directly to the newly-created Orig
    shape (verified empirically, not a guess).

    When before is False, the new deformer goes downstream of whatever's
    already there, so it's safe (and desired -- e.g. reacting to an
    existing skinCluster's pose) to track the current live output.
    """
    temp_cluster = None

    def _force_orig_shape():
        cluster_nodes = cmds.cluster(mesh_shape, name='temp_cluster')
        source = cmds.connectionInfo(mesh_shape + '.inMesh', sourceFromDestination=True)
        return source, cluster_nodes

    if before:
        orig_plug = cmds.deformableShape(mesh_shape, originalGeometry=True)[0]
        if orig_plug:
            in_mesh_con = orig_plug
        else:
            in_mesh_con, temp_cluster = _force_orig_shape()
    else:
        in_mesh_con = cmds.connectionInfo(mesh_shape + '.inMesh', sourceFromDestination=True)
        if not in_mesh_con:
            orig_plug = cmds.deformableShape(mesh_shape, originalGeometry=True)[0]
            if orig_plug:
                in_mesh_con = orig_plug
            else:
                in_mesh_con, temp_cluster = _force_orig_shape()

    return in_mesh_con, temp_cluster


def createStickyControls(driverComponents=[], componentType='f', createControlParentGroupsOnly=False,
                         stickyControlsParent='', radius=1.0,
                         namePrefix='', constrainViaFollicles=True, before=True):
    """
    Creates sticky controls (or empty parent groups) constrained to a mesh surface, using follicles or pointOnPolyConstraint.

    Args:
        driverComponents: face ('mesh.f[N]') or vertex ('mesh.vtx[N]') component(s) driving each control's position.
        componentType: 'f' for faces (default) or 'vtx' for vertices -- selects the selectionMask/position lookup used.
        before: Must match whatever `before` the caller will use when actually
            inserting the deformer (see createSticky). When True, the new
            deformer will sit upstream of anything already in the mesh's
            history, so the follicle positioning each control MUST track the
            true pre-deformation geometry -- tracking whatever currently
            feeds inMesh would make that existing output depend on the new
            deformer once inserted (a cycle). When False, the new deformer
            goes downstream, so tracking the current live output is correct
            and desired (e.g. reacting to an existing skinCluster's pose).
    """
    bGenerateName = not namePrefix
    sticky_controls = []
    sticky_control_zeroes = []
    follicles = []

    mask = 31 if componentType == 'vtx' else 34
    mesh_components = cmds.filterExpand(driverComponents, expand=True, selectionMask=mask)
    if componentType == 'vtx':
        d_component_position = getVertexPositions(mesh_components, returnMPoints=True)
    else:
        d_component_position = getFaceCenterPositions(mesh_components, returnMPoints=True)

    for driver in mesh_components:
        geo_name, comp_num = driver.split(".")
        component = re.sub(r'[^a-zA-Z0-9]', '_', comp_num)

        if bGenerateName:
            base_name = geo_name.replace(":", "_") + "_" + component
        else:
            base_name = namePrefix

        name = getUniqueBaseName(base_name, dstSuffixes=['_zro', '_ctrl', '_follicle', '_follicleShape'])

        # Create control or parent group
        ctrl, ctrl_zero = create_control_group(name, radius, createControlParentGroupsOnly)
        sticky_controls.append(ctrl)
        sticky_control_zeroes.append(ctrl_zero)

        if component:
            cmds.addAttr(ctrl_zero, ln="following", dt="string")
            cmds.setAttr(ctrl_zero + ".following", driver, type="string")

        # Maya reports vertex component selections either transform-qualified
        # ('pSphere1.vtx[0]') or shape-qualified ('pSphere1Shape.vtx[0]')
        # depending on scene state (e.g. merely having a joint in the scene
        # can flip it) -- resolve to the shape only when geo_name isn't
        # already one.
        mesh_shape = geo_name
        if cmds.nodeType(geo_name) != 'mesh':
            mesh_shape = cmds.listRelatives(geo_name, noIntermediate=1, shapes=1, fullPath=1)[0]

        in_mesh_con, temp_cluster = _resolve_history_source(mesh_shape, before)

        # Get UVs and setup follicle or pointOnPoly constraint
        sh_only = mesh_shape.split("|")[-1]  # key is only the shape's short name (matches partialPathName())
        component_m_point = d_component_position[f'{sh_only}.{comp_num}']
        # delay import to avoid circular call
        from dw_maya.dw_maya_utils import closest_uv_on_mesh
        uv = closest_uv_on_mesh(mesh_shape, position=component_m_point)

        if constrainViaFollicles:
            follicle = create_follicle_constraint(ctrl_zero, mesh_shape, uv, base_name, in_mesh_con)
            follicles.append(follicle)
        else:
            # not supported because bug on fullpath
            pop_cnt = pointOnPolyConstraint(driver, ctrl_zero)

        if temp_cluster:
            cmds.delete(temp_cluster)

    # group all controls (and follicles) under one single parent node (if the stickyControlsParent arg was provided)
    if stickyControlsParent:
        # create a group if the stickyControlsParent obj doesn't exist yet
        if not cmds.objExists(stickyControlsParent):
            stickyControlsParent = cmds.group(empty=True, name=stickyControlsParent)

        if constrainViaFollicles:
            cmds.parent(follicles, stickyControlsParent)
        else:
            cmds.parent(sticky_control_zeroes, stickyControlsParent)

    return sticky_control_zeroes if createControlParentGroupsOnly else sticky_controls


def updateLocators(locators):
    if locators:
        for i, loc in enumerate(locators):
            if cmds.objExists(loc + ".following"):
                # get rid of any keys on it
                for attr in cmds.listAttr(loc):
                    cmds.cutKey(loc, cl=1, at=attr)
                constTo = cmds.getAttr(loc + ".following")
                cmds.select(constTo, r=1)
                cmds.select(loc, add=1)
                cmd = 'doCreatePointOnPolyConstraintArgList 1 { "0","0","0","1","","1" };'
                res = mel.eval(cmd)
            else:
                locators.pop(i)

        if locators:
            # now we have them all, lets bake them.
            # hide everything
            # here we hide all visible top nodes
            topNodes = cmds.ls(assemblies=True)
            nodesHidden = []
            for x in topNodes:
                if cmds.getAttr(x + ".v") == 1:
                    try:
                        cmds.setAttr(x + ".v", 0)
                        nodesHidden.append(x)
                    except:
                        pass
            cmds.select(cl=True)
            # bake
            start = cmds.playbackOptions(q=1, min=1)
            end = cmds.playbackOptions(q=1, max=1)
            cmds.bakeResults(locators, t=(start, end), sampleBy=1, simulation=1, at=("translate", "rotate", "scale"))
            # make sure we  make them visible again
            for loc in locators:
                cmds.delete(cmds.listRelatives(loc, type="constraint"))

            for x in nodesHidden:
                cmds.setAttr(x + ".v", 1)

            return locators
        else:
            return None
    else:
        return None


def _create_control(deformerType: str, name: str, falloffRadius: float) -> str:
    """
    Creates a control object for the given deformer type.

    Args:
        deformerType (str): The type of deformer (cluster, softMod, or locator).
        name (str): The base name for the control.
        falloffRadius (float): The radius for the control falloff.

    Returns:
        str: The name of the created control object.
    """
    if deformerType == "cluster":
        ctrl = cmds.curve(
            name=name + "_ctrl", d=1,
            p=[(-0.25, -0.25, -0.25), (-0.25, 0.25, -0.25), (-0.25, 0.25, 0.25), (-0.25, -0.25, 0.25),
               (-0.25, -0.25, -0.25), (0.25, -0.25, -0.25), (0.25, 0.25, -0.25), (-0.25, 0.25, -0.25),
               (-0.25, -0.25, 0.25), (0.25, -0.25, -0.25), (0.25, 0.25, -0.25), (0.25, 0.25, 0.25),
               (0.25, -0.25, 0.25), (0.25, -0.25, -0.25), (0.25, -0.25, 0.25), (-0.25, -0.25, 0.25),
               (-0.25, 0.25, 0.25), (0.25, 0.25, 0.25)]
        )
        if falloffRadius != 1.0:
            cmds.xform(ctrl, scale=[falloffRadius * 4] * 3)
            cmds.makeIdentity(ctrl, s=True, r=False, t=False, apply=True, normal=0, preserveNormals=True)

    elif deformerType == "softMod":
        ctrl = cmds.group(em=True, name=name + "_ctrl")
        circleX = cmds.circle(name=name + "X", nr=(1, 0, 0), sw=360, r=falloffRadius, d=3, ut=0, tol=0.01, s=8, ch=False)[0]
        circleY = cmds.circle(name=name + "Y", nr=(0, 1, 0), sw=360, r=falloffRadius, d=3, ut=0, tol=0.01, s=8, ch=False)[0]
        circleZ = cmds.circle(name=name + "Z", nr=(0, 0, 1), sw=360, r=falloffRadius, d=3, ut=0, tol=0.01, s=8, ch=False)[0]
        cmds.parent(circleX + "Shape", circleY + "Shape", circleZ + "Shape", ctrl, r=True, s=True)
        cmds.delete(circleX, circleY, circleZ)

    elif deformerType == "locator":
        ctrl = cmds.curve(name=name + "_ctrl", d=1,
                          p=[(0, 1, 0), (0, -1, 0), (0, 0, 0), (0, 0, -1), (0, 0, 1), (0, 0, 0), (1, 0, 0), (-1, 0, 0)],
                          k=[0, 1, 2, 3, 4, 5, 6, 7])
        if falloffRadius != 1.0:
            cmds.xform(ctrl, scale=[falloffRadius * 2] * 3)
            cmds.makeIdentity(ctrl, s=True, apply=True)

    return ctrl


def _create_offset_control(name: str, falloffRadius: float, createOffsetCtrls: bool, parent: str) -> str:
    """
    Creates or reuses an offset control for the deformer.

    Args:
        name (str): The base name for the offset control.
        falloffRadius (float): The falloff radius for the control.
        createOffsetCtrls (bool): Whether to create a new offset control.
        parent (str): The parent object to use if not creating a new offset control.

    Returns:
        str: The name of the created or reused offset control.
    """
    if createOffsetCtrls:
        offsetCtrl = cmds.circle(n=name + '_offset_ctrl', ch=False, radius=falloffRadius * 0.5 * 0.1)[0]
        cmds.rotate(-90, 0, 0, offsetCtrl + ".cv[0:7]", os=True, r=True)
        cmds.setAttr(offsetCtrl + '.v', keyable=False, channelBox=False)
        offsetCtrlShape = cmds.listRelatives(offsetCtrl, shapes=True)[0]
        cmds.setAttr(offsetCtrlShape + ".overrideEnabled", 1)
        cmds.setAttr(offsetCtrlShape + ".overrideColor", 27)
    else:
        offsetCtrl = parent

    return offsetCtrl


def _add_locator_shape_to_offset_ctrl(offsetCtrl: str):
    """
    Adds a locator shape to the offset control for accessing the worldPosition attribute.

    Args:
        offsetCtrl (str): The name of the offset control.
    """
    tempLocator = cmds.spaceLocator()[0]
    offsetCtrlLocatorShape = cmds.listRelatives(tempLocator, shapes=True)[0]
    offsetCtrlLocatorShape = cmds.parent(offsetCtrlLocatorShape, offsetCtrl, r=True, s=True)[0]
    cmds.setAttr(offsetCtrlLocatorShape + '.visibility', 0)
    cmds.delete(tempLocator)
    offsetCtrlLocatorShape = cmds.rename(offsetCtrlLocatorShape, offsetCtrl + "Shape")
    return offsetCtrlLocatorShape


def _deformer_setup(members, name,
                     weightNode: list,
                     offsetCtrl: str,
                     falloffRadius: float,
                     deformerType: str,
                     before: bool = True):
    """
    Connects the deformer to the members and sets up the required connections.

    Args:
        ctrl (str): The control object.
        offsetCtrl (str): The offset control object.
        members (list): The list of objects or components to deform.
        meshFaces (list): The list of mesh faces for deformation.
        falloffRadius (float): The falloff radius for the deformation.
        deformerType (str): The type of deformer ('cluster', 'softMod').
        multiFaceMode (bool): Whether to apply multi-face deformation.
        before (bool): Insert this deformer BEFORE existing deformers in the
            member's history (True, default) or AFTER them (False). On an
            already-skinned mesh, True creates a cycle -- the sticky
            control is positioned by a follicle tracking the live,
            already-deformed surface, and inserting the sticky before the
            skinCluster makes the skinCluster's output depend on the
            sticky's own output. Pass False in that case.
    """
    # Inserting a deformer with before=True on a mesh that already has one
    # in its history (e.g. a skinCluster) briefly looks cyclic to Maya
    # while it reconnects plugs, before settling into its final, genuinely
    # non-cyclic state -- see _CycleCheckSuppressed.
    with _CycleCheckSuppressed():
        if deformerType == "softMod":
            deformer, ctrl = cmds.softMod(members,
                                          name=name + '_softMod',
                                          weightedNode=weightNode,
                                          bindState=1,
                                          falloffRadius=falloffRadius,
                                          falloffAroundSelection=0, before=before,
                                          afterReference=False)
            cmds.connectAttr(offsetCtrl + ".worldPosition", deformer + ".falloffCenter")
            cmds.addAttr(ctrl, ln="falloffRadius", at="float", dv=falloffRadius, k=1, min=0.0)
            cmds.connectAttr(ctrl + ".falloffRadius", deformer + ".falloffRadius")

            cmds.addAttr(ctrl, ln="falloffMode", at="enum", en='volume:surface', k=1)
            cmds.connectAttr(ctrl + ".falloffMode", deformer + ".falloffMode")

        elif deformerType == "cluster":
            deformer, ctrl = cmds.cluster(members,
                                          name=name + '_cluster',
                                          weightedNode=weightNode,
                                          envelope=1, before=before, afterReference=False)
            worldPos = cmds.xform(offsetCtrl, q=True, translation=True, ws=True)
            cmds.percent(deformer, members, v=0.0)

            if falloffRadius:
                cmds.percent(deformer, members, dropoffPosition=worldPos, dropoffType='linearSquared',
                             dropoffDistance=falloffRadius, value=1)

        if deformerType in ["softMod", "cluster"]:
            cmds.connectAttr(offsetCtrl + ".worldInverseMatrix", deformer + ".bindPreMatrix")

    return deformer, ctrl


def _reset_transform(obj: str):
    """
    Resets the transform attributes (translation, rotation, and scale) of the given object.

    Args:
        obj (str): The name of the object whose transformations should be reset.
    """
    # Reset translation
    cmds.setAttr(f"{obj}.translateX", 0)
    cmds.setAttr(f"{obj}.translateY", 0)
    cmds.setAttr(f"{obj}.translateZ", 0)

    # Reset rotation
    cmds.setAttr(f"{obj}.rotateX", 0)
    cmds.setAttr(f"{obj}.rotateY", 0)
    cmds.setAttr(f"{obj}.rotateZ", 0)

    # Reset scale
    cmds.setAttr(f"{obj}.scaleX", 1)
    cmds.setAttr(f"{obj}.scaleY", 1)
    cmds.setAttr(f"{obj}.scaleZ", 1)

    # If there's shear, reset it as well (optional)
    if cmds.objExists(f"{obj}.shear"):
        cmds.setAttr(f"{obj}.shearXY", 0)
        cmds.setAttr(f"{obj}.shearXZ", 0)
        cmds.setAttr(f"{obj}.shearYZ", 0)

def _no_double_transform(members, deformer):
    # make sure that transforming the deformed object does not produce double-deformations
    # NOTE: these connections should be established by the cluster/softMod command!
    deformedObjs = []
    for member in members:
        deformedObj = member.split('.')[0]
        if not deformedObj in deformedObjs:
            deformedObjs.append(deformedObj)

    for index, deformedObj in enumerate(deformedObjs):
        srcCon = deformedObj + ".worldMatrix"
        dstCon = deformer + f".geomMatrix[{index}]"
        if not cmds.isConnected(srcCon, dstCon):
            cmds.connectAttr(srcCon, dstCon, f=True)

