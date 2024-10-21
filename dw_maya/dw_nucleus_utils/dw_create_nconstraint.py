import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from maya import cmds, mel
from .dw_nx_mel import *
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_deformers as dwdef

from .dw_create_nucleus import create_nucleus
from .dw_make_collide import make_collide_ncloth
from .dw_setup_for_tear_constraint import setup_for_tear_constraint
from .dw_nhair_utils import get_index_offset_for_hair

def createNConstraint(selection=list, constraintType=str,
                      name='dynamicConstraint1', createSet=None):
    """
    This creates a constraint node that acts on the selected objects and/or components. For each node that
    is selected or that has components selected, nComponent nodes are built that feed into the constraint node.
    This is equivalent to invoking constraint creation off of the menu where the constraint type is the menu item.
    Depending on the constraint type and the selection nRigid nodes may be created for meshes that have not yet been made into
    passive nObjects.

    Given a selected list of nucleus objects and components, create
    nComponent objects and attach these to a constraint, based on
    the desired constraint type

    Args:
        selection (list): your selection as it was maya selection
        constraintType (str): Must be one of: "transform", "pointToSurface",
            "slideOnSurface", "weldBorders", "force", "match", "tearableSurface",
            "weldBorders", "collisionExclusion", "disableCollision", "pointToPoint"
        createSet (int): if true then create a set for selected components instead of setting them
            on the nComponent node
    Returns:
        list: Nodes created
    """

    offsetCache = []
    offsetCacheHsysName = []
    # Nodes created by this routine
    newNodes = []
    # Get the selection( including vertices )
    if selection:
        selected = cmds.ls(selection, flatten=True)
    else:
        selected = cmds.ls(flatten=1, sl=1)
    selected = list(set(selected))
    numSelected = len(selected)

    if numSelected < 1:
        cmds.warning("m_createNConstraint.kNothingToConstrain")
        return []

    tearable = int((constraintType == "tearableSurface"))
    weldBorders = int((constraintType == "weldBorders"))
    force = int((constraintType == "force"))
    match = int((constraintType == "match"))
    collideExclude = int((constraintType == "collisionExclusion"))
    collideDisable = int((constraintType == "disableCollision"))
    hairCurveEdges = int(False)

    # TODO: set this variable throught the UI
    if tearable or weldBorders:
        nParticles = cmds.ls(selected, ni=1, dag=1,
                             type=['nParticle', 'hairSystem', 'pfxHair'], o=1)
        if len(nParticles) > 0:
            cmds.warning("m_createNConstraint.kParticlesNoSupported")
            return []

    selectedObjects = cmds.ls(selected, ni=1, dag=1,
                              type=['mesh', 'nParticle', 'pfxHair',
                                    'hairSystem', 'nurbsCurve'],
                              o=1)
    # Get the selected meshes
    # string $selectedObjects[] = `ls -sl -visible -ni -o -dag -type mesh -type nParticle`;
    selectedObjects = list(set(selectedObjects))
    numObjects = len(selectedObjects)
    if numObjects < 1:
        cmds.warning("m_createNConstraint.kNeedToSelectMesh")
        return []

    if match:
        if numObjects != 2 or numSelected != 2:
            cmds.warning('kNeedToSelectMesh')
            return []

    if numSelected < 2 and not weldBorders and not force and constraintType != "transform" and not collideDisable and \
            selected[0].endswith("]"):
        cmds.warning("m_createNConstraint.kNeedToSelectSurface")
        return []

    parentObject = ""
    if constraintType == "transform":
        locators = cmds.ls(selected, ni=1, dag=1, type='locator', o=1)
        if len(locators) > 0:
            parentObject = locators[0]

    pToSurfObj = ""
    surfConstraint = 0
    if constraintType == "pointToSurface" or constraintType == "slideOnSurface":
        surfConstraint = 1
        if numObjects < 2:
            cmds.warning("m_createNConstraint.kNeedVerticesAndSurface")
            return []

        selObjs = cmds.ls(selected, ni=1, dag=1, type='mesh')
        numSurf = len(selObjs)
        if numSurf == 0:
            cmds.warning("m_createNConstraint.kNoSurfaceToConstrain")
            return []
        if numSurf > 1:
            cmds.warning("m_createNConstraint.kSelectSurfaceToConstrain")
            return []
        pToSurfObj = selObjs[0]

    positionAtMidpoint = 0
    if collideDisable or force or constraintType == "transform":
        positionAtMidpoint = 1
    bb = []
    if positionAtMidpoint:
        bb = cmds.xform(cmds.ls(selected, q=True, bb=True))

    obj = ""
    nucleus = ""
    # find nucleus node
    makePassive = []
    for obj in selectedObjects:
        partObj = find_related_nucleus_object(obj)
        # string $cons[] = `listConnections -sh 1 -type nBase $obj`;
        makePassive.append(True)
        if partObj != "":
            cons = cmds.listConnections(partObj + ".startState")
            if len(cons) < 0:
                fmt = '{} is not connected to a solver. Can\'t constrain.'
                cmds.warning(fmt.format(obj))
                return []

            if nucleus != "":
                if nucleus != cons[0]:
                    cmds.warning("m_createNConstraint.kDifferntSolvers")
                    return []
            else:
                nucleus = cons[0]
            makePassive[-1] = False

        elif constraintType == "transform" and parentObject == "":
            parentObject = obj

        if tearable and makePassive[-1] == True:
            cmds.warning("m_createNConstraint.kNeedCloth")
            return []

    if nucleus == "":
        cmds.warning("m_createNConstraint.kNoClothToConstrain")
        return []

    if not tearable and constraintType != "transform":
        for i in range(0, numObjects):
            if makePassive[i]:
                # TODO : Should replace makePassiveNObj by the main one makeCollideNCloth
                newNodes.append(make_collide_ncloth(selectedObjects[i], nucleus))

    if surfConstraint:
        # make the constrain surface the first component
        for x in range(numObjects):
            if selectedObjects[x] == pToSurfObj:
                if x != 0:
                    selectedObjects[x] = selectedObjects[0]
                    # swap positions
                    selectedObjects[0] = pToSurfObj
                    break

    if tearable:
        if not setup_for_tear_constraint(selectedObjects, selected):
            return []
        numSelected = len(selected)
    # could have changed as result of tear

    if createSet:
        nParticles = cmds.ls(selected, ni=1, dag=1,
                             type=['nParticle', 'hairSystem', 'pfxHair'], o=1)
        if len(nParticles) > 0:
            cmds.warning("m_createNConstraint.kParticleSetsNotSupported")
            createSet = False

    constraint = cmds.createNode('dynamicConstraint', name=name)
    newNodes.append(constraint)

    if positionAtMidpoint:
        cmds.move(constraint, ((bb[0] + bb[3]) * 0.5)
        ((bb[1] + bb[4]) * 0.5)
        ((bb[2] + bb[5]) * 0.5))

    if constraintType == "transform" or collideDisable or force:
        cmds.setAttr(constraint + ".constraintRelation", 0)
        # object to constraint
        cmds.setAttr(constraint + ".componentRelation", 0)
        # all to first
        if force:
            cmds.setAttr(constraint + ".strength", 0.0)
            cmds.setAttr(constraint + ".tangentStrength", 0.0)
            cmds.setAttr(constraint + ".force", 1.0)
            cmds.setAttr(constraint + ".dropoffDistance", 1.0)
            cmds.setAttr(
                constraint + ".strengthDropoff[1].strengthDropoff_Position", 1)
            cmds.setAttr(
                constraint + ".strengthDropoff[1].strengthDropoff_FloatValue",
                0)
            cmds.setAttr(
                constraint + ".strengthDropoff[1].strengthDropoff_Interp", 1)

        if constraintType == "transform" and parentObject != "":
            if cmds.nodeType(parentObject) != "transform":
                tforms = dwu.lsTr(parentObject)
                parentObject = tforms[0]

            cmds.parent(constraint, parentObject, s=1, r=1)
            print("m_createNConstraint.kParentingMsg")

    elif constraintType == "pointToSurface":
        cmds.setAttr(constraint + ".constraintRelation", 1)  # object to object
        cmds.setAttr(constraint + ".componentRelation", 0)  # all to first

    elif match:
        cmds.setAttr(constraint + ".constraintRelation", 1)  # object to object
        cmds.setAttr(constraint + ".componentRelation", 0)  # all to first
        cmds.setAttr(constraint + ".strength", .8)
        cmds.setAttr(constraint + ".tangentStrength", 0.2)
        cmds.setAttr(constraint + ".restLengthScale", 0.0)

    elif constraintType == "slideOnSurface":
        cmds.setAttr(constraint + ".constraintRelation", 1)  # object to object
        cmds.setAttr(constraint + ".componentRelation", 0)  # all to first
        cmds.setAttr(constraint + ".connectionUpdate", 1)  # Per frame
        cmds.setAttr(constraint + ".friction", 0.1)
        cmds.setAttr(constraint + ".strength", 0.02)
        cmds.setAttr(constraint + ".tangentStrength", 0.2)
        cmds.setAttr(constraint + ".localCollide", True)

    elif weldBorders:
        cmds.setAttr(constraint + ".constraintMethod", 0)  # weld
        cmds.setAttr(constraint + ".connectionMethod", 1)  # max distance
        cmds.setAttr(constraint + ".constraintRelation", 1)  # object to object
        cmds.setAttr(constraint + ".componentRelation", 1)  # all to all
        cmds.setAttr(constraint + ".maxDistance", 0.05)
        if numObjects:
            cmds.setAttr(constraint + ".connectWithinComponent", True)

    elif constraintType == "pointToPoint" or collideExclude:
        cmds.setAttr(constraint + ".connectionMethod", 2)  # nearest pair
        cmds.setAttr(constraint + ".constraintRelation", 1)  # object to object
        cmds.setAttr(constraint + ".componentRelation", 1)  # all to all
        if numObjects == 1:
            cmds.setAttr(constraint + ".connectWithinComponent", True)

    elif tearable:
        cmds.setAttr(constraint + ".constraintMethod", 0)  # weld
        cmds.setAttr(constraint + ".connectionMethod", 1)  # max distance
        cmds.setAttr(constraint + ".constraintRelation", 1)  # object to object
        cmds.setAttr(constraint + ".componentRelation", 1)  # all to all
        cmds.setAttr(constraint + ".connectWithinComponent", True)
        cmds.setAttr(constraint + ".glueStrength", 0.1)
        cmds.setAttr(constraint + ".maxDistance", 0.01)
    else:
        cmds.setAttr(constraint + ".constraintRelation", 1)  # object to object
        cmds.setAttr(constraint + ".componentRelation", 1)  # all to all

    if collideDisable or collideExclude:
        cmds.setAttr(constraint + ".strength", 0.0)
        cmds.setAttr(constraint + ".tangentStrength", 0.0)
        cmds.setAttr(constraint + ".collide", False)
        cmds.setAttr(constraint + ".excludeCollisions", True)
        cmds.setAttr(constraint + ".displayConnections", False)

    nComponents = []
    compTypes = []
    componentObjects = []
    baseName = []
    cTypes = []
    cInds = []
    for i in selected:
        name = i[:]
        component = index = None
        if '.' in i:
            name, indexToken = i.split('.')
            component, index = indexToken[:-1].split('[')

        baseName.append(name)
        if component:
            if component == "cv":
                cTypes.append(8)
            elif component == "vtx":
                cTypes.append(2)
            elif component == "e":
                cTypes.append(3)
            elif component == "f":
                cTypes.append(4)
            elif component == "pt":
                cTypes.append(7)
            else:
                cTypes.append(-1)
            cInds.append(index)
        else:
            cTypes.append(-1)
            cInds.append(-1)

    # create the nComponents
    for i in range(numObjects):
        if constraintType == "transform" and makePassive[i]:
            continue
        obj = selectedObjects[i]
        nObject = find_related_nucleus_object(obj)
        appendToExistingComponent = False
        component = ""
        componentIndex = len(nComponents)
        indexOffset = 0
        # offset for hair curves
        componentIndexOffset = 0
        # first unused index on nComponent
        if cmds.nodeType(obj) == "nurbsCurve":
            indexOffset = get_index_offset_for_hair(obj, hairCurveEdges,
                                                offsetCache,
                                                offsetCacheHsysName)
            # TODO change offsets to a double index array on nComponent (hair, index)
            for j in range(componentIndex):
                if componentObjects[j] == nObject:
                    appendToExistingComponent = int(True)
                    # another hair in this hair system
                    componentIndex = j
                    break

        if appendToExistingComponent:
            component = nComponents[componentIndex]
            componentIndexOffset = cmds.getAttr(component + ".componentIndices",
                                                size=1)
        else:
            component = cmds.createNode('nComponent')
            nComponents.append(component)
            componentObjects.append(nObject)
            cmds.connectAttr(nObject + ".nucleusId", component + ".objectId")

        tforms = dwu.lsTr(obj)
        objTform = tforms[0]
        numComponents = componentIndexOffset
        inputMeshComponents = []
        inputMesh = []
        compIndices = []
        compType = 6
        # surface
        doCreateSet = createSet
        if appendToExistingComponent:
            compType = 8
        # hair curves only have selectable cvs currently..edges would be nice in future
        didFirstCurveEdgeCv = 0
        for j in range(numSelected):
            if cTypes[j] == -1:
                continue
            replaceObj = ""
            if baseName[j] == objTform:
                replaceObj = objTform

            elif baseName[j] == obj:
                replaceObj = obj
            else:
                continue

            if numComponents == 0:
                compType = cTypes[j]
            elif compType != cTypes[j]:
                cmds.warning('Mixed Type Warning !')
                break

            sel = selected[j]
            if doCreateSet and numComponents == 0:
                inputMesh = get_input_mesh_for_sets(obj)
                # sets are applied on the input to nCloth nodes not the outputs
                # so that construction history added later is reflected in the set.
                if not inputMesh:
                    doCreateSet = 0
                # still try to create a component constraint without a set

            if doCreateSet:
                inputMeshComponents[numComponents] = sel.replace(replaceObj,
                                                                 inputMesh[0])
                numComponents += 1
            else:
                compInd = int(cInds[j])
                if compType == 8 and hairCurveEdges:
                    compInd -= 1
                    if compInd < 0:
                        compInd = 0

                    if compInd == 0:
                        if didFirstCurveEdgeCv:
                            compInd = -1
                        # allow the first cv to still be converted to edge but avoid duplicate indices

                        didFirstCurveEdgeCv = 1
                if compInd >= 0:
                    compInd += indexOffset
                    cmds.setAttr("{}.componentIndices[{}]".format(component,
                                                                  numComponents),
                                 compInd)
                    compIndices.append(compInd)
                    numComponents += 1

        if not appendToExistingComponent:
            doBend = 0
            if tearable:
                if "nCloth" == cmds.nodeType(nObject):
                    bend = cmds.getAttr(nObject + ".bendResistance")
                    if bend > 0.2:
                        doBend = 1
                        cmds.setAttr(constraint + ".bendStrength", bend)
                        cmds.setAttr(constraint + ".bend", True)
                        cmds.setAttr(constraint + ".bendBreakAngle", 5.0)

            if compType == 8:
                if hairCurveEdges:
                    cmds.setAttr(component + ".componentType",
                                 3)  # treat hair cvs as edges
                else:
                    cmds.setAttr(component + ".componentType",
                                 2)  # treat hair cvs as vertices

            elif compType == 7:
                cmds.setAttr(component + ".componentType",
                             2)  # treat particle points as vertices
            else:
                cmds.setAttr(component + ".componentType", compType)

            if compType == 3 and numObjects == 1 and constraintType == "pointToPoint":
                cmds.setAttr(constraint + ".connectionMethod", 0)
            # For edge components on single objects we set to componentOrder
            # which essentially treats each edge as being a link, rather than
            # forming links between edges.
            # component order

            compTypes.append(compType)
            if numComponents == 0:
                if weldBorders:
                    cmds.setAttr(component + ".elements", 1)
                    # BORDERS
                    cmds.setAttr(component + ".componentType", 3)
                    # edge
                    compTypes[i] = 3
                else:
                    cmds.setAttr(component + ".elements", 2)  # ALL
                    if doBend:
                        cmds.setAttr(component + ".componentType", 3)
                        # edge
                        compTypes[i] = 3
                    elif tearable or force or match or constraintType == "pointToPoint":
                        cmds.setAttr(component + ".componentType", 2)
                        # point
                        compTypes[i] = 2

            elif is_all_components(obj, numComponents, compType):
                cmds.setAttr(component + ".elements", 2)
            # ALL

            # Note : this part has never been coded by autodesk and return always False
            # elif _isAllBorderComponents(obj, compIndices, compType):
            #     cmds.setAttr((component + ".elements"),
            #                  1)
            # ALL BORDERS
            else:
                cmds.setAttr(component + ".elements", 0)
                # indice list
                if doCreateSet:
                    make_set_for_component(component, inputMesh[1],
                                        inputMeshComponents)

    if constraintType == "pointToSurface" or constraintType == "slideOnSurface":
        ind = 0
        # connect components to constraint
        # put the surface at the head of the list... there should only be one
        for i in range(0, len(nComponents)):
            if compTypes[i] == 6:
                cmds.connectAttr(nComponents[i] + ".outComponent",
                                 '{}.componentIds[{}]'.format(constraint, ind))
                # is a surface
                ind += 1
        for i in range(0, len(nComponents)):
            if compTypes[i] != 6:
                cmds.connectAttr(nComponents[i] + ".outComponent",
                                 '{}.componentIds[{}]'.format(constraint, ind))
                # is NOT a surface
                ind += 1
    else:
        for i in range(len(nComponents)):
            if constraintType == "transform" and makePassive[i]:
                continue
            cmds.connectAttr(nComponents[i] + ".outComponent",
                             '{}.componentIds[{}]'.format(constraint, i))

    if len(nComponents) == 1 and (
            constraintType == "pointToPoint" or collideExclude):
        cmds.setAttr(constraint + ".connectWithinComponent", True)

    nucleusConstraintIndex = get_first_free_constraint_index(nucleus)
    # The following line should be removed once constraints are updating
    # for start frame inside the solver
    cmds.connectAttr("time1.outTime", constraint + ".currentTime")
    cmds.connectAttr(constraint + ".evalStart[0]",
                     "{}.inputStart[{}]".format(nucleus,
                                                nucleusConstraintIndex), f=1)
    cmds.connectAttr(constraint + ".evalCurrent[0]",
                     "{}.inputCurrent[{}]".format(nucleus,
                                                  nucleusConstraintIndex), f=1)
    # force update of nucleus for new constraint if start frame
    cmds.getAttr(nucleus + ".forceDynamics")
    # cmds.select(constraint, r = 1)
    if tearable:
        print("m_createNConstraint.kAdjustGlueStrength")

    return newNodes


