import sys
# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

from typing import List
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_alembic_utils as dwabc
import maya.cmds as cmds
import maya.mel as mel
import dw_maya.dw_decorators as dwdeco

def makeTextureReferenceObject(sel: List[str]) -> List[str]:
    """===========================================================================
    Copyright 2017 Autodesk, Inc. All rights reserved.

    Use of this software is subject to the terms of the Autodesk license
    agreement provided at the time of installation or download, or which
    otherwise accompanies this software in either electronic or hard copy form.
    ===========================================================================

    Description
        Looks at the selection list for the first piece of
        geometry and then proceeeds to:
                duplicate it
                translate it slightly
                template it
                make it a reference object of the original
                surface.
    """

    output = []
    selectedObjects = cmds.ls(sel, type = ['transform', 'geometryShape'])
    # Get the relevant selected objects (transforms or geometryShapes)
    if len(selectedObjects) >= 1:
        allShapeNodes = cmds.ls(selectedObjects[0], type = 'geometryShape', dagObjects = 1, sl = 1)
        # Get the geometryShapeNodes for the first selected object.
        originalShapeNodes = []
        for shape in allShapeNodes:
            intermediate = int(cmds.getAttr(str(shape) + ".intermediateObject"))
            if not intermediate:
                originalShapeNodes.append(str(shape))

        if len(originalShapeNodes) >= 1:
            duplicatedObj = cmds.duplicate(selectedObjects[0], n = (selectedObjects[0] + "_reference"))
            cmds.setAttr(duplicatedObj[0] + ".template", True)
            listOfParents = cmds.listRelatives(duplicatedObj[0], p = 1)
            if len(listOfParents) > 0:
                cmds.parent(duplicatedObj[0], w = 1)

            duplicatedShapeNodesTmp = cmds.ls(duplicatedObj[0], type = 'geometryShape', dagObjects = 1, sl = 1)
            # Get a list of geometryShape nodes for the duplicated object
            # This list will have the duplicated objects.  Cull them.
            duplicatedShapeNodes = []
            for shape in duplicatedShapeNodesTmp:
                intermediate = int(cmds.getAttr(str(shape) + ".intermediateObject"))
                if not intermediate:
                    duplicatedShapeNodes.append(str(shape))

            if len(originalShapeNodes) == len(duplicatedShapeNodes):
                # The originalShapeNodes and duplicatedShapeNodes are arrays
                # that must have the same elements or we are in big trouble
                for i, shapeNode in enumerate(originalShapeNodes):
                    cmds.connectAttr((duplicatedShapeNodes[i] + ".msg"), (str(shapeNode) + ".referenceObject"))
                    new_name = cmds.rename(duplicatedShapeNodes[i],
                                (str(shapeNode) + "_reference"))
                    output.append(new_name)
            else:
                cmds.warning("m_makeReferenceObject.kReferenceObjectHasDifferentTopology")

    return output

@dwdeco.acceptString('sel')
def saveGuidesRestPosition(sel: List[str]):
    """
    Saves the rest position of guides for the selected object sets.

    Args:
        sel (list): A list of selected objects, expected to contain object sets.

    Returns:
        None
    """
    # Filter the selection to only include object sets
    available = [i for i in sel if cmds.nodeType(i) == 'objectSet']

    # Iterate over available object sets and process them
    for x, s in enumerate(available):
        cmds.select(s, r=True)
        mel.eval('pgYetiCommand -saveGuidesRestPosition;')
        print(f'{x}- "{s}" objectSet has been processed for guide rest position!')

