import sys, os
# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)


from maya import cmds, mel
from dw_maya.dw_decorators import acceptString, timeIt, singleUndoChunk, load_plugin
from dw_maya.dw_maya_utils import Flags, lsTr, get_type_io, chunks
from dw_maya.dw_create import pointOnPolyConstraint

import re
import maya.OpenMaya as om
import maya.OpenMayaAnim as oma


@acceptString('drivenMesh')
def eST_meshDeformer(drivenMesh=list, driverMesh=str, **kwargs):

    '''
    Args :
        cage               = string     - the driver mesh node name.
                                          ( default: the 1st selection )
        objs               = [string]   - a list of geometry node names to be deformed.
                                          ( default: after 2nd selections )


    Kwargs:

              n|name           = string     - a node name expression of new eSTmeshDeformer
                                              node.
                                              ( default: [ '~', '~[meshDeformer]', '(@)~' ] )
              s|smooth         = int        - smooth level of the driver mesh output.
                                              ( default: 0 )
             kb|keepBorder     = bool       - do not smooth border edges.
                                              this option effects with smooth option.
                                              ( default: False )
              l|local          = bool       - use local space to setting up.
                                              ( default: False )
             ec|echoResult     = bool       - print binding information after creation.
                                              ( default: False )
              m|mode           = string     - valid values are 'fixInput', 'updatePoints',
                                              'updateBinding' or 'rebind'.
                                              ( default: 'fixInput' )
             cm|centeringMethod = string    - valid values are 'medianPoint', 'average' or
                                              'centerOfBindingBox'.
                                              ( default: 'medianPoint' )
             ds|depthSource    = string     - valid values are 'face' or 'vertex'.
                                              ( default: 'face' )
             dm|driverMatrix   = mixed      - the driver matrix. when EMatrix was specified to
                                              this option, it will be set in static. if string
                                              based value was specified, it will be connected
                                              as plug name. this option is ignored when local
                                              option was set to False.
                                              ( default: do nothing )
            bdm|bindDriverMesh = string     - a substitute driver mesh to getting original
                                              point positions when rebinding.
                                              ( default: None )
             bg|bindGeometry   = [(int,string)]  - a list of tuples that contains index of objs
                                                   and a substitute driven geometry to getting
                                                   original point positions when rebinding.
                                                   ( default: [] )
            csg|connectSubstituteGeometries - create connections with specified bindDriverMesh
                                              and bindGeometries.
                                              ( default: False )
            ump|useMP          = bool       - if True, use multithread when update binding or
                                              rebinding.
                                              ( default: False )
            pfp|priorFixedPints = bool      - prior fixed points when (re)binding time.
                                              ( default: False )
            idd|ignoreDriverDisconnection = bool  - if True then suppress rebinding when the
                                                    driver mesh has been disconnected.
                                                    when using a referenced mesh as a driver,
                                                    set this option to True.
                                                    ( default: False )
            before             = bool       -
                                              ( default: False )
            after              = bool       -
                                              ( default: False )
            split              = bool       -
                                              ( default: False )
            parallel           = bool       -
                                              ( default: False )
            exclusive          = bool       -
                                              ( default: False )
            partition          = string     -
                                              ( default: '' )

    Return Value:
            string   - a new eSTmeshDeformer node name.

    '''

    try:
        cmds.loadPlugin("eSTcmds.so")
    except:
        return

    from eST.tools.setup.setupMeshDeformer import setupMeshDeformer
    o = setupMeshDeformer(cage = driverMesh, objs = drivenMesh, echoResult = True, **kwargs)
    return o

    # help(eST.tools.setup.setupMeshDeformer)


