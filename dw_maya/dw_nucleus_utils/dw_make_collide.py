import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)
from math import sqrt
from maya import cmds, mel
from .dw_nx_mel import *
import dw_maya.dw_maya_utils as dwu
from dw_maya.dw_decorators import acceptString
import dw_maya.dw_duplication as dwdup
import dw_maya.dw_deformers as dwdef
from .dw_create_nucleus import create_nucleus


def make_collide_ncloth(sel_mesh: str, nucleus: str = None, **kwargs) -> list:
    """
    Sets up selected meshes as passive colliders in a nucleus simulation.

    Args:
        sel_mesh (str): The selected mesh that will act as a passive collider.
        nucleus (str): The name of the nucleus node to use for the simulation. If not provided, a new one will be created.
        **kwargs: Additional arguments:
            - name (str): Custom name for the nRigid node.
            - preset (int): Collider preset to use, defaults to 2.
            - thickness (float): Custom thickness for the collider.

    Returns:
        list: List of new nRigid nodes created.

    Raises:
        RuntimeError: If no valid meshes are provided.
    """

    # Unpacking kwargs with default values
    name = kwargs.get('name')
    preset = kwargs.get('preset', 2)
    thickness = kwargs.get('thickness')

    # Get the list of selected meshes
    meshes = cmds.ls(sel_mesh, ni=True, dag=True, type="mesh")
    if not meshes:
        cmds.error("Please specify a valid mesh.")

    # Create or retrieve the nucleus
    nucleus = create_nucleus(nucleus)

    input_meshes = []

    for mesh in meshes:
        # Check if the mesh is connected to an nCloth
        nBase = find_type_in_history(mesh, "nCloth", future=0, past=1)
        if not nBase:
            input_meshes.append(mesh)

    if not input_meshes:
        cmds.error("Nothing to make passive collider.")

    new_rigid_nodes = []

    for mesh in input_meshes:
        # Check if the mesh is already an nRigid
        nBase = find_type_in_history(mesh, "nRigid", future=1, past=0)
        create_n_rigid = True

        if nBase:
            acN = cmds.listConnections(f"{nBase}.currentState")
            if acN and acN[0] == nucleus:
                nRigid = nBase
                collide = cmds.getAttr(f"{nRigid}.collide")
                if collide:
                    cmds.warning(f"{mesh} already collides in nucleus {nucleus}")
                else:
                    cmds.setAttr(f"{nRigid}.collide", True)
                    create_n_rigid = False

        # Create nRigid if necessary
        if create_n_rigid:
            tform = cmds.listRelatives(mesh, p=True, path=True)[0]
            nRigid = cmds.createNode('nRigid', parent=tform)

            if name:
                nRigid_tr = cmds.rename(tform, name)
                nRigid = cmds.listRelatives(nRigid_tr, type='nRigid')[0]

            new_rigid_nodes.append(nRigid)

            # Set initial nRigid properties
            mel.eval(f'hideParticleAttrs("{nRigid}");')
            cmds.setAttr(f"{nRigid}.selfCollide", False)
            cmds.connectAttr("time1.outTime", f"{nRigid}.currentTime")
            cmds.connectAttr(f"{mesh}.worldMesh", f"{nRigid}.inputMesh")
            add_passive_to_nsystem(nRigid, nucleus)
            cmds.connectAttr(f"{nucleus}.startFrame", f"{nRigid}.startFrame")

        cmds.setAttr(f"{mesh}.quadSplit", 0)

        # Calculate thickness if not provided
        if not thickness:
            bbox = cmds.exactWorldBoundingBox(mesh)
            x, y, z = (bbox[3] - bbox[0]), (bbox[4] - bbox[1]), (bbox[5] - bbox[2])
            bbox_surface_area = 2 * ((x * y) + (x * z) + (y * z))
            num_faces = cmds.polyEvaluate(mesh, face=True)
            max_ratio = 0.003
            min_width = 0.0001
            obj_size = sqrt(bbox_surface_area)
            new_width = obj_size * max_ratio

            if num_faces > 0:
                estimated_edge_length = sqrt(bbox_surface_area / num_faces)
                thickness = 0.13 * estimated_edge_length
                if thickness < new_width:
                    new_width = thickness

            if new_width < min_width:
                new_width = min_width
        else:
            new_width = thickness

        cmds.setAttr(f"{nRigid}.thickness", new_width)

        if preset == 1:
            new_width *= 4

        # Apply collider preset
        set_collider_preset(nRigid, preset, new_width)

    # Force update of the nucleus node to reset the collide objects if start frame is changed
    cmds.getAttr(f"{nucleus}.forceDynamics")
    cmds.select(clear=True)

    return new_rigid_nodes