@dwdeco.acceptString('sel')
def groomToCurve(sel: List[str], alias='guide'):
    """
    Converts selected Yeti grooms to curves and organizes them into a group.

    Args:
        sel (list): List of selected objects (Yeti grooms).
        alias (str): Alias to replace 'PYGShape_strand' in curve names.

    Returns:
        list: List of group names containing the newly created curves.
    """
    out = []
    # Get the list of selected Yeti groom nodes
    sel_grm = cmds.ls(sel, dag=True, type='pgYetiGroom')

    for s in sel_grm:
        cmds.select(s)
        # Capture the initial state before creating curves
        sets_init = cmds.ls(type='objectSet')
        nodes_init = dwu.lsTr(type='nurbsCurve', l=True)

        # Execute the conversion from Yeti groom to curves
        mel.eval('pgYetiConvertGroomToCurves;')
        # Capture the state after the curves are created
        sets_end = cmds.ls(type='objectSet')
        noddes_end = dwu.lsTr(type='nurbsCurve', l=True)

        # Find the differences between the initial and final states
        nodes_diff = list(set(noddes_end)-set(nodes_init))
        sets_diff = list(set(sets_end)-set(sets_init))

        # Delete the temporary sets created during the process
        cmds.delete(sets_diff)

        # Rename the created curves and group them
        crvs = []
        for nd in nodes_diff:
            name = nd.split('|')[-1].replace('PYGShape_strand', alias)
            new = cmds.rename(nd, name)
            crvs.append(new)
        # Group the renamed curves
        grp_name = f'{crvs[0].rsplit("_", 1)[0]}s_grp'
        grp = cmds.group(crvs, name=grp_name)
        out.append(grp)
    return out

def getGuideSetConnections(namespace=':'):
    """
    Collects the connections between Yeti guide sets and Yeti nodes in the scene.

    Args:
        namespace (str): The namespace to filter the assets. Default is ':' (all namespaces).

    Returns:
        dict: A dictionary with object sets as keys and their connected Yeti nodes and attributes as values.
    """
    setUsage = {}
    yetiGuideCon = {}

    # Determine the asset pattern based on the provided namespace
    if namespace == ':':
        asset = '*'
    else:
        asset=namespace+':*'

    # Find all pgYetiMaya nodes in the specified namespace
    for gr in cmds.ls(asset, type = 'pgYetiMaya'):
        con = cmds.listConnections(f'{gr}.guideSets', d=False, p=True, type='objectSet')
        if con:
            con = list(set(con)) # Remove any duplicate connections
            sets_data = [i.split('.') for i in con]

            # Collect attributes connected to each object set
            for sd in sets_data:
                if sd[0] not in setUsage:
                    setUsage[sd[0]] = [sd[1]]
                else:
                    setUsage[sd[0]].append(sd[1])
    # For each object set, find which Yeti nodes and attributes are connected
    for su in setUsage:
        if su not in yetiGuideCon:
            attrs = [f'{su}.{i}' for i in setUsage[su]]
            dest = cmds.listConnections(attrs, s=False, shapes=True, p=True, type='pgYetiMaya')
            yetiGuideCon[su] = [attrs[0], list(set(dest))]
    return yetiGuideCon

def setGuideSetConnections(set_name: str, con_dic: dict):
    """
    Connects the attributes of the guide set to the destination attributes based on the provided connection dictionary.

    Args:
        set_name (str): The name of the guide set to connect.
        con_dic (dict): A dictionary containing the connection information for the guide set.

    Example structure of con_dic:
    {
        "set_name": ["source_attr", ["destination_attr1", "destination_attr2"]]
    }
    """
    if set_name in con_dic:
        source_attr, destination_attrs = con_dic[set_name]
        for dest in destination_attrs:
            cmds.connectAttr(source_attr, dest, f=True)