def createWrap(*args, **kwargs):
    """
    Create a wrap deformer that allows one object to deform based on the shape of another.

    Args:
        objWhoDeforms (str): The object that deforms (the surface).
        objInfluence (str): The object that influences the deformation.

    Kwargs:
        weightThreshold (float): The threshold below which the weights are discarded (default: 0.0).
        maxDistance (float): The maximum distance for the deformation (default: 1.0).
        exclusiveBind (bool): Whether to bind exclusively (default: False).
        autoWeightThreshold (bool): Whether to automatically determine the weight threshold (default: True).
        falloffMode (int): Determines how the falloff is calculated (default: 0).
        name (str): Name of the wrap deformer node.

    Returns:
        list: A list containing the wrap node and the duplicated base shape.
    """

    if len(args) < 2:
        cmds.error("Both surface and influence objects are required.")

    influence = args[1]
    surface = args[0]

    shapes = cmds.listRelatives(influence, shapes=True)
    influenceShape = shapes[0]

    shapes = cmds.listRelatives(surface, shapes=True)
    surfaceShape = shapes[0]

    # create wrap deformer
    weightThreshold = kwargs.get('weightThreshold', 0.0)
    maxDistance = kwargs.get('maxDistance', 1.0)
    exclusiveBind = kwargs.get('exclusiveBind', False)
    autoWeightThreshold = kwargs.get('autoWeightThreshold', True)
    falloffMode = kwargs.get('falloffMode', 0)
    name = kwargs.get('name', None)

    if not name:
        wrapData = cmds.deformer(surface, type='wrap')
    else:
        wrapData = cmds.deformer(surface, type='wrap', name=name)
    wrapNode = wrapData[0]

    # Set wrap deformer attributes
    cmds.setAttr(f'{wrapNode}.weightThreshold', weightThreshold)
    cmds.setAttr(f'{wrapNode}.maxDistance', maxDistance)
    cmds.setAttr(f'{wrapNode}.exclusiveBind', exclusiveBind)
    cmds.setAttr(f'{wrapNode}.autoWeightThreshold', autoWeightThreshold)
    cmds.setAttr(f'{wrapNode}.falloffMode', falloffMode)

    # Connect surface to wrap deformer
    cmds.connectAttr(f'{surface}.worldMatrix[0]', f'{wrapNode}.geomMatrix')

    # Duplicate the influence object as the base object
    base = cmds.duplicate(influence, name=f'{influence}Base')[0]
    baseShape = cmds.listRelatives(base, shapes=True, fullPath=True)[0]
    cmds.hide(base)

    # create dropoff attr if it doesn't exist
    if not cmds.attributeQuery('dropoff', n=influence, exists=True):
        cmds.addAttr(influence, sn='dr', ln='dropoff', dv=4.0, min=0.0, max=20.0)
        cmds.setAttr(influence + '.dr', k=True)

    # if type mesh
    if cmds.nodeType(influenceShape) == 'mesh':
        # create smoothness attr if it doesn't exist
        if not cmds.attributeQuery('smoothness', n=influence, exists=True):
            cmds.addAttr(influence, sn='smt', ln='smoothness', dv=0.0, min=0.0)
            cmds.setAttr(influence + '.smt', k=True)

        # create the inflType attr if it doesn't exist
        if not cmds.attributeQuery('inflType', n=influence, exists=True):
            cmds.addAttr(influence, at='short', sn='ift', ln='inflType', dv=2, min=1, max=2)

        cmds.connectAttr(f'{influenceShape}.worldMesh[0]', f'{wrapNode}.driverPoints[0]')
        cmds.connectAttr(f'{baseShape}.worldMesh[0]', f'{wrapNode}.basePoints[0]')
        cmds.connectAttr(f'{influence}.inflType', f'{wrapNode}.inflType[0]')
        cmds.connectAttr(f'{influence}.smoothness', f'{wrapNode}.smoothness[0]')

    # if type nurbsCurve or nurbsSurface
    if cmds.nodeType(influenceShape) == 'nurbsCurve' or cmds.nodeType(influenceShape) == 'nurbsSurface':
        # create the wrapSamples attr if it doesn't exist
        if not cmds.attributeQuery('wrapSamples', n=influence, exists=True):
            cmds.addAttr(influence, at='short', sn='wsm', ln='wrapSamples', dv=10, min=1)
            cmds.setAttr(influence + '.wsm', k=True)

        cmds.connectAttr(f'{influenceShape}.worldSpace[0]', f'{wrapNode}.driverPoints[0]')
        cmds.connectAttr(f'{baseShape}.worldSpace[0]', f'{wrapNode}.basePoints[0]')
        cmds.connectAttr(f'{influence}.wrapSamples', f'{wrapNode}.nurbsSamples[0]')

    # Connect dropoff attribute
    cmds.connectAttr(f'{influence}.dropoff', f'{wrapNode}.dropoff[0]')

    return [wrapNode, base]


