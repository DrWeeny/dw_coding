import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from maya import cmds, mel
from collections import defaultdict
from dw_maya.dw_decorators import viewportOff, tmp_disable_solver, acceptString
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_maya_nodes as dwnn
from .dw_get_uv_coord import getVertexMap
from itertools import chain
import re


@viewportOff
@tmp_disable_solver
def motion_ctrl_nucleus(nucleus=None, input_vertex=None):
    """
    Controls the position of the given nucleus node by setting its translation
    to match the position of the specified vertex over a given time range.

    Args:
        nucleus (str): The nucleus node to control. If not provided, the first selected nucleus is used.
        input_vertex (str): The vertex whose position will control the nucleus. If not provided, the first selected vertex is used.

    Returns:
        None
    """
    try:
        # Get the current time range (start and end)
        range_ = dwu.current_timerange(range_=True)

        # Get the input vertex
        if input_vertex:
            vtx_track = input_vertex
        else:
            selected_vertices = cmds.filterExpand(sm=31)
            if not selected_vertices:
                raise RuntimeError("No vertex selected or provided.")
            vtx_track = selected_vertices[0]

        # Get the nucleus node
        if not nucleus:
            selected_nucleus = cmds.ls(sl=True, type='nucleus')
            if not selected_nucleus:
                raise RuntimeError("No nucleus node selected or provided.")
            nucleus = selected_nucleus[0]

        # Iterate over the frames in the time range
        for frm in range_:
            cmds.currentTime(frm, e=True)
            pos = cmds.pointPosition(vtx_track)
            cmds.setAttr(nucleus + '.t', *pos)
            cmds.setKeyframe(nucleus, attribute=['tx', 'ty', 'tz'])

    except Exception as e:
        cmds.error(f"Error in motion_ctrl_nucleus: {e}")


def create_loca_cluster(_in=None,
                        _out=None,
                        matrix_node=None,
                        cam=None,
                        prefix=None,
                        ctrl=None):
    """
    Create a localization setup that includes clusters, a locator, and control nodes.

    This function set the animation at the origin for easier simulation

    Args:
        _in (str): The input geometry (e.g., vertex or curve) for the input cluster.
        _out (str): The output geometry for the output cluster.
        matrix_node (str, optional): A matrix node whose transformation is used for the localization.
        cam (str, optional): A camera node to be controlled by the setup.
        prefix (str, optional): Prefix for naming the created nodes.
        ctrl (str, optional): Control node to add attributes for controlling the localization setup.

    Returns:
        list or str:
            - If `matrix_node` is provided: Returns a list of the input and output cluster transform nodes.
            - If no `matrix_node` is provided: Returns the full attribute path of the decompose matrix input matrix.
    """
    # Set the prefix for naming
    if prefix:
        prefix += '_'
    else:
        prefix = ''

    # Define names for the clusters and locator
    main_in = prefix + 'loca_in_cls'
    main_out = prefix + 'loca_out_cls'
    loc_in = prefix + 'loca_in_loc'

    # Create null meshes (or consider using transforms instead)
    null1 = dwnn.MayaNode(prefix + 'loca_null1_msh', 'mesh')
    null2 = dwnn.MayaNode(prefix + 'loca_null2_msh', 'mesh')

    # Create clusters for input and output
    cls_in = cmds.cluster(_in, name=main_in)[1]
    cls_out = cmds.cluster(_out, name=main_out)[1]

    # Convert to MayaNode objects
    cls_in = dwnn.MayaNode(cls_in)
    cls_out = dwnn.MayaNode(cls_out)
    loc_in = dwnn.MayaNode(loc_in, 'locator')

    # Parent null meshes under clusters
    cmds.parent(null1.tr, cls_in.tr)
    cmds.parent(null2.tr, cls_out.tr)

    # Create decomposeMatrix node and multiplyDivide nodes
    decomp = dwnn.MayaNode(prefix + 'loca_dmx', 'decomposeMatrix')
    mult_enable = dwnn.MayaNode(prefix + 'loca_enable_mult', 'multiplyDivide')

    # Connect decompose matrix output to the clusters
    decomp.outputTranslate > mult_enable.input1
    mult_enable.output > cls_out.translate

    # Create additional multiplyDivide nodes for locator and cluster localization
    mult_enable_loc = dwnn.MayaNode(prefix + 'loca_loc_enable_mult', 'multiplyDivide')
    mult_loc_in = dwnn.MayaNode(prefix + 'loc_in_mult', 'multiplyDivide')
    mult_loc_in.input2.set(*[-1] * 3)

    mult_enable.output > mult_enable_loc.input1
    mult_enable_loc.output > mult_loc_in.input1
    mult_loc_in.output > loc_in.t

    mult_loc_cls = dwnn.MayaNode(prefix + 'cls_in_mult', 'multiplyDivide')
    mult_loc_cls.input2.set(*[-1] * 3)

    mult_enable.output > mult_loc_cls.input1
    mult_loc_cls.output > cls_in.t

    # Create attributes for the control node
    nodes = [cls_in.tr, cls_out.tr, loc_in.tr]
    grp = cmds.group(nodes, name=prefix + 'localisation_grp')

    # Check if control node exists or assign the group as the control node
    if cmds.objExists(ctrl):
        ctrl_node = dwnn.MayaNode(ctrl)
    else:
        ctrl_node = dwnn.MayaNode(grp)

    # Add custom attributes for localization and camera control
    ctrl_node.addAttr('localisation', value=1, min=-1, max=1)
    ctrl_node.addAttr('camera', value=1, min=-1, max=1)

    # Connect attributes to enable localization and camera controls
    for axis in 'XYZ':
        ctrl_node.localisation > mult_enable.get('input2' + axis)
        ctrl_node.camera > mult_enable_loc.get('input2' + axis)

    # If camera node is provided, connect its translation to the locator
    if cam:
        long_name = cmds.ls(cam, long=True)[0]
        top_node = long_name.split('|')[1]
        cam_grp = cmds.group(top_node, name='camera_offset_grp')
        cmds.connectAttr(loc_in.t.fullattr, cam_grp + '.t', f=True)

    # If a matrix node is provided, connect its worldMatrix to the decompose matrix
    if matrix_node:
        nn = dwnn.MayaNode(matrix_node)
        nn.worldMatrix > decomp.inputMatrix
        return [cls_in.tr, cls_out.tr]
    else:
        return decomp.inputMatrix.fullattr


