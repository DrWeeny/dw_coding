import sys, os
# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

from maya import cmds, mel
import re

from dw_maya.dw_decorators import acceptString, timeIt, singleUndoChunk, load_plugin
from dw_maya.dw_create import pointOnPolyConstraint


# Helper functions
def filterSelection(inputFaces=[]):
    if not inputFaces:
        sel = cmds.ls(orderedSelection=True, fl=True)
    else:
        sel = cmds.ls(inputFaces, fl=True)
    meshFaces = cmds.filterExpand(sel, expand=True, selectionMask=34) or []
    meshTransforms = cmds.filterExpand(expand=True, selectionMask=12) or []
    nurbsSurfaceTransforms = cmds.filterExpand(expand=True, selectionMask=10) or []
    nurbsCurvesTransforms = cmds.filterExpand(expand=True, selectionMask=9) or []
    return meshFaces, meshTransforms, nurbsSurfaceTransforms, nurbsCurvesTransforms


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


def create_control_group(base_name, radius=1.0, create_control=False):
    """
    Creates a control and its parent zero group, or just the zero group if create_control is False.
    """
    ctrl = ''
    if create_control:
        ctrl = cmds.circle(n=base_name + '_ctrl', ch=0, radius=radius * 0.5 + 0.1)[0]
        cmds.rotate(-90, 0, 0, ctrl + ".cv[0:7]", os=True, r=True)
        cmds.setAttr(ctrl + '.v', keyable=False, channelBox=False)
        ctrl_shape = cmds.listRelatives(ctrl, shapes=True)[0]
        cmds.setAttr((ctrl_shape + ".overrideEnabled"), 1)
        cmds.setAttr((ctrl_shape + ".overrideColor"), 27)
        ctrl_zro = cmds.group(ctrl, n=base_name + '_zro')
    else:
        ctrl_zro = cmds.group(empty=True, n=base_name + '_zro')

    return ctrl, ctrl_zro

def create_follicle_constraint(ctrl_zro, mesh_shape, uv, base_name):
    """
    Creates a follicle and sets it up to drive the control group.
    """
    from dw_maya.dw_nucleus_utils import create_follicles
    follicle = create_follicles(mesh_shape, uv, name=base_name + '_follicle')
    follicle_shape = cmds.listRelatives(follicle)[0]
    cmds.setAttr(follicle_shape + '.v', 0)

    # Parent the control zero group to the follicle
    cmds.parent(ctrl_zro, follicle, relative=1)
    normal_cnt = cmds.normalConstraint(mesh_shape, ctrl_zro, weight=1, aimVector=(0, 1, 0), upVector=(0, 0, 1),
                                       worldUpVector=(0, 0, 1), worldUpType='scene')
    cmds.delete(normal_cnt)

    return follicle

@singleUndoChunk
def createSticky(componentSel=None, parent=None, _type='softMod'):
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
    out = createStickyDeformers(_type, parent=grp, inputFaces=componentSel)

    # Set the falloff radius to 0.5 (adjust as needed)
    print(out)
    cmds.setAttr("{}.falloffRadius".format(out[0]), 0.5)

    return out


def createStickyDeformers(deformerType, name=None, parent=None, inputFaces=[], ssr=False):
    # Filter selection
    meshFaces, meshTransforms, nurbsSurfaceTransforms, nurbsCurvesTransforms = filterSelection(inputFaces)

    # Multi-face selection handling (Currently commented out logic for UI multi-mode)
    multiFaceMode = False
    driverFaces = meshFaces[-1] if meshFaces else None  # Default to last face selected

    # Check user preferences for selection order tracking
    if not multiFaceMode:
        cmds.selectPref(trackSelectionOrder=True)

    # Find deformer members (geometry to which deformer will be applied)
    obj = cmds.ls(driverFaces, o=True)
    meshTransforms = cmds.listRelatives(obj, p=True)
    deformerMembers = list(set(meshTransforms + nurbsSurfaceTransforms + nurbsCurvesTransforms))

    # Set name prefix if not provided
    if not name:
        name = ''

    # Get the falloff radius for soft selection
    falloffRadius = getFalloffRadius(ssr)

    # Define parent group for controls if none exists
    stickyControlsParent = parent if parent else 'sticky_grp'
    if not cmds.objExists(stickyControlsParent):
        stickyControlsParent = cmds.group(empty=True, name=stickyControlsParent)

    # Create sticky controls
    stickyControls = createStickyControls(
        driverMeshFaces=driverFaces,
        createControlParentGroupsOnly=False,
        stickyControlsParent=stickyControlsParent,
        radius=falloffRadius,
        namePrefix=name
    )

    # Create deformers
    deformer_output = createDeformers(
        deformerType=deformerType,
        name='',
        parents=stickyControls,
        members=deformerMembers,
        meshFaces=meshFaces,
        multiFaceMode=multiFaceMode,
        falloffRadius=falloffRadius,
        createOffsetCtrls=False
    )

    return stickyControls, deformer_output