@timeIt
def cvWeights2Geo(crv):
    """
    Distribute weights along the control vertices (CVs) of a NURBS curve and apply them to a cvWrap deformer.

    Args:
        crv (str): The name of the curve to process.

    Raises:
        RuntimeError: If no cvWrap node is found for the curve.

    """
    curve_sh = lsTr(crv, ni=True, type='nurbsCurve', p=False)
    cvs_len = [len(cmds.ls(c + '.cv[:]', fl=True)) for c in curve_sh]
    for c, length in zip(curve_sh, cvs_len):
        # Calculate weights based on normalized position along the curve
        weights = [float(x) / (length - 1) for x in range(length)]

        # Find cvWrap nodes and related connections
        cwOut = cmds.listConnections(c, t='cvWrap')
        if not cwOut:
            raise RuntimeError(f"No cvWrap node found for curve {c}")
        cwOut=cwOut[0]

        attr = cmds.listConnections(c + '.create', p=True)[0]
        if attr.startswith(cwOut):
            nb = re.findall(r"\d+", attr)[-1]
            weight_attr = f'weightList[{nb}].weights'

            # Set weights on the input node and reverse weights on the output node
            cmds.setAttr(f'{cwOut}.{weight_attr}[0:{length - 1}]', *weights, size=length)
            cmds.setAttr(f'{cwOut}.{weight_attr}[0:{length - 1}]', *weights[::-1], size=length)

@acceptString('mesh')
def cvWrap2Geo(item, mesh):
    """
    Apply cvWrap deformer to chunks of curves for a given mesh. The function supports the 251 connection limit
    of the cvWrap node by chunking the input curves.

    Args:
        item (list): List of curves or items to wrap.
        mesh (str or list): The target mesh or list of two meshes (outer, inner).

    Returns:
        list: Names of created cvWrap nodes.
    """
    # Check if the mesh argument is valid
    if not isinstance(mesh, list) and not isinstance(mesh, str):
        raise ValueError("Invalid mesh input. Must be a list or a string.")

    # Chunk the curves into manageable groups of 251 (cvWrap limitation)
    crv_chunks = chunks(item, 251)

    # Handle mesh list (assuming only the first mesh is used, clarify based on requirements)
    outer = inner = None
    if isinstance(mesh, list):
        if len(mesh) == 2:
            outer, inner = mesh
        else:
            raise ValueError("Invalid mesh list. Expecting a list of two meshes (outer, inner).")
    else:
        outer = mesh

    output = []

    # Iterate over chunks and apply cvWrap
    for mesh_item in [outer]:  # Only outer is used
        for x, curve_chunk in enumerate(crv_chunks):
            # Apply cvWrap deformer
            cv_wrap = cmds.cvWrap(curve_chunk, mesh_item, radius=.1)

            # Get the connected mesh (assuming mesh is second in the list)
            connected_mesh = cmds.listConnections(cv_wrap, t='mesh')[1]
            mesh_name = connected_mesh.split('|')[-1].split(':')[-1]

            # Rename the cvWrap node for clarity
            new_name = cmds.rename(cv_wrap, f'{mesh_name}_{cv_wrap}_{x}')
            output.append(new_name)

    return output