@acceptString('nodes', 'input_vertex')
def create_localisation_in(nodes=list, input_vertex=list, ctrl=None,
                           force=False, name=None):
    """
    Creates a locator-based localisation system for transforming nodes or components.

    Args:
        nodes (list): A list of nodes to transform.
        input_vertex (list): Vertices or other components driving the localisation.
        ctrl (str, optional): Control object for the localisation attribute.
        force (bool, optional): If True, force the creation of new connections.
        name (str, optional): The name for the locator. If it exists, the function reuses it.

    Returns:
        list: A list containing the connected geometry and the locator transform.
    """
    skip = False
    if name and cmds.objExists(name):
        sh = cmds.listRelatives(name)
        if sh:
            con = cmds.listConnections(name, d=True, type='transformGeometry')
            if cmds.nodeType(sh[0]) == 'locator' and con:
                skip = True

    flag = {'force': True} if force else {}

    # Create a locator to reverse the transform matrix
    defaultname = name or 'loc_localisation'
    loc = dwnn.MayaNode(defaultname, 'locator')

    if not skip:
        # Ensure the ctrl argument is a string if provided
        if ctrl:
            if not isinstance(ctrl, str):
                t = type(ctrl)
                cmds.error(f'ctrl argument must be a string instead of : {t}')

        # If input is not a component (vertices), create a localisation rig control
        if not '.' in input_vertex:
            create_loca_rigctrl(input_vertex=input_vertex[0],
                                locator_name=loc.tr,
                                xyz=True,
                                ctrl=ctrl)

        else:
            # Convert input to vertices if necessary
            toVertices = cmds.polyListComponentConversion(input_vertex, tv=True)
            vertices = cmds.ls(toVertices, fl=True)
            nb = len(vertices)

            # Calculate the average position of the vertices
            if nb > 1:
                pos = cmds.xform(vertices, q=True, t=True)
                xyz = [sum(pos[0::3]) / nb, sum(pos[1::3]) / nb,
                       sum(pos[2::3]) / nb]
            elif nb == 1:
                xyz = cmds.pointPosition(vertices[0])

            # Create pointOnPolyConstraint based on the vertices
            ptC = create_loca_pOC(input_vertex=input_vertex,
                                  locator_name=loc.tr,
                                  xyz=xyz,
                                  ctrl=ctrl)
    else:
        loc = dwnn.MayaNode(name)

    # Prepare for connection and output as mesh
    toconnect = []
    multi = defaultdict(list)

    for x, m in enumerate(nodes):
        if '_' in m:
            name = m.split('|')[-1].rsplit('_', 1)[0]
        else:
            name = m

        # Find the shape node
        m_sh = cmds.ls(m, dag=True, ni=True, type=['mesh', 'nurbsCurve'])
        if not m_sh:
            m_sh = cmds.ls(m)

        # Get input/output attributes for connections
        attr = dwu.get_type_io(m_sh[0], multi=2)
        if '{}' in attr:
            if not multi[attr]:
                nb = cmds.listAttr(attr.format(':'))
                id = [re.findall(r'\d+', i)[-1] for i in nb]
                multi[attr] = id
            value = multi[attr][0]
            multi[attr].pop(0)
            attr = attr.format(value)

        # Create transformGeometry nodes for each mesh and connect
        tg_name = f'tgin_localisation_{x}_{name.replace(":", "_")}'
        tg_in = cmds.createNode('transformGeometry', n=tg_name)
        cmds.connectAttr(attr, f'{tg_in}.inputGeometry', **flag)
        cmds.connectAttr(f'{loc.tr}.worldInverseMatrix[0]',
                         f'{tg_in}.transform', **flag)

        out = f'{tg_in}.outputGeometry'
        toconnect.append(out)

    return [toconnect, loc.tr]