def extractFaces(selectedFaces, toPartsMesh):
    cmds.polyChipOff(selectedFaces, ch=1, kft=1, dup=0, off=0)
    cmds.polySeparate(selectedFaces[0].split('.')[0], rs=1, ch=1)
    myTransform = list(set([cmds.listRelatives(i, p=1)[0] for i in
                            cmds.ls(toPartsMesh, dag=True, type="mesh")]))
    for i in myTransform:
        cmds.delete(i, ch=1)


def uncombineMesh(selectedMesh, keepHistory=True):
    # SeparatePolygon;
    # performPolyShellSeparate;
    meshes = cmds.polySeparate(selectedMesh, ch=1)
    if not keepHistory:
        for i in meshes:
            cmds.delete(i, ch=1)
    return meshes


def oldExampleSofaWorkflow():
    mySel = cmds.ls(sl=True)[0]

    # 1- Duplicate and create the recipe mesh : mesh_recipe_cfx
    outputClothMesh = cmds.duplicate(mySel, n=mySel + "_cfxOutput",
                                     rc=1)  # will be wrapped to the combined
    cmds.blendShape(outputClothMesh, mySel)

    grpCfxName = cmds.group(em=1, n=mySel + "_cfxRig")
    cmds.parent(outputClothMesh, grpCfxName)

    # 2- Duplicate again and blendshape to recipe - mesh_parts_cfx
    grpCombinedName = cmds.group(em=1, n=mySel + "_combinedParts")
    toPartsMesh = cmds.duplicate(mySel, n=mySel + "_toCut", rc=1)
    cmds.parent(toPartsMesh, grpCombinedName)

    # --------  Sofa_parts_pied04_noneCfx
    # --------  Sofa_parts_accoudoir01_activeCfx
    # --------  Sofa_parts_body01_rigidCfx

    # 4- Duplicate this group and blendshape mesh_parts_cfx to transfer ones
    toTransferMesh = cmds.duplicate(toPartsMesh[0],
                                    n=toPartsMesh[0].replace("_toCut",
                                                             "_toTransfer"),
                                    rc=1)
    myTransferNodes = [cmds.listRelatives(i, p=1)[0] for i in
                       cmds.ls(toTransferMesh[1:], dag=True, type='mesh')]
    for i in myTransferNodes:
        cmds.rename(i, i + "_transfer")

    parts_cfx = cmds.ls(sl=1, dag=1, type='transform')[1:]
    for i in parts_cfx:
        cmds.rename(i, i + "_parts")
    parts_transfer = cmds.ls(sl=1, dag=1, type='transform')[1:]

    for i in range(len(parts_cfx)):
        bs_Name = cmds.blendShape(parts_cfx[i], parts_transfer[i], w=(0, 1))

    # 5- combine transfer mesh
    myMeshResult = cmds.polyUnite(parts_transfer, ch=1, mergeUVSets=1,
                                  name="sofa_transfer")

    # 6-wrap the sofa_parts_recipe to the transfer mesh
    dwdef.createWrap(myMeshResult[0], outputClothMesh[0])

    # 7- display layer to make them unselectable
    cmds.parent(grpCombinedName, grpCfxName)
    cmds.setAttr(grpCombinedName + ".visibility", 0)
    cmds.setAttr(outputClothMesh[0] + ".visibility", 0)
    cmds.createDisplayLayer(n="sofaRigHiddenElements", e=1)
    cmds.editDisplayLayerMembers('sofaRigHiddenElements', grpCombinedName, nr=1)

    # 8 create one group per cloth object
    mySimGroup = cmds.group(n="Sofa_Sim_GRP", em=1, p=grpCfxName)
    nucleusNode = create_nucleus("Sofa_nucleus")
    cmds.parent(nucleusNode, mySimGroup)
    for i in parts_cfx:
        if i.endswith("_activeCfx"):
            myNode = cmds.duplicate(i, n=i.replace("_activeCfx", "_cloth"))
            cmds.parent(myNode, mySimGroup)