def createDeformers(deformerType: str, name: str = '',
                    parents: list = [], members: list = [],
                    meshFaces: list = [],
                    multiFaceMode: bool = False, falloffRadius: float = None,
                    createOffsetCtrls: bool = False) -> list:
    """
    Create deformers (cluster/softMod/locator) and set up connections so they travel with the parent(s), if any.

    Args:
        deformerType (str): Type of deformer to create ("cluster", "softMod", "locator").
        name (str): Optional name for the deformers.
        parents (list): List of parent objects to define the center of deformation.
        members (list): Objects/components to be influenced by the deformer.
        meshFaces (list): Specific faces on a mesh that should be influenced by the deformer.
        multiFaceMode (bool): Whether to allow deformation on multiple faces.
        falloffRadius (float): Radius of influence for deformation.
        createOffsetCtrls (bool): If True, create offset controls for deformers.

    Returns:
        list: A list of offset controls created for the deformers.
    """

    defaultFalloffRadius = falloffRadius if falloffRadius else 1.0

    if not members:
        print("No geometry provided. Nothing created.")
        return []

    deformers = []
    offsetCtrls = []

    baseName = getUniqueBaseName(parents, name)

    if not createOffsetCtrls:
        uniqueOffsetCtrlName = getUniqueBaseName(parents, dstSuffixes=['_offset_ctrl'])
        parent = cmds.rename(parents, uniqueOffsetCtrlName + '_offset_ctrl')
    else:
        parent = parents

    # Generate unique deformer name
    name = getUniqueBaseName(baseName, dstSuffixes=['_' + deformerType, '_ctrl'])

    # Create Control
    ctrl = _create_control(deformerType, name, defaultFalloffRadius)

    # Offset Control Creation
    offsetCtrl = _create_offset_control(name, falloffRadius, createOffsetCtrls, parent)

    # Add locator shape to access worldPosition
    _add_locator_shape_to_offset_ctrl(offsetCtrl)

    # Create Deformer
    deformer = _create_deformer(ctrl, offsetCtrl, members, meshFaces, falloffRadius, deformerType, multiFaceMode)

    # Finalize Control Setup
    cmds.parent(ctrl, offsetCtrl)
    _reset_transform(ctrl)

    if createOffsetCtrls:
        cmds.parent(offsetCtrl, parent)

    offsetCtrls.append(offsetCtrl)

    return offsetCtrls


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


def createStickyControls(driverMeshFaces=[], createControlParentGroupsOnly=False, stickyControlsParent='', radius=1.0,
                         namePrefix='', constrainViaFollicles=True):
    """
    Creates sticky controls (or empty parent groups) constrained to a mesh surface, using follicles or pointOnPolyConstraint.
    """
    bGenerateName = not namePrefix
    sticky_controls = []
    sticky_control_zeroes = []
    follicles = []

    mesh_faces = cmds.filterExpand(driverMeshFaces, expand=True, selectionMask=34)
    d_face_vs_face_position = getFaceCenterPositions(mesh_faces, returnMPoints=True)

    for driver in mesh_faces:
        geo_name, face_num = driver.split(".")
        component = face_num.replace("[", "_").replace("]", "").replace(":", "_")

        base_name = generate_control_name(geo_name, component, namePrefix if not bGenerateName else '')

        # Create control or parent group
        sticky_controls, ctrl_zro = create_control_group(base_name, radius, not createControlParentGroupsOnly)
        sticky_control_zeroes.append(ctrl_zro)

        if component:
            cmds.addAttr(ctrl_zro, ln="following", dt="string")
            cmds.setAttr(ctrl_zro + ".following", driver, type="string")

        mesh_shape = geo_name if cmds.nodeType(geo_name) == 'mesh' else \
        cmds.listRelatives(geo_name, noIntermediate=1, shapes=1, fullPath=1)[0]
        in_mesh_con = cmds.connectionInfo(mesh_shape + '.inMesh', sourceFromDestination=True)

        temp_cluster = None
        if not in_mesh_con:
            temp_cluster = cmds.cluster(mesh_shape, name='temp_cluster')
            in_mesh_con = cmds.connectionInfo(mesh_shape + '.inMesh', sourceFromDestination=True)

        # Get UVs and setup follicle or pointOnPoly constraint
        sh_only = mesh_shape.rsplit("|")[-1]  # key is only the shape
        face_m_point = d_face_vs_face_position[f'{sh_only}.{face_num}']
        # delay import to avoid circular call
        from dw_maya.dw_maya_utils import closest_uv_on_mesh
        uv = closest_uv_on_mesh(mesh_shape, position=face_m_point)

        if constrainViaFollicles:
            follicle = create_follicle_constraint(ctrl_zro, mesh_shape, uv, base_name)
            follicles.append(follicle)
        else:
            pop_cnt = pointOnPolyConstraint(driver, ctrl_zro)

        if temp_cluster:
            cmds.delete(temp_cluster)

    if stickyControlsParent:
        if not cmds.objExists(stickyControlsParent):
            stickyControlsParent = cmds.group(empty=True, name=stickyControlsParent)

        cmds.parent(follicles if constrainViaFollicles else sticky_control_zeroes, stickyControlsParent)

    return sticky_control_zeroes if createControlParentGroupsOnly else sticky_controls