def create_loca_pOC(input_vertex=str,
                    locator_name=str,
                    xyz=tuple,
                    ctrl=None):
    """
    Creates a pointOnPolyConstraint (POC) on a locator, constrained to follow a given vertex.
    Optionally connects the translation to a control for weighted localization.

    Args:
        input_vertex (str): The polygon vertex to constrain the locator to.
        locator_name (str): The locator to follow the polygon vertex.
        xyz (tuple): Offset values for the locator in X, Y, and Z directions.
        ctrl (str, optional): Control object to add a 'localisation' attribute for adjusting the locator's position.

    Returns:
        str: The name of the pointOnPolyConstraint node.
    """
    # Ensure input_vertex and locator_name are valid
    if not cmds.objExists(input_vertex):
        raise ValueError(f"Input vertex {input_vertex} does not exist.")
    if not cmds.objExists(locator_name):
        raise ValueError(f"Locator {locator_name} does not exist.")

    # Convert input to vertices
    toVertices = cmds.polyListComponentConversion(input_vertex, tv=True)
    vertices = cmds.ls(toVertices, fl=True)

    # Create pointOnPolyConstraint
    ptC = cmds.pointOnPolyConstraint(vertices, locator_name)[0]

    # Extract UV attributes and set them manually
    sel_names = [i.split('.')[0] for i in vertices]
    pattern = re.compile('[U-V]\d$')
    attrs = cmds.listAttr(ptC)
    attrUV = ['{}.{}'.format(ptC, a) for a in attrs if pattern.search(a)]

    # Retrieve UV values for the vertices and set them on the POC node
    valueUV = chain(*[getVertexMap(i) for i in vertices])
    for attr, value in zip(attrUV, valueUV):
        cmds.setAttr(attr, value)

    # Clean default connections on locator (rotation and translation)
    con = [i for i in cmds.listConnections(ptC, p=True) if
           re.search('^(rotate|translate)[X-Z]$', i.split('.')[-1])]
    dest = [i for i in cmds.listConnections(con, p=True)]
    plugs = zip(dest, con)
    for p in plugs:
        cmds.disconnectAttr(*p)
        cmds.setAttr(p[1], 0)

    # Create multiplyDivide node for weighting localization
    mult = cmds.createNode('multiplyDivide', name='{}_weightLocalisation'.format(locator_name))
    offset = []
    if vertices:
        # Create addDoubleLinear nodes to apply the xyz offset
        for nb, axis in enumerate('XYZ'):
            addL = cmds.createNode('addDoubleLinear',
                                   name='{}_offset{}_Localisation'.format(locator_name, axis))
            cmds.setAttr('{}.input2'.format(addL), -xyz[nb])
            offset.append(addL)

    # Set up the control if provided
    if ctrl:
        if cmds.objExists(ctrl):
            attr = 'localisation'
            if not cmds.ls('{}.{}'.format(ctrl, attr)):
                cmds.addAttr(ctrl, sn=attr, dv=1, min=-1, max=1)
                cmds.setAttr('{}.{}'.format(ctrl, attr), k=True)
            for a in 'XYZ':
                cmds.connectAttr('{}.{}'.format(ctrl, attr),
                                 '{}.input2{}'.format(mult, a))

    # Connect multiplyDivide node to locator's translation
    if offset:
        for axis, off in zip('XYZ', offset):
            cmds.connectAttr('{}.constraintTranslate{}'.format(ptC, axis),
                             '{}.input1'.format(off), force=True)
            cmds.connectAttr('{}.output'.format(off),
                             '{}.input1{}'.format(mult, axis), force=True)
    else:
        cmds.connectAttr('{}.constraintTranslate'.format(ptC),
                         '{}.input1'.format(mult), force=True)

    cmds.connectAttr('{}.output'.format(mult),
                     '{}.translate'.format(locator_name), force=True)

    return ptC


