import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
from dw_maya.dw_create import pointOnPolyConstraint
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_duplication as dwdup


def create_curve_ctrl(asset_name=None, attach=None):
    """
    Create a 'cfx' control curve for a rig.

    Args:
        asset_name (str): Name of the asset. Defaults to None.
        attach (str): Vertex number of an object to attach the curve. Defaults to None.

    Returns:
        str: The name of the control curve.
    """
    base = 'cfx_ctrl_crv'
    name = f'{asset_name}_cfx_ctrl_crv' if asset_name else base

    if not cmds.objExists(name):
        path = os.path.join(rdPath, '.files', 'cfx_ctrl_crv.abc')
        print(f"Importing Alembic file from: {path}")
        cmds.AbcImport(path)

        if asset_name:
            cmds.rename(base, name)

        if attach:
            pointOnPolyConstraint(input_vertex=attach, tr=None, name=name, replace=True)

    return name


def create_group(name, parent=None, mset=True):
    """
    Create a group in Maya and optionally a Maya set for the rig.

    Args:
        name (str): The name of the group. Should end with '_grp'.
        parent (str): Optional parent for the group.
        mset (bool): Whether to create a Maya set associated with the group. Defaults to True.

    Returns:
        str or list: The name of the group, or [group, set] if a set is created.
    """
    if not name.lower().endswith('_grp'):
        cmds.error('Group names should end with "_grp" or "_GRP".')

    maya_kwargs = {'parent': parent} if parent else {}

    if not cmds.objExists(name):
        grp = cmds.group(name=name, empty=True, **maya_kwargs)
        if mset:
            set_name = name.rsplit('_', 1)[0] + '_set'
            mset = cmds.sets(name=set_name, empty=True)

            if parent:
                parent_set = parent.rsplit('_', 1)[0] + '_set'
                cmds.sets(mset, edit=True, forceElement=parent_set)

            return [grp, mset]
        return grp
    else:
        cmds.warning(f"Group '{name}' already exists.")
        return name


def create_hierarchy(asset='characterName', rigname='rigName'):
    """
    Create a default simulation hierarchy for a given asset and rig.

    Args:
        asset (str): The name of the asset. Defaults to 'longlclaw'.
        rigname (str): The name of the simulation rig. Defaults to 'wings'.

    Returns:
        list: List of group names created for the hierarchy.
    """
    output = []

    # Create the top group for the asset
    grp_asset = create_group(f'{asset}_cfx_grp')
    if not isinstance(grp_asset, (list, tuple)):
        grp_asset = [grp_asset]
    output.append(grp_asset)

    # Create the simulation rig group
    grp_rig = create_group(f'{rigname}_sim_grp', parent=grp_asset[0])
    if not isinstance(grp_rig, (list, tuple)):
        grp_rig = [grp_rig]
    output.append(grp_rig)

    # Create additional groups with specific visibility settings
    grps = ['presim', 'utils', 'collider', 'sim', 'postsim', 'exp']
    visibilities = [0, 0, 1, 1, 0, 0]

    for grp_name, visibility in zip(grps, visibilities):
        full_name = f'{grp_name}_{rigname}_grp'
        created_grp = create_group(full_name, parent=grp_rig[0])
        cmds.setAttr(f'{created_grp}.visibility', visibility)
        output.append(created_grp)

    return output


def add_to_group(obj, name):
    """
    Add objects to a group and optionally a Maya set.

    Args:
        obj (list): List of object names to be added.
        name (str): Name of the group or set.

    """
    if name.lower().endswith('_grp'):
        grp = name
        mset = name.rsplit('_', 1)[0] + '_set'
        if cmds.objExists(grp):
            cmds.parent(obj, grp)
        if cmds.objExists(mset):
            cmds.sets(obj, add=mset)
    elif name.lower().endswith('_set'):
        mset = name
        grp_base = name.rsplit('_', 1)[0]
        grp = next((grp_base + suffix for suffix in ['_grp', '_GRP'] if cmds.objExists(grp_base + suffix)), None)

        if grp:
            cmds.parent(obj, grp)
        if cmds.objExists(mset):
            cmds.sets(obj, add=mset)


def build_sim_step(step_name: str, step_ind: int, obj: list,
                   insert: bool = False, parent: str = None, connection: bool = True) -> list:
    """Create outmeshes for a whole group of meshes with optional parenting and connection.

    Args:
        step_name (str): Name of the simulation step, e.g., 'presim'.
        step_ind (int): Index in the object's name where the step name should be inserted/replaced.
        obj (list): List of object names (usually transforms).
        insert (bool, optional): Whether to insert the step name at the step index instead of replacing it. Defaults to False.
        parent (str, optional): Name of the parent to group the new objects under. Defaults to None.
        connection (bool, optional): If True, connects original and duplicated objects. Defaults to True.

    Returns:
        list: List of newly created nodes.
    """
    created_objects = []

    for o in obj:
        try:
            # Get the shape node
            shape_node = cmds.ls(o, dag=True, type='shape')[0]

            # Skip objects already linked to a reference object
            connections = cmds.listConnections(shape_node + '.message')
            if connections:
                if any('.referenceObject' in conn for conn in connections):
                    continue

            # Split the name, modify for step naming
            name_parts = o.split(':')[-1].split('|')[-1].split('_')
            if insert:
                name_parts.insert(step_ind, step_name)
            else:
                name_parts[step_ind] = step_name

            new_transform_name = '_'.join(name_parts)
            new_shape_name = new_transform_name + 'Shape'

            # Duplicate the object
            node_type = cmds.nodeType(shape_node)
            if node_type == 'mesh':
                # Duplicate using outmesh logic for mesh types
                duplicated_object = dwdup.outmesh([o], fresh=False)
                duplicated_object = cmds.rename(duplicated_object[0], new_transform_name)
            else:
                # Standard duplicate for non-mesh types
                duplicated_object = cmds.duplicate(o, name=new_transform_name)[0]

            # Rename the shape node accordingly
            new_shape_node = cmds.listRelatives(duplicated_object, ni=True, type='shape')[0]
            cmds.rename(new_shape_node, new_shape_name)

            # Parent the new object if required
            if parent:
                cmds.parent(duplicated_object, parent)

            # Connect the shapes if required
            if connection:
                orig_shape = cmds.ls(o, dag=True, type='shape')[0]
                new_shape = cmds.ls(duplicated_object, dag=True, type='shape')[0]

                source_plug = dwu.get_type_io(orig_shape, io=1)
                target_plug = dwu.get_type_io(new_shape, io=0)

                if not cmds.listConnections(target_plug):
                    cmds.connectAttr(source_plug, target_plug)

            created_objects.append(duplicated_object)

        except Exception as e:
            cmds.warning(f"Failed to process object {o}: {str(e)}")
            continue

    return created_objects