def transferWrapConns(wrapPlugs=[], newNode=''):
    """
    Transfer connections from the current wrap deformer to the new node.
    Derived from MEL command but I've let chatGPT refactor the function
    Args:
        wrapPlugs (list): A list of wrap plugs (connections) to be transferred.
        newNode (str): The node to which connections will be transferred.

    """
    for wrapPlug in wrapPlugs:
        # Get the node and attribute connected to the plug
        wrapNode = cmds.plugNode(wrapPlug)
        wrapAttr = cmds.plugAttr(wrapPlug)

        # Process only driverPoints connections
        if wrapAttr.startswith("driverPoints"):
            # Find connections to meshes
            meshConns = cmds.listConnections(wrapPlug, s=True, p=True, sh=True, type="mesh")

            if meshConns:
                # Transfer the connection to the new node
                meshAttr = cmds.plugAttr(meshConns[0])
                cmds.disconnectAttr(meshConns[0], wrapPlug)
                cmds.connectAttr(f'{newNode}.{meshAttr}', wrapPlug)


def isDeformer(node: str) ->bool:
    """
    Check if the given node is a deformer by looking at its inherited node types.

    Args:
        node (str): The name of the node to check.

    Returns:
        bool: True if the node is a deformer, False otherwise.
    """
    # Get the inherited node types of the given node
    test = cmds.nodeType(node, inherited=True) or []

    # Return True if 'geometryFilter' is in the list of inherited types, otherwise False
    return "geometryFilter" in test

@acceptString('object_list')
def maya_edit_sets(deformer_name: str, object_list: list, **kwargs):
    """
    Add or remove objects from a set connected to the given deformer.

    Args:
        deformer_name (str): The name of the deformer.
        object_list (list): List of objects to add or remove.
        **kwargs: Optional flags for Maya's `cmds.sets` function (e.g., 'add', 'remove').

    Valid Flags:
        - add: Adds objects to the set.
        - remove: Removes objects from the set.
        - addElement: Adds a single element to the set.
        - rm: Alias for remove.

    Example:
        maya_edit_sets("skinCluster1", ["pCube1"], add=True)
    """
    # Accepted flags
    flags_accepted = ['remove', 'rm', 'add', 'addElement']

    # Ensure the deformer exists
    if not cmds.objExists(deformer_name):
        cmds.error(f"Deformer '{deformer_name}' does not exist.")
        return

    # Get the object set connected to the deformer
    object_set = cmds.listConnections(deformer_name, type="objectSet")

    if not object_set:
        cmds.error(f"No object set found connected to the deformer '{deformer_name}'.")
        return
    object_set = object_set[0]  # The first connected set is used

    # Find the first valid flag in kwargs
    flag = None
    for fa in flags_accepted:
        if kwargs.get(fa):
            flag = fa
            break

    # If a valid flag is found, update the kwargs and edit the set
    if flag:
        kwargs[flag] = object_set
        cmds.sets(object_list, **kwargs)
    else:
        cmds.error("No valid flag ('add', 'remove', 'addElement', 'rm') provided in kwargs.")

def editDeformer(**kwargs):
    """
    Based on selection :
    Edit a deformer by adding or removing objects from the set it affects.

    Args:
        kwargs: Flags that specify the operation to perform. Accepts:
            - remove: Removes objects from the set.
            - rm: Alias for remove.
            - add: Adds objects to the set.
            - addElement: Adds a single element to the set.

    Usage:
        Select the objects and the deformer in Maya, then run the command with a flag:
            editDeformer(add=True)
            editDeformer(remove=True)
    """
    flags_accepted = ['remove', 'rm', 'add', 'addElement']

    # Ensure that a valid flag is provided in the kwargs
    if not (set(kwargs.keys()) & set(flags_accepted)):
        print(f"Error: One flag must be set from this list: {flags_accepted}")
        return

    # Check that something is selected
    sel = cmds.ls(sl=True)
    if not sel or len(sel) < 2:
        print("Error: Please select at least one object and a deformer.")
        return

    # Objects to add/remove and the deformer
    objs = sel[:-1]
    deformer_sel = sel[-1]

    # Retrieve the history of the deformer and find any deformers in its history
    history = cmds.listHistory(deformer_sel)
    filter_deformers = [i for i in history if isDeformer(i)]

    if not filter_deformers:
        print(f"Error: No deformers found in the history of {deformer_sel}.")
        return

    # Use the first deformer found in the history and edit the set
    maya_edit_sets(filter_deformers[0], objs, **kwargs)