def create_loca_rigctrl(input_vertex=str,
                        locator_name=str,
                        xyz=tuple,
                        ctrl=None):
    """
    Creates a rig control system where the input control drives the translation of a locator
    through a decompose matrix and multiply-divide node for weighted localization.

    Args:
        input_vertex (str): The control object whose world matrix will drive the system.
        locator_name (str): The locator whose translation will be driven.
        xyz (tuple): Optional offset values in the X, Y, and Z axes.
        ctrl (str, optional): Control object to add a 'localisation' attribute for adjusting the locator's position.

    Returns:
        bool: True if the rig control setup is successful.
    """
    # Ensure input_vertex and locator_name are valid
    if not cmds.objExists(input_vertex):
        raise ValueError(f"Input control {input_vertex} does not exist.")
    if not cmds.objExists(locator_name):
        raise ValueError(f"Locator {locator_name} does not exist.")

    # Create and connect a decompose matrix node to decompose the input control's world matrix
    decomp = dwnn.MayaNode('dm_localisation', 'decomposeMatrix')
    rig_ctrl = dwnn.MayaNode(input_vertex)

    rig_ctrl.worldMatrix[0] > decomp.inputMatrix

    # Create multiplyDivide node to handle weighted localization
    mult = dwnn.MayaNode('weightLocalisation', 'multiplyDivide')

    # Compute the offset (use xyz argument or decompose output translate)
    offset = []
    if xyz:
        for nb, axis in enumerate('XYZ'):
            addL = dwnn.MayaNode('offset{}Localisation'.format(axis),
                                 'addDoubleLinear')
            addL.input2 = -xyz[nb]
            offset.append(addL)
    else:
        xyz = decomp.outputTranslate.get()[0]  # Default to the decompose matrix output translation
        for nb, axis in enumerate('XYZ'):
            addL = dwnn.MayaNode('offset{}Localisation'.format(axis),
                                 'addDoubleLinear')
            addL.input2 = -xyz[nb]
            offset.append(addL)

    # Set up the control (if provided) to add a 'localisation' attribute for weighting
    if ctrl:
        if cmds.objExists(ctrl):
            attr = 'localisation'
            if not cmds.ls('{}.{}'.format(ctrl, attr)):
                cmds.addAttr(ctrl, sn=attr, dv=1, min=-1, max=1)
                cmds.setAttr('{}.{}'.format(ctrl, attr), k=True)
            for a in 'XYZ':
                cmds.connectAttr('{}.{}'.format(ctrl, attr),
                                 '{}.input2{}'.format(mult.tr, a))

    # Connect decompose matrix and offset to the multiplyDivide node
    if offset:
        for axis, off in zip('XYZ', offset):
            decomp.get('outputTranslate{}'.format(axis)) > off.input1
            off.output > mult.get('input1{}'.format(axis))
    else:
        decomp.outputTranslate > mult.input1

    # Connect the multiplyDivide output to the locator's translate attribute
    cmds.connectAttr('{}.output'.format(mult.tr),
                     '{}.translate'.format(locator_name), force=True)

    return True


@acceptString('nodes')
def create_localisation_out(nodes, locator, force=False):
    """
    Creates the localisation output for the given nodes, applying the transformation
    from the locator's world matrix.

    Args:
        nodes (list): List of nodes (meshes, nurbs curves) to be transformed.
        locator (str): The name of the locator whose world matrix will be applied.
        force (bool, optional): If True, force the creation of new connections.

    Returns:
        list: A list containing the connected geometries and the locator transform.
    """
    flag = {'force': True} if force else {}
    multi = defaultdict(list)
    toconnect = []

    for x, m in enumerate(nodes):
        # Process node names and retrieve their shape nodes
        if '_' in m:
            name = m.split('|')[-1].split(':')[-1].rsplit('_', 1)[0]
        else:
            name = m

        # Get the shape node (mesh, nurbs curve) of the object
        m_sh = cmds.ls(m, dag=True, ni=True, type=['mesh', 'nurbsCurve'], l=True)
        if not m_sh:
            m_sh = cmds.ls(m)

        # Get the input/output attributes for the node, handling multi-index attributes
        attr = dwu.get_type_io(m_sh[0], multi=2)
        if '{}' in attr:
            if not multi[attr]:
                nb = cmds.listAttr(attr.format(':'))
                id = [re.findall(r'\d+', i)[-1] for i in nb]
                multi[attr] = id
            value = multi[attr][0]
            multi[attr].pop(0)
            attr = attr.format(value)

        # Create a unique name for the transformGeometry node
        _name = f'tgout_localisation_{x}_{name.replace(":", "_")}'
        tg_in = cmds.createNode('transformGeometry', n=_name)

        # Connect the node's geometry to the transformGeometry node
        cmds.connectAttr(f'{attr}', f'{tg_in}.inputGeometry', **flag)
        cmds.connectAttr(f'{locator}.worldMatrix[0]', f'{tg_in}.transform', **flag)

        # Output geometry
        out = f'{tg_in}.outputGeometry'
        toconnect.append(out)

    return [toconnect, locator]