@dwdeco.singleUndoChunk
def renderGroomToCurve(groom):
    """
    Converts Yeti groom node to curves, renames them, groups them,
    and manages the connections and sets for the guide and simulation curves.
    Useful for Yeti rendering when sim guides are attached in a new scene because
    of bugs....

    Args:
        groom (str): The Yeti groom node to be converted to curves.

    Returns:
        list: A list of top guide sets created.
    """
    # Retrieve the Yeti guide connections
    yetiGuideCon = getGuideSetConnections(':')
    output = []
    p = '_GRP'

    # Process both guide and simulation curves
    for typ in ['guide', 'sim']:
        # Convert groom to curves for the given type (guide or sim)
        guides = groomToCurve(groom, typ)
        # guides return groups of guides
        for g in guides:
            # Iterate over the groups of curves returned
            top_grp = f'C_{typ}s_GRP'
            top_set = f'{typ}sGroup_set'
            target_name = g.replace('_grp', p)
            set_name = g.replace('_grp', '_set')

            # Delete any existing group or set with the same name
            if cmds.objExists(target_name):
                cmds.delete(target_name)
            if cmds.objExists(set_name):
                cmds.delete(set_name)

            # Rename the group and get curves
            new_name = cmds.rename(g, target_name)
            crvs = dwu.lsTr(new_name, dag=True, type='nurbsCurve')

            # Create a set for the curves
            addYetiCurveAttr(crvs)
            new_set = cmds.sets(crvs, name=new_name.rsplit('_', 1)[0]+'_set')

            # Parent the group to the top guide or sim group
            if cmds.objExists(top_grp):
                cmds.parent(target_name, top_grp)
            else:
                cmds.group(target_name, n=top_grp)

            # Create the top set if it doesn't exist
            if not cmds.objExists(top_set):
                cmds.sets(em=True, name=top_set)
            cmds.sets(new_set, edit=True, fe=top_set)

            # Save guide rest position and restore any guide set connections
            saveGuidesRestPosition([new_set])
            setGuideSetConnections(new_set, yetiGuideCon)

            output.append(top_set)

    return output

def manual_cache(topNode, path, framerange = [0,0,0], autoDir=True):
    """
    Caches the specified Yeti nodes under topNode.

    Args:
        topNode (str): Top node of the hierarchy containing Yeti nodes.
        path (str): Directory path where the cache will be written.
        framerange (list): List of [start, end, sample] for frame range.
        autoDir (bool): Whether to automatically create subdirectories.

    Returns:
        None
    """
    # Handle frame range
    frm0, frm1, samp = 0, 0, 0
    if any(framerange) and isinstance(framerange, (list, tuple)):
        if len(framerange) == 2:
            frm0, frm1 = framerange[0:2]
            samp = 1
        if len(framerange) == 3:
            frm0, frm1 = framerange[0:2]
            samp = framerange[2] or 1

        if len(framerange) == 1 or len(framerange) > 3:
            cmds.error('list must have two or three entries : [start, end, sample]')
    else:
        frm0, frm1 = dwu.current_timerange()
        samp = 1

    # Get all Yeti nodes under topNode
    pgYetis = cmds.ls(topNode, dag=True, type='pgYetiMaya')
    restore = {}

    for pgy in pgYetis:
        node = dwu.lsTr(pgy)[0]
        if not cmds.getAttr(f'{node}.visibility', l=True):
            restore[f'{node}.visibility'] = cmds.getAttr(node+'.visibility')
            cmds.setAttr(f'{node}.visibility', 0)
        # Set cache attributes
        cmds.setAttr(f"{pgy}.fileMode", 0)
        cmds.setAttr(f"{pgy}.outputCacheFrameRangeStart", frm0)
        cmds.setAttr(f"{pgy}.outputCacheFrameRangeEnd", frm1)
        cmds.setAttr(f"{pgy}.outputCacheNumberOfSamples", samp)

        # Adjust the path
        tmp_path = path[:]
        if not tmp_path.endswith('.fur'):
            name = pgy.split('|')[-1].rsplit('_', 1)[0].replace(':', '_')
            if not tmp_path.endswith('/'):
                tmp_path = tmp_path + '/'
        else:
            name = None

        # If a name is available, prepare the cache directory
        if name:
            sc = ''
            if autoDir:
                sc = dwu.scene_name(True)
                if sc != '':
                    sc += f'/{name}'
            else:
                sc += name

            mkpath = dwabc.make_dir(f'{tmp_path}{sc}')
            tmp_path = f'{mkpath}/{name}.%04d.fur'

        # Set the file path for the cache
        cmds.setAttr(f'{pgy}.cacheFileName', tmp_path, type='string')
        cmds.setAttr(f'{pgy}.outputCacheFileName', tmp_path, type = 'string')

    # Write the cache and restore visibility
    for pgy in pgYetis:
        node = dwu.lsTr(pgy)[0]
        try:
            cmds.setAttr(f'{node}.visibility', 1)
        except:
            pass

        # Write the Yeti cache
        # mel.eval('AEpgYetiWriteCacheCMD {}'.format(pgy))
        createYetiCache(pgy)
        try:
            cmds.setAttr(f'{node}.visibility', 0)
        except:
            pass

    # Restore the original visibility
    for n, v in restore.items():
        cmds.setAttr(n, v)