def getTargetMesh(targetTrans: str):
    """
    Retrieves the non-intermediate mesh shape from the given transform node.

    Args:
        targetTrans (str): The name of the transform node to check.

    Returns:
        str: The name of the non-intermediate mesh shape node, or None if not found.
    """
    # Check if the provided transform exists
    if not cmds.objExists(targetTrans):
        print(f"Error: Target transform '{targetTrans}' does not exist.")
        return None

    # Retrieve all shape nodes under the transform
    shape_nodes = cmds.ls(targetTrans, dag=True, shapes=True)

    for shape in shape_nodes:
        # Skip intermediate objects
        if cmds.getAttr(f"{shape}.io"):
            continue

        # Return the first valid mesh
        if cmds.nodeType(shape) == "mesh":
            return shape

    # No valid mesh found
    return None


def shrinkWrap(mesh: str, target: str,
               projection: int = 0, closestIfNoIntersection: int = 0,
               reverse: int = 0, bidirectional: int = 0,
               boundingBoxCenter: int = 1, axisReference: int = 0,
               alongX: int = 0, alongY: int = 0, alongZ: int = 0,
               offset: float = 0.0, targetInflation: float = 0.0) -> str:
    """
    Maya python function doesn't work so here it is in python
    Creates a shrink-wrap deformer on the mesh, wrapping it to the target object.
    ChatGPT did reformat the function

    Args:
        mesh (str): The name of the mesh to apply the shrink-wrap deformer on.
        target (str): The target mesh object.
        projection (int, optional): The projection method. Default is 0.
        closestIfNoIntersection (int, optional): Use closest point if no intersection. Default is 0.
        reverse (int, optional): Reverse the deformation. Default is 0.
        bidirectional (int, optional): Use bidirectional projection. Default is 0.
        boundingBoxCenter (int, optional): Use bounding box center. Default is 1.
        axisReference (int, optional): Axis reference for deformation. Default is 0.
        alongX (int, optional): Deform along the X-axis. Default is 0.
        alongY (int, optional): Deform along the Y-axis. Default is 0.
        alongZ (int, optional): Deform along the Z-axis. Default is 0.
        offset (float, optional): Offset for deformation. Default is 0.0.
        targetInflation (float, optional): Target inflation amount. Default is 0.0.

    Returns:
        str: The name of the shrink-wrap deformer node.
    """

    # Get the target mesh shape
    targetMesh = getTargetMesh(target)
    if not targetMesh:
        raise ValueError(f"Target mesh '{target}' not found.")

    # Find the surface of the mesh
    surf = cmds.listRelatives(mesh, path=True)
    surface = surf[0]

    # Create shrink-wrap deformer
    shrinkwrapNode = cmds.deformer(surface, type='shrinkWrap')[0]

    # Set shrink-wrap attributes
    cmds.setAttr(f"{shrinkwrapNode}.projection", projection)
    cmds.setAttr(f"{shrinkwrapNode}.closestIfNoIntersection", closestIfNoIntersection)
    cmds.setAttr(f"{shrinkwrapNode}.reverse", reverse)
    cmds.setAttr(f"{shrinkwrapNode}.bidirectional", bidirectional)
    cmds.setAttr(f"{shrinkwrapNode}.boundingBoxCenter", boundingBoxCenter)
    cmds.setAttr(f"{shrinkwrapNode}.axisReference", axisReference)
    cmds.setAttr(f"{shrinkwrapNode}.alongX", alongX)
    cmds.setAttr(f"{shrinkwrapNode}.alongY", alongY)
    cmds.setAttr(f"{shrinkwrapNode}.alongZ", alongZ)
    cmds.setAttr(f"{shrinkwrapNode}.offset", offset)
    cmds.setAttr(f"{shrinkwrapNode}.targetInflation", targetInflation)

    # Connect target mesh attributes to the shrinkwrap node
    cmds.connectAttr(f"{targetMesh}.worldMesh[0]", f"{shrinkwrapNode}.target")
    cmds.connectAttr(f"{targetMesh}.continuity", f"{shrinkwrapNode}.continuity")
    cmds.connectAttr(f"{targetMesh}.smoothUVs", f"{shrinkwrapNode}.smoothUVs")
    cmds.connectAttr(f"{targetMesh}.keepBorder", f"{shrinkwrapNode}.keepBorder")
    cmds.connectAttr(f"{targetMesh}.boundaryRadius", f"{shrinkwrapNode}.boundaryRadius")
    cmds.connectAttr(f"{targetMesh}.keepHardEdges", f"{shrinkwrapNode}.keepHardEdges")
    cmds.connectAttr(f"{targetMesh}.propagateEdgeHardness", f"{shrinkwrapNode}.propagateEdgeHardness")
    cmds.connectAttr(f"{targetMesh}.keepMapBorders", f"{shrinkwrapNode}.keepMapBorders")

    return shrinkwrapNode