def createHiRez(meshA, meshB):
    # we can specifiy a hi rez or multiple hi rez by pattern
    # we can define them manually
    # we can find them by going from the input "wrapped geo"
    ##     maybe the high
    # Check if same number of points, if not blendshape
    # Check if same
    pass


def getVertexMap(vertex, getMapIndex=False):
    vtx_map = cmds.polyListComponentConversion(vertex, tuv=True)
    if getMapIndex:
        return vtx_map
    uv_value = cmds.polyEditUV(vtx_map, query=True)
    if len(uv_value) > 2:
        return uv_value[:2]
    return uv_value


def create_pointOnPolyConstraint(input_vertex, tr, name=None, **kwargs):
    replace = kwargs.get('replace') or False

    # if other type of component has been input, change to vertices
    toVertices = cmds.polyListComponentConversion(input_vertex, tv=True)
    vertices = cmds.ls(toVertices, fl=True)

    if replace:
        o = cmds.ls(input_vertex, o=True)
        con = cmds.listConnections(o, d=True, type='pointOnPolyConstraint')
        pos = cmds.pointPosition(input_vertex)
        if con:
            for x, a in enumerate('XYZ'):
                addL = cmds.createNode('addDoubleLinear',
                                       name='offset{}Localisation'.format(a))
                cmds.setAttr('{}.input1'.format(addL), -pos[x])
                cmds.connectAttr(con[0] + '.constraintTranslate{}'.format(a),
                                 '{}.input2'.format(addL))
                cmds.connectAttr('{}.output'.format(addL),
                                 tr + '.translate{}'.format(a))
            ptC = con[0]
    else:
        # maya python command doesn't set the uv values for whatever reason
        # the attr name has to be guessed i suppose with the input object
        # and the len
        ptC = cmds.pointOnPolyConstraint(vertices,
                                         tr,
                                         name='popc_{}'.format(name))[0]
        sel_names = [i.split('.')[0] for i in vertices]
        attrUV = ['{}.{}{}{}'.format(ptC, m, uv, x) for uv in 'UV' for x, m in
                  enumerate(sel_names)]
        valueUV = chain(*[getVertexMap(i) for i in vertices])
        for attr, value in zip(attrUV, valueUV):
            cmds.setAttr(attr, value)

        # cleaning the default connections going into the locator
        con = [i for i in cmds.listConnections(ptC, p=True)
               if re.search('^(rotate|translate)[X-Z]$', i.split('.')[-1])]
        dest = [i for i in cmds.listConnections(con, p=True)]
        plugs = zip(dest, con)
        for p in plugs:
            cmds.disconnectAttr(*p)
            cmds.setAttr(p[1], 0)

    return ptC