@dwdeco.viewportOff
@dwdeco.timeIt
def createYetiCache(node):
    """
    Creates a Yeti cache for the given Yeti node.

    Args:
        node (str): The Yeti node or its parent transform node.

    Returns:
        None
    """
    flags = {}
    # Determine if the node is a pgYetiMaya node or its parent
    if cmds.nodeType(node) == 'pgYetiMaya':
        yeti_node = node
    else:
        yeti_node = cmds.listRelatives(node, type='pgYetiMaya')[0]

    # Gather attributes from the Yeti node
    flags = {
        'node': yeti_node,
        'st': cmds.getAttr(f"{yeti_node}.outputCacheFrameRangeStart"),
        'et': cmds.getAttr(f"{yeti_node}.outputCacheFrameRangeEnd"),
        'samp': cmds.getAttr(f"{yeti_node}.outputCacheNumberOfSamples"),
        'view': cmds.getAttr(f"{yeti_node}.outputCacheUpdateViewport"),
        'gP': cmds.getAttr(f"{yeti_node}.outputCacheGeneratePreview"),
        'file': cmds.getAttr(f"{yeti_node}.outputCacheFileName")
    }

    # Build the pgYetiCommand MEL command
    c = 'pgYetiCommand -writeCache "{file}" -range {st} {et} -samples {samp} -updateViewport {view} -generatePreview {gP} "{node}"'.format(**flags)
    c = c.replace(' False ', ' false ').replace(' True ', ' true ')
    mel.eval(c)
    # pgYetiCommand - writeCache $fileName - range $startFrame $endFrame -samples $numberOfSamples -updateViewport $enableViewportUpdate -generatePreview $generatePreview $node;

def pgy_listParams(node: str):
    """List all parameters of the given Yeti node."""
    return cmds.pgYetiGraph(node=node, listParams=True)

def pgy_getType(node: str):
    """Get the type of the Yeti node."""
    return cmds.pgYetiGraph(node=node, param='type', getParamValue=True)

def pgy_getParam(node: str, param: str):
    """Fetch the value of the specified parameter for the given Yeti node."""
    return cmds.pgYetiGraph(node=node, param=param, getParamValue=True)

def addSetToYeti(setName: str, pgYetiMayaNode: str):
    """Add a guide set to the specified Yeti node using MEL."""
    mel.eval(f'pgYetiAddGuideSet("{setName}", "{pgYetiMayaNode}");')


def addYetiAttrSetCtrl(sets: list, **kwargs):
    """
    Adds attributes to a set of Yeti curves and connects them to control curves.

    Args:
        sets (list): A list of object sets representing Yeti curves.
        kwargs: Additional attributes to be added.
    """
    sets_nodes = cmds.ls(sets, type='objectSet')

    for s in sets_nodes:
        # Query the curves within the set and get their shape nodes
        curves = cmds.sets(s, q=True)
        curves_sh = dwu.lsTr(curves, type='nurbsCurve', p=False)

        # Define attributes using dwu.Flags
        attrs = dwu.Flags(kwargs, 3, 'maxNumberOfGuideInfluences', 'mng', dic={})
        attrs = dwu.Flags(kwargs, 1, 'stepSize', 'stp', dic=attrs)
        attrs = dwu.Flags(kwargs, 1, 'weight', 'w', dic=attrs)
        attrs = dwu.Flags(kwargs, 1, 'lengthWeight', 'lw', dic=attrs)
        attrs = dwu.Flags(kwargs, 0, 'innerRadius', 'ir', dic=attrs)
        attrs = dwu.Flags(kwargs, 2, 'outerRadius', 'or', dic=attrs)
        attrs = dwu.Flags(kwargs, 1, 'density', 'd', dic=attrs)
        attrs = dwu.Flags(kwargs, 1, 'baseAttraction', 'ba', dic=attrs)
        attrs = dwu.Flags(kwargs, 1, 'tipAttraction', 'ta', dic=attrs)
        attrs = dwu.Flags(kwargs, 0, 'attractionBias', 'ab', dic=attrs)
        attrs = dwu.Flags(kwargs, 0, 'randomAttraction', 'ra', dic=attrs)
        attrs = dwu.Flags(kwargs, 0, 'twist', 'tw', dic=attrs)

        # Iterate through the attributes and connect them to the shape nodes
        for a, v in attrs.items():
            dwu.add_attr(s, a, v, 'double', dv=v)
            for c in curves_sh:
                con_attr = cmds.ls(f'{c}.{a}')
                if con_attr:
                    cmds.connectAttr(f'{s}.{a}', con_attr[0], f=True)


