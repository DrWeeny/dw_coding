
import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from maya import cmds, mel
from .dw_nx_mel import *
import dw_maya.dw_maya_utils as dwu


def connectChoice(attr1, attr2, selector=1, **kwargs):
    """
    Attempts to connect `attr1` to `attr2`. If `attr2` is already connected,
    it creates a `choice` node to allow both connections to be active, with
    switching controlled by the `selector`.

    Args:
        attr1 (str): The source attribute to connect.
        attr2 (str): The destination attribute.
        selector (int, optional): Controls the choice selection, default is 1.
        **kwargs: Additional arguments such as node name.

    Returns:
        str: The output attribute of the created `choice` node, if applicable.
    """
    # Extracting flags for node creation
    flags = dwu.flags(kwargs, None, 'name', 'n', key='name')

    # Check if both attributes exist
    if '.' in attr1 and '.' in attr2:
        try:
            cmds.connectAttr(attr1, attr2)
        except:
            # Handle existing connections with choice node
            plug = cmds.listConnections(attr2, p=True)[0]
            choice = cmds.createNode('choice', **flags)
            cmds.setAttr('{}.selector'.format(choice), selector)
            choiceAttr = choice + '.input'

            # Connect both the existing connection and new connection
            for a in [plug, attr1]:
                id = get_next_free_multi_index(choiceAttr)
                cmds.connectAttr(a, '{}[{}]'.format(choiceAttr, id))

            # Connect choice output to the destination
            choice_out = dwu.get_type_io(choice, j=True)
            cmds.connectAttr(choice_out, attr2, f=True)
            return choice_out
    else:
        cmds.error('You must specify two valid attributes to connect.')


def create_skipSim_ctrl(sim_rig, mesh_dic=None, defValue=1):
    """
    Creates a blend shape control that allows skipping simulations. The control
    is connected to the provided meshes through blend shapes.

    Args:
        sim_rig (str): The name of the simulation rig.
        mesh_dic (dict, optional): A dictionary of mesh mappings where keys are
                                   target meshes and values are input meshes.
                                   Default is {'target': 'input'}.
        defValue (int, optional): The default value for the blend shape weight.

    Returns:
        list: A list of created blend shape nodes.
    """
    if not mesh_dic:
        mesh_dic = {'target': 'input'}

    rig_pref_p = '{}_ctrl_crv'
    asset = cmds.listRelatives(sim_rig, p=True)[0]
    rig_pref = rig_pref_p.format(asset.replace('_grp', ''))

    bsList = []
    for k, v in mesh_dic.items():
        try:
            # Create blend shape and connect
            bs = cmds.blendShape(v, k, en=defValue, tc=1, o='world', w=(0, 1),
                                 n='bs_{}_skipSim'.format(v))[0]
            bsList.append(bs)
        except:
            cmds.warning(
                '"{}" can\'t blendshape to "{}" due to different topology.'.format(v, k))

    attr = "skipSim{}".format(sim_rig.replace('_grp', ''))

    # If the attribute doesn't exist, create it
    if not cmds.objExists('{}.{}'.format(rig_pref, attr)):
        cmds.addAttr(rig_pref, ln=attr, at='double', dv=defValue)
        cmds.setAttr('{}.{}'.format(rig_pref, attr), e=1, keyable=1)

    # Connect blend shapes to the control attribute
    for b in bsList:
        cmds.connectAttr('{}.{}'.format(rig_pref, attr), '{}.en'.format(b))

    return bsList


def create_choice_ctrl(sim_rig, name, nodes, value=1, **kwargs):
    """
    Creates a control to manage a `choice` node, connecting the control to the
    provided nodes. This allows selection between different inputs.

    Args:
        sim_rig (str): The name of the simulation rig.
        name (str): The name of the control attribute to be created.
        nodes (list): List of nodes to connect to the `choice` node.
        value (int, optional): The default value of the control attribute.
        **kwargs: Additional flags for attribute creation.

    Returns:
        None
    """
    rig_pref_p = '{}_ctrl_crv'
    asset = cmds.listRelatives(sim_rig, p=True)[0]
    rig_pref = rig_pref_p.format(asset.replace('_grp', ''))

    attr = "{}{}".format(sim_rig.replace('_grp', ''), name)

    # If the control attribute doesn't exist, create it
    if not cmds.objExists('{}.{}'.format(rig_pref, attr)):
        cmds.addAttr(rig_pref, ln=attr, at='long', dv=value, **kwargs)
        cmds.setAttr('{}.{}'.format(rig_pref, attr), e=1, keyable=1)

    # Connect the control attribute to each node's selector
    for n in nodes:
        cmds.connectAttr('{}.{}'.format(rig_pref, attr),
                         '{}.selector'.format(n))


def create_namelinkInOut(sim_rig, nomenclature=None):
    """
    Creates a mapping of related objects between the 'presim' and 'postsim' groups based on naming conventions.

    Args:
        sim_rig (str): The parent group containing presim and postsim subgroups.
        nomenclature (list, optional): A list of naming conventions for matching objects.
                                       Defaults to [['_presim_msh', '_postsim_msh']].

    Returns:
        dict: A dictionary where keys are objects from the 'postsim' group and values are the corresponding objects from the 'presim' group.
    """
    # Default nomenclature for matching presim and postsim objects
    if nomenclature is None:
        nomenclature = [['_presim_msh', '_postsim_msh']]

    # Get the subgroups in sim_rig that start with 'presim' and 'postsim'
    grps = cmds.listRelatives(sim_rig, type='transform')
    presim = [i for i in grps if i.startswith('presim')]
    postsim = [i for i in grps if i.startswith('postsim')]

    # List all the mesh and nurbsCurve parent transforms in both presim and postsim
    _in = cmds.listRelatives(
        cmds.ls(presim, dag=True, type=['mesh', 'nurbsCurve']), p=True)
    _in = list(set(_in))  # Remove duplicates
    _out = cmds.listRelatives(
        cmds.ls(postsim, dag=True, type=['mesh', 'nurbsCurve']), p=True)
    _out = list(set(_out))  # Remove duplicates

    _in_check, _out_check = [], []
    out = {}

    # Iterate over all nomenclature pairs and match based on name replacement
    for nom in nomenclature:
        # Collect matching presim and postsim objects based on naming convention
        _in_check += [i for i in _in if i.replace(*nom) in _out]
        _out_check += [i for i in _out if i.replace(*nom[::-1]) in _in]

        # Map matching objects from _out to _in
        for o in _out_check:
            matching_in = [i for i in _in_check if i.replace(*nom) == o]
            if matching_in:
                out[o] = matching_in[0]

    return out