def createForceBS(_source_msh: str, _target_msh: str, **kwargs) -> list:
    """
    Creates a blend shape (BS) between the source and target meshes with a custom naming convention and cleans up the scene.

    Args:
        _source_msh (str): The name of the source mesh that drives the blend shape.
        _target_msh (str): The name of the target mesh that will be deformed by the blend shape.
        **kwargs: Additional blend shape options (e.g., prefix, name, etc.).

    Returns:
        list: Returns the created blend shape node and the name of the intermediate shape.
    """

    # Extract prefix from kwargs (default is empty string)
    _prefix = Flags(kwargs, '', 'prefix')
    if _prefix != '':
        del kwargs['prefix']

    # Naming conventions for the blend shape
    _name_forcebs_sh = f'forceBs_{_prefix}_{_target_msh.replace(":", "_")}'.replace('__', '_') + 'Shape'
    _bs_name = f'bs_{_prefix}_{_target_msh.replace(":", "_")}'.replace('__', '_')

    # Check if a custom name is provided
    if kwargs.get('name'):
        _name_forcebs_sh = f'forceBs_{kwargs["name"]}Shape'
    else:
        kwargs['name'] = _bs_name

    # Create a temporary mesh shape
    bs_msh_sh = cmds.createNode('mesh', n=_name_forcebs_sh)
    bs_msh_tr = cmds.listRelatives(bs_msh_sh, parent=True)[0]

    # Connect the target mesh's output to the temporary mesh's input
    _target_out = get_type_io(_target_msh)
    bs_msh_in = get_type_io(bs_msh_sh, io=0)
    cmds.connectAttr(_target_out, bs_msh_in)
    cmds.delete(bs_msh_tr, ch=True)  # Clean up history on the temporary mesh

    # Create the blend shape
    bs = cmds.blendShape(_source_msh, bs_msh_tr, **kwargs)

    # Connect the blend shape output to the target mesh
    bs_out = get_type_io(bs[0])
    _target_in = get_type_io(_target_msh, io=0)
    cmds.connectAttr(bs_out, _target_in, f=True)

    # Clean up the original temporary connection
    bs_msh_sh_in = get_type_io(bs_msh_sh, io=0)
    cmds.disconnectAttr(bs_out, bs_msh_sh_in)

    # Reparent the temporary mesh shape under the target mesh and delete the transform node
    cmds.parent(bs_msh_sh, _target_msh, s=True, r=True)

    # TODO: Clean way to find the orig shape
    cmds.parent(f'{bs_msh_sh}Orig', _target_msh, s=True, r=True)
    cmds.delete(bs_msh_tr)

    # Mark the temporary mesh shape as intermediate (invisible)
    cmds.setAttr(f'{bs_msh_sh}.io', 1)

    # Return the blend shape node and the name of the intermediate shape
    return [bs[0], _name_forcebs_sh]


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