def addYetiSetAttr(sets: list, **kwargs):
    """
    Add attributes to Yeti sets with specified values from kwargs.

    Args:
        sets (list): List of object set names to add attributes to.
        kwargs: Attribute values to be set. Supports 'maxNumberOfGuideInfluences' and 'stepSize'.
    """
    # Get list of object sets
    sets_nodes = cmds.ls(sets, type='objectSet')

    # Define attributes using dwu.Flags
    attrs = dwu.Flags(kwargs, 3, 'maxNumberOfGuideInfluences', 'mng', dic={})
    attrs = dwu.Flags(kwargs, 1, 'stepSize', 'stp', dic=attrs)

    # Add attributes to each set node
    for n in sets_nodes:
        for a, v in attrs.items():  # Use items() instead of iteritems() in Python 3
            dwu.addAttribute(n, a, v, 'double', dv=v)


def addYetiCurveAttr(curves: list, **kwargs):
    """
    Add Yeti curve-related attributes to the specified curves.

    Args:
        curves (list): List of curve names.
        kwargs: Additional keyword arguments to specify the attributes. Supports
                'weight', 'lengthWeight', 'innerRadius', 'outerRadius', 'density',
                'baseAttraction', 'tipAttraction', 'attractionBias', 'randomAttraction',
                and 'twist'.

    Returns:
        list: Attribute names if 'query' flag is set.
    """
    # Query attributes if requested
    query = dwu.Flags(kwargs, 0, 'query', 'q')
    if query:
        return ['weight', 'lengthWeight', 'innerRadius', 'outerRadius',
                'density', 'baseAttraction', 'tipAttraction', 'attractionBias',
                'randomAttraction', 'twist']

    # Retrieve curve shapes
    curves_sh = dwu.lsTr(curves, type='nurbsCurve', p=False)

    # Define attribute values
    attrs = dwu.Flags(kwargs, 1, 'weight', 'w', dic={})
    attrs = dwu.Flags(kwargs, 1, 'lengthWeight', 'lw', dic=attrs)
    attrs = dwu.Flags(kwargs, 0, 'innerRadius', 'ir', dic=attrs)
    attrs = dwu.Flags(kwargs, 2, 'outerRadius', 'or', dic=attrs)
    attrs = dwu.Flags(kwargs, 1, 'density', 'd', dic=attrs)
    attrs = dwu.Flags(kwargs, 1, 'baseAttraction', 'ba', dic=attrs)
    attrs = dwu.Flags(kwargs, 1, 'tipAttraction', 'ta', dic=attrs)
    attrs = dwu.Flags(kwargs, 0, 'attractionBias', 'ab', dic=attrs)
    attrs = dwu.Flags(kwargs, 0, 'randomAttraction', 'ra', dic=attrs)
    attrs = dwu.Flags(kwargs, 0, 'twist', 'tw', dic=attrs)

    for s in curves_sh:
        # Iterate through the attributes and connect them to the shape nodes
        for a, v in attrs.items():
            dwu.add_attr(s, a, v, 'double', dv=v)
            for c in curves_sh:
                con_attr = cmds.ls(f'{c}.{a}')
                if con_attr:
                    cmds.connectAttr(f'{s}.{a}', con_attr[0], f=True)