def add_passive_to_nsystem(passive: str, nucleus: str) -> int:
    """
    Adds a passive nObject to a nucleus simulation.

    Args:
        passive (str): Name of the passive nObject.
        nucleus (str): Name of the nucleus node.

    Returns:
        int: The index where the passive object was connected.
    """
    # Define the attribute names for inputPassive and inputPassiveStart
    attr = f"{nucleus}.inputPassive"
    start_attr = f"{nucleus}.inputPassiveStart"

    # Get the next available index for the multi-attribute
    n_index = get_next_free_multi_index(attr)

    # Connect the passive object's currentState and startState to the nucleus attributes
    cmds.connectAttr(f"{passive}.currentState", f"{attr}[{n_index}]")
    cmds.connectAttr(f"{passive}.startState", f"{start_attr}[{n_index}]")

    # Set the passive object's active attribute to 0 (indicating it's passive)
    cmds.setAttr(f"{passive}.active", 0)

    # Return the index where the passive object was connected
    return n_index


@acceptString('rigid')
def set_collider_preset(rigid=list, preset=2, thickness=.01):
    """ Three different presets for nRigid

    Args:
        rigid (list): nodes
        preset (int): between 0-2 corresponding to "driver pushout and collide"
        thickness (float):

    Returns:

    """

    order_sel = ['driver', 'pushout', 'collide']

    # Preset 2
    mypresets = {}
    attrs = {'collide': 1, 'collideStrength': 1, 'thickness': thickness,
             'friction': 0.3, 'trappedCheck': 1, 'pushOut': 0,
             'pushOutRadius': 0}
    mypresets['collide'] = attrs

    # Preset 1
    attrs = {'collide': 0, 'collideStrength': 1, 'thickness': 0.01,
             'friction': 0.3, 'trappedCheck': 0,
             'pushOut': thickness, 'pushOutRadius': thickness}
    mypresets['pushout'] = attrs

    # Preset 0
    attrs = {'collide': 0, 'collideStrength': 0, 'thickness': 0.0,
             'friction': 0.0, 'trappedCheck': 0, 'pushOut': 0,
             'pushOutRadius': 0}
    mypresets['driver'] = attrs

    sel = cmds.ls(rigid, dag=True, type='nRigid')
    if len(sel) == 0:
        cmds.error('No Rigids in Selection')
    for i in sel:
        for a, v in mypresets[order_sel[preset]].iteritems():
            cmds.setAttr('{}.{}'.format(i, a), v)


def combine_wrap(name: str,
                 driven: str,
                 drivers: list = None,
                 filter: list = None,
                 exception: list = None,
                 parent: str = None,
                 out_poly_unite: bool = False) -> str:
    """
    Create an outmesh from the provided drivers, combine them, and wrap the driven mesh to the combined geometry.

    Args:
        name (str): The base name for the combined geometry and group.
        driven (str): The driven mesh that will be wrapped to the combined geometry.
        drivers (list): A list of driver meshes to combine.
        filter (list): A list of string filters to selectively choose drivers based on their names.
        exception (list): A list of meshes to exclude from the combination.
        parent (str): The parent node to attach the combined group to.
        out_poly_unite (bool): Whether to return the polyUnite node instead of the combined mesh.
    Notes:
        Used to create a collider from two separated meshes
    Returns:
        str: The name of the combined mesh or polyUnite node.
    """
    sel = []

    # Filter the drivers based on the provided filter
    if drivers:
        geos = cmds.ls(drivers, dag=True, type='mesh', ni=True)
        if filter:
            for f in filter:
                sel.extend([g for g in geos if g.endswith(f)])
        else:
            sel.extend(geos)

    # Get the transform nodes of the selected meshes
    sel_tr = [cmds.listRelatives(mesh, p=True)[0] for mesh in sel]

    # Exclude any meshes in the exception list
    if exception:
        sel_tr = list(set(sel_tr) - set(exception))

    # Create duplicates of the selected meshes
    dups = [dwdup.outmesh(tr)[0] for tr in sel_tr]

    # Combine the duplicated meshes
    comb_geos = cmds.polyUnite(dups, ch=True, mergeUVSets=True, centerPivot=True, name=name)

    # Wrap the driven mesh to the combined geometry
    frm_name = '_'.join(name.split('_')[:-1])
    if driven:
        wrp_base = dwdef.createWrap(driven, comb_geos[0], exclusiveBind=False, n=f'wrp_{frm_name}')

    # Create a group for organization and parent the duplicated and combined meshes
    grp_name = cmds.group(em=True, n=f'combine_{frm_name}_grp')
    cmds.parent(dups, grp_name)
    cmds.parent(comb_geos[0], grp_name)
    if driven:
        cmds.parent(wrp_base[1], grp_name)
    if parent:
        cmds.parent(grp_name, parent)

    # Return either the combined mesh or the polyUnite node, based on the out_poly_unite flag
    if not out_poly_unite:
        return comb_geos[0]
    else:
        hist = cmds.listHistory(comb_geos[0], f=False)
        poly_unite = next((h for h in hist if cmds.nodeType(h) == 'polyUnite'), None)
        if poly_unite:
            grp_part_name = cmds.listConnections(comb_geos[0] + '.inMesh')
            grp_part_in = cmds.listConnections(grp_part_name[0] + '.output', p=True)
            cmds.disconnectAttr(grp_part_name[0] + '.output', grp_part_in[0])
            new_name = cmds.rename(poly_unite, comb_geos[0].replace('_msh', '_polyunite'))
            cmds.delete(comb_geos[0])
            return new_name
        return comb_geos[0]