def updateLocators(locators):
    """
    Main function to update a list of locators by applying constraints, baking transformations, and restoring visibility.
    """
    if locators:
        for i, loc in enumerate(locators):
            if cmds.objExists(loc + ".following"):
                # get rid of any keys on it
                for attr in cmds.listAttr(loc):
                    cmds.cutKey(loc, cl=1, at=attr)
                constTo = cmds.getAttr(loc + ".following")
                pointOnPolyConstraint(constTo, loc) #doCreatePointOnPolyConstraintArgList 1 { "0","0","0","1","","1" }
            else:
                locators.remove(loc)

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
            cmds.makeIdentity(ctrl, s=True, apply=True)

    elif deformerType == "softMod":
        ctrl = cmds.group(em=True, name=name + "_ctrl")
        circleX = cmds.circle(name=name + "X", nr=(1, 0, 0), r=falloffRadius, ch=False)[0]
        circleY = cmds.circle(name=name + "Y", nr=(0, 1, 0), r=falloffRadius, ch=False)[0]
        circleZ = cmds.circle(name=name + "Z", nr=(0, 0, 1), r=falloffRadius, ch=False)[0]
        cmds.parent(circleX + "Shape", circleY + "Shape", circleZ + "Shape", ctrl, r=True, s=True)
        cmds.delete(circleX, circleY, circleZ)

    elif deformerType == "locator":
        ctrl = cmds.curve(name=name + "_ctrl", d=1, p=[(0, 1, 0), (0, -1, 0), (0, 0, 0), (0, 0, -1),
                                                       (0, 0, 1), (0, 0, 0), (1, 0, 0), (-1, 0, 0)])
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
        offsetCtrl = cmds.circle(n=name + '_offset_ctrl', ch=False, radius=falloffRadius * 0.5)[0]
        cmds.rotate(-90, 0, 0, offsetCtrl + ".cv[0:7]", os=True, r=True)
        cmds.setAttr(offsetCtrl + '.v', keyable=False)
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
    cmds.rename(offsetCtrlLocatorShape, offsetCtrl + "Shape")


def _create_deformer(ctrl: str, offsetCtrl: str, members: list, meshFaces: list,
                      falloffRadius: float, deformerType: str, multiFaceMode: bool):
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
    """
    if deformerType == "softMod":
        deformer, _ = cmds.softMod(members, name=ctrl + '_softMod', weightedNode=[ctrl, ctrl],
                                   bindState=1, falloffRadius=falloffRadius)
        cmds.connectAttr(offsetCtrl + ".worldPosition", deformer + ".falloffCenter")
        cmds.addAttr(ctrl, ln="falloffRadius", at="float", dv=falloffRadius, k=True)
        cmds.connectAttr(ctrl + ".falloffRadius", deformer + ".falloffRadius")

    elif deformerType == "cluster":
        deformer, _ = cmds.cluster(members, name=ctrl + '_cluster', weightedNode=[ctrl, ctrl], envelope=1)
        worldPos = cmds.xform(offsetCtrl, q=True, translation=True, ws=True)
        cmds.percent(deformer, members, v=0.0)

        if falloffRadius:
            cmds.percent(deformer, members, dropoffPosition=worldPos, dropoffType='linearSquared',
                         dropoffDistance=falloffRadius, value=1)
        if multiFaceMode and meshFaces:
            setClusterWeightsFromSoftSelection(deformer, members[0], meshFaces[0], falloffRadius)

    if deformerType != "locator":
        cmds.connectAttr(offsetCtrl + ".worldInverseMatrix", deformer + ".bindPreMatrix")

    return deformer


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