@dwdeco.acceptString('set_nodes')
def saveGuidesRestPosition(set_nodes: list):
    """
    Saves the guides' rest position for each object set in the provided nodes.

    Args:
        set_nodes (list): A list of nodes that must be of type 'objectSet'.

    Raises:
        RuntimeError: If any node in set_nodes is not an objectSet.
    """
    if all([True for i in set_nodes if cmds.nodeType(i) == 'objectSet']):
        for node in set_nodes:
            mel.eval(f'pgYetiCommand -saveGuidesRestPosition "{node}"')
    else:
        cmds.error('Please provide a valid object set.')


def AEpgYetiAddUserAttribute(_type: int, node: str, attr_name: str):
    """
    Adds a user attribute to the Yeti node. Depending on the _type, it can add a float or vector (double3) attribute.

    Args:
        _type (int): Type of attribute. 0 for float (double), 1 for vector (double3).
        node (str): Name of the Yeti node.
        attrName (str): Name of the attribute to add.
    """
    if attr_name:
        if _type == 0:
            cmds.addAttr(node, ln=f"yetiVariableF_{attr_name}", keyable=True, at='double', defaultValue=0.0, softMinValue=0.0, softMaxValue=100.0)
        else:
            parent_attr = f"yetiVariableV_{attr_name}"
            cmds.addAttr(node, ln=parent_attr, keyable=True, at='double3')
            for axis in "XYZ":
                cmds.addAttr(node, ln=f"{parent_attr}{axis}", keyable=True, at='double', p=parent_attr)
    else:
        cmds.warning("Please provide an acceptable attribute name...")

    # Update the attribute editor
    mel.eval(f'updateAE("{node}");')