def _connect_deformer(ctrl: str, offsetCtrl: str, members: list, meshFaces: list,
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

    # Filter existing parents
    existingParents = cmds.ls(parents)
    nonExistingParents = set(parents) - set(existingParents)
    if nonExistingParents:
        print(f"The following parent objects do not exist and have been skipped: {list(nonExistingParents)}")

    if not name and not existingParents:
        print("You must provide either parent objects or a name. Nothing created.")
        return []

    bGenerateNameFromParent = not name
    if bGenerateNameFromParent:
        print("No name provided. Generating names from parent objects.")

    deformers = []
    offsetCtrls = []

    for parentNum, parent in enumerate(existingParents):
        baseName = getUniqueBaseName(parent, name, bGenerateNameFromParent)

        if not createOffsetCtrls:
            uniqueOffsetCtrlName = getUniqueBaseName(parent, dstSuffixes=['_offset_ctrl'])
            parent = cmds.rename(parent, uniqueOffsetCtrlName + '_offset_ctrl')

        # Generate unique deformer name
        name = getUniqueBaseName(baseName, dstSuffixes=['_' + deformerType, '_ctrl'])

        # Create Control
        ctrl = _create_control(deformerType, name, defaultFalloffRadius)

        # Offset Control Creation
        offsetCtrl = _create_offset_control(name, falloffRadius, createOffsetCtrls, parent)

        # Add locator shape to access worldPosition
        _add_locator_shape_to_offset_ctrl(offsetCtrl)

        # Connect Deformer
        _connect_deformer(ctrl, offsetCtrl, members, meshFaces, falloffRadius, deformerType, multiFaceMode)

        # Finalize Control Setup
        cmds.parent(ctrl, offsetCtrl)
        _reset_transform(ctrl)

        if createOffsetCtrls:
            cmds.parent(offsetCtrl, parent)

        offsetCtrls.append(offsetCtrl)

    return offsetCtrls


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


def editMembership(deformer=None):
    """
    Launch Maya's EditMembershipTool for the specified deformer.

    Args:
        deformer (str, optional): The name of the deformer. If no deformer is provided, the tool will be launched on the currently selected objects.

    Usage:
        editMembership("myCluster")
    """
    if deformer:
        # Select the parent object of the deformer
        parent_object = cmds.listRelatives(deformer, parent=True)
        if parent_object:
            cmds.select(parent_object[0], replace=True)
        else:
            cmds.warning(f"Deformer '{deformer}' has no parent.")
    else:
        cmds.warning("No deformer provided. Please select a deformer.")

    # Launch Maya's Edit Membership Tool
    mel.eval("EditMembershipTool")


def paintWeights(deformer=None):
    """
    Launch Maya's Paint Weights Tool for the specified deformer.

    Args:
        deformer (str, optional): The name of the deformer. This could be a softMod or a cluster.

    Usage:
        paintWeights("mySoftMod")
        paintWeights("myCluster")
    """
    if not deformer:
        cmds.warning("No deformer provided. Please specify a deformer.")
        return

    defNode = None
    geo = None

    # Check for softMod deformer
    if cmds.listConnections(deformer, type="softMod"):
        defNode = cmds.listConnections(deformer, type="softMod")
        if defNode:
            geo = cmds.softMod(defNode[0], query=True, geometry=True)
            if geo:
                cmds.select(geo)
                mel.eval(f'artSetToolAndSelectAttr( "artAttrCtx", "softMod.{defNode[0]}.weights" );')
                mel.eval('artAttrInitPaintableAttr;')

    # Check for cluster deformer
    elif cmds.listConnections(deformer, type="cluster"):
        defNode = cmds.listConnections(deformer, type="cluster")
        if defNode:
            geo = cmds.cluster(defNode[0], query=True, geometry=True)
            if geo:
                cmds.select(geo)
                mel.eval(f'artSetToolAndSelectAttr( "artAttrCtx", "cluster.{defNode[0]}.weights" );')
                mel.eval('artAttrInitPaintableAttr;')

    # Handle case where deformer is not found or not supported
    else:
        cmds.warning(f"No supported deformer (softMod or cluster) found for '{deformer}'.")


def deleteDeformer(deformers):
    """
    Deletes the specified deformer(s) and any associated child or parent nodes.

    Args:
        deformers (list): A list of deformer names to be deleted.

    Usage:
        deleteDeformer(["myCluster", "mySoftMod"])
    """
    if not deformers:
        cmds.warning("No deformers provided for deletion.")
        return

    for deformer in deformers:
        if cmds.objExists(deformer):
            # Check if it's a child node with a dnSoftDeformChildMsg attribute
            if cmds.attributeQuery("dnSoftDeformChildMsg", node=deformer, exists=True):
                cmds.delete(deformer)
            # If not a child, check if it's a top node with dnSoftDeformTopNodeMsg attribute
            elif cmds.attributeQuery("dnSoftDeformTopNodeMsg", node=deformer, exists=True):
                parent = cmds.listRelatives(deformer, parent=True, type="transform")
                if parent and cmds.objExists(parent[0]):
                    # Check if the parent has dnSoftDeformChildMsg, indicating it's part of the deformer hierarchy
                    if cmds.attributeQuery("dnSoftDeformChildMsg", node=parent[0], exists=True):
                        cmds.delete(parent[0])
            # If none of the attributes exist, delete the deformer directly
            else:
                cmds.delete(deformer)
        else:
            cmds.warning(f"Deformer '{deformer}' does not exist.")


def generate_control_name(driver, geo_name, component, name_prefix=''):
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
    ctrl_zro = ''
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

    return ctrl_zro

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

        base_name = generate_control_name(driver, geo_name, component, namePrefix if not bGenerateName else '')

        # Create control or parent group
        ctrl_zro = create_control_group(base_name, radius, not createControlParentGroupsOnly)
        sticky_control_zeroes.append(ctrl_zro)

        if component:
            cmds.addAttr(ctrl_zro, ln="following", dt="string")
            cmds.setAttr(ctrl_zro + ".following", driver, type="string")

        mesh_shape = geo_name if cmds.nodeType(geo_name) == 'mesh' else cmds.listRelatives(geo_name, noIntermediate=1, shapes=1, fullPath=1)[0]
        in_mesh_con = cmds.connectionInfo(mesh_shape + '.inMesh', sourceFromDestination=True)

        temp_cluster = None
        if not in_mesh_con:
            temp_cluster = cmds.cluster(mesh_shape, name='temp_cluster')
            in_mesh_con = cmds.connectionInfo(mesh_shape + '.inMesh', sourceFromDestination=True)

        # Get UVs and setup follicle or pointOnPoly constraint
        sh_only = mesh_shape.rsplit("|")[-1] # key is only the shape
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


def selectionToSpaceSeparatedString(listOfStrings):
    """
    Converts a list of strings to a single, space-separated string.
    """
    # Join the list of strings into a space-separated string
    spaceSeparatedSelString = ' '.join(listOfStrings)

    return spaceSeparatedSelString


def stringToListOfStrings(stringOfObjects):
    """
    Converts a string to a list of strings. The string may contain opening and closing brackets ('[', ']'),
    spaces, commas, and single or double quotes.

    Example inputs:
    - 'face_216_locator face_237_locator face_276_locator'
    - "face_216_locator, face_237_locator, face_276_locator"
    - "[u'face_216_locator', u'face_237_locator', u'face_276_locator']"
    - '["face_216_locator", "face_237_locator", "face_276_locator"]'
    - ' [pPlane1.f[779],  pPlane1.f[392], pPlane1.f[1433], pPlane1.f[323]] '

    Returns:
    - A cleaned list of strings, e.g., ['face_216_locator', 'face_237_locator', 'face_276_locator']
    """
    # Remove any leading/trailing whitespace and brackets if they exist
    stringOfObjects = stringOfObjects.strip().lstrip('[').rstrip(']')

    # Replace unwanted characters (u' for unicode notation, commas, quotes)
    cleanedString = stringOfObjects.replace("u'", '').replace("'", '').replace('"', '').replace(",", '')

    # Split the cleaned string into individual objects
    objList = cleanedString.split()

    return objList


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

    return stickyControls + deformer_output


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
    return 0.0


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
    cmds.setAttr("{}.falloffRadius".format(out[0]), 0.5)

    return out