def createSimBindNetwork(ygt, x=0, simsetfrm='C_*_sim_set', color=[0.478, 0.322, 0.574]):
    """
    Create a simulation binding network in a Yeti node for simulating fibers and hair.

    Args:
        ygt (str): The Yeti node to add the network to.
        x (int): Counter for unique node naming.
        simsetfrm (str): Naming pattern for the simulation set.
        color (list): RGB color for coloring the Yeti nodes.

    TODO : disconnect every slots because of auto connect by default

    Returns:
        None
    """

    COUNTER = x
    def update_yeti(node):
        mel.eval(f'pgYetiForceUpdate("{node}");')

    # GEOMETRY SCALP
    imp = cmds.pgYetiGraph(ygt, create=True, type='import')
    imp_name = f'dw_imp_geo{COUNTER}'
    update_yeti(ygt)
    cmds.pgYetiGraph(node=imp, rename=imp_name)
    cmds.pgYetiGraph(node=imp_name, param='geometry', setParamValueString='*')
    update_yeti(ygt)
    mel.eval(f'pgYetiMayaUI -setSelectedNodesColor {color[0]} {color[1]} {color[2]};')

    # CONVERT TO FIBRES
    fib = cmds.pgYetiGraph(ygt, create=True, type='convert')
    fib_name = f'dw_convert_to_fibres{COUNTER}'
    update_yeti(ygt)
    cmds.pgYetiGraph(node=fib, rename=fib_name)
    update_yeti(ygt)
    cmds.pgYetiGraph(ygt, node=imp_name, connect=[fib_name, 1])
    mel.eval(f'pgYetiMayaUI -setSelectedNodesColor {color[0]} {color[1]} {color[2]};')

    # GUIDE NODE
    gui = cmds.pgYetiGraph(ygt, create=True, type='guide')
    gui_name = f'dw_guide{COUNTER}'
    update_yeti(ygt)
    cmds.pgYetiGraph(node=gui, rename=gui_name)
    update_yeti(ygt)
    cmds.pgYetiGraph(ygt, node=fib_name, connect=[gui_name, 0])
    mel.eval(f'pgYetiMayaUI -setSelectedNodesColor {color[0]} {color[1]} {color[2]};')

    # CURVE SET
    cset = cmds.pgYetiGraph(ygt, create=True, type='import')
    cset_name = f'dw_imp_guides{COUNTER}'
    update_yeti(ygt)
    cmds.pgYetiGraph(node=cset, rename=cset_name)
    cmds.pgYetiGraph(node=cset_name, param='geometry', setParamValueString=simsetfrm)
    cmds.pgYetiGraph(node=cset_name, param='type', setParamValueScalar=2)
    update_yeti(ygt)
    cmds.pgYetiGraph(ygt, node=cset_name, connect=[gui_name, 1])
    mel.eval(f'pgYetiMayaUI -setSelectedNodesColor {color[0]} {color[1]} {color[2]};')

    # CREATE CUSTOM ATTR (useNHair)
    try:
        AEpgYetiAddUserAttribute(0, ygt, 'useNHair')
    except Exception:
        pass

    # BLEND
    ble = cmds.pgYetiGraph(ygt, create=True, type='blend')
    ble_name = f'dw_useNHair{COUNTER}'
    update_yeti(ygt)
    cmds.pgYetiGraph(node=ble, rename=ble_name)
    cmds.pgYetiGraph(node=ble_name, param='blend', setParamValueExpr='$useNHair')
    cmds.pgYetiGraph(ygt, node=fib_name, connect=[ble_name, 0])
    cmds.pgYetiGraph(ygt, node=gui_name, connect=[ble_name, 1])
    mel.eval(f'pgYetiMayaUI -setSelectedNodesColor {color[0]} {color[1]} {color[2]};')

    # CONVERT TO STRAND
    stra = cmds.pgYetiGraph(ygt, create=True, type='convert')
    stra_name = f'dw_convert_to_strands{COUNTER}'
    update_yeti(ygt)
    cmds.pgYetiGraph(node=stra, rename=stra_name)
    cmds.pgYetiGraph(node=stra_name, param='conversion', setParamValueScalar=1)
    cmds.pgYetiGraph(ygt, node=imp_name, connect=[stra_name, 1])
    cmds.pgYetiGraph(ygt, node=ble_name, connect=[stra_name, 0])
    mel.eval(f'pgYetiMayaUI -setSelectedNodesColor {color[0]} {color[1]} {color[2]};')

    # COMB NODE
    comb = cmds.pgYetiGraph(ygt, create=True, type='comb')
    comb_name = f'dw_comb{COUNTER}'
    update_yeti(ygt)
    cmds.pgYetiGraph(node=comb, rename=comb_name)
    cmds.pgYetiGraph(ygt, node=stra_name, connect=[comb_name, 1])
    mel.eval(f'pgYetiMayaUI -setSelectedNodesColor {color[0]} {color[1]} {color[2]};')


@dwdeco.acceptString('name')
def getFaceSet(name):
    """
    Get a dictionary of face sets from the provided object set name.

    Args:
        name (str): Name of the object set.

    Returns:
        dict: A dictionary of face sets and their contents.
    """
    data = {}
    isTop = cmds.sets(name, q=True)

    # If the first element is not an object set, return the set directly
    if cmds.nodeType(isTop[0]) != 'objectSet':
        data[name] = isTop
    else:
        # If it is an object set, iterate through its elements
        for i in isTop:
            data[i] = cmds.sets(i, q=True)

    return data


def setFaceSet(assignDic=dict):
    """
    Assign elements to the face sets from a dictionary.

    Args:
        assignDic (dict): A dictionary where the key is the face set and the value is the list of objects to assign.
    """
    for k, v in assignDic.items():  # Use items() instead of iteritems() for Python 3 compatibility
        cmds.sets(v, fe=k)


def debugFaceSet(name, assignDic=dict):
    """
    Debug and recreate the face sets.

    Args:
        name (str): Name of the parent set.
        assignDic (dict): Dictionary of face sets to be debugged and recreated.
    """
    for k, v in assignDic.items():  # Use items() instead of iteritems()
        cmds.delete(k)
        mset = cmds.sets(v, name=k)
        cmds.sets(mset, edit=True, fe=name)