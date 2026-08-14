import re
from math import sqrt
from typing import List, Optional, Union

from maya import cmds, mel
from .dw_nx_mel import *
from dw_maya.dw_decorators import acceptString
from .dw_create_nucleus import create_nucleus
from .dw_add_active_to_nsystem import add_active_to_nsystem
from . import _naming_convention


def resolve_cloth_names(meshes: List[str],
                        name: Union[str, List[str]] = None) -> dict:
    """
    Pair every mesh with the names its nCloth and output mesh should take.

    Args:
        meshes (list): Mesh shapes, in the order returned by Maya.
        name: Naming request.
            - None: derive from each mesh through the active naming
              convention (`body_msh` gives `body_ncloth` and
              `body_outputcloth_mshShape`).
            - str with `{}`: format pattern, fed the trailing number of the
              mesh name when it has one, else a 1-based counter.
            - str: used as-is for a single mesh, suffixed with the 1-based
              index when several meshes are given.
            - list: one name per mesh, must match `len(meshes)`.

    Returns:
        dict: {mesh: (cloth name, output mesh name)}. Keyed by mesh so that
            skipping an already-simulated mesh cannot shift the pairing.

    Raises:
        RuntimeError: If a name list does not match the mesh count.
    """
    naming = _naming_convention.get_naming()

    if name is None:
        return {mesh: (naming.name(mesh, 'ncloth'),
                       naming.name(mesh, 'output', shape=True))
                for mesh in meshes}

    if isinstance(name, (list, tuple)):
        if len(name) != len(meshes):
            cmds.error(f"Got {len(name)} names for {len(meshes)} meshes: "
                       f"{list(meshes)}")
        requested = list(name)
    elif '{' in name and '}' in name:
        requested = []
        counter = 0
        for mesh in meshes:
            digits = re.findall(r'\d+', mesh.split('|')[-1])
            counter = int(digits[-1]) if digits else counter + 1
            requested.append(name.format(counter))
    elif len(meshes) == 1:
        requested = [name]
    else:
        requested = [f"{name}{i}" for i in range(1, len(meshes) + 1)]

    # An explicit name is the cloth name; the output mesh is derived from
    # it, so the pair stays consistent whatever the caller asked for
    out = {}
    for mesh, cloth_name in zip(meshes, requested):
        out[mesh] = (cloth_name,
                     naming.name(cloth_name, 'output', shape=True))
    return out


def create_ncloth(meshes: List[str],
                  nucleus_node: Optional[str] = None,
                  world_space: int = 0,
                  **kwargs) -> List[str]:
    """
    Description:
    Given a selected list of meshes, converts them to nCloth by creating an nCloth node
    and an output mesh for each. The resulting nCloth nodes are left selected.

    Args:
        meshes (list): A list of mesh transforms to convert to nCloth.
        nucleus_node (str, optional): The name of the nucleus node to connect the nCloth nodes to.
        world_space (int): If 1, the output mesh will be created in world space.
        **kwargs: Additional arguments:
            - name (str or list): Custom name(s) for the nCloth node(s).
              Defaults to a name derived from each mesh. See
              `resolve_cloth_names` for the str/pattern/list forms.
            - parent (str): Parent for the created nCloth node.
            - full_output (bool): Return one dict per cloth instead of the
              bare nCloth shapes (see Returns).

    Returns:
        list: The newly created nCloth shapes. With `full_output=True`, a
            list of {'ncloth', 'transform', 'output_mesh', 'input_mesh'}
            dicts instead: the output mesh is otherwise unreachable without
            walking `ncloth.outputMesh` by hand.

    Raises:
        RuntimeError: If no valid meshes are selected for nCloth creation.

    Example:
        >>> create_ncloth(['tissus_sim_msh'])
        ['tissus_sim_nclothShape']
    """

    # Set default cloth creation flags
    cloth_flags = {}
    name = kwargs.get('name') or kwargs.get('n')
    cloth_flags['parent'] = kwargs.get('parent') or kwargs.get('p')
    full_output = kwargs.get('full_output', False)

    # Find mesh shapes
    meshes = cmds.listRelatives(meshes, f=True, ni=True, s=True, type="mesh")

    if not meshes:
        cmds.error("No mesh selected for nCloth creation.")

    # Names are resolved against the full mesh list, before the already
    # simulated meshes are skipped below, so a skip cannot shift the pairing
    cloth_names = resolve_cloth_names(meshes, name)

    # Create or use existing nucleus node
    nucleus = nucleus_node or create_nucleus()

    new_cloth_nodes = []
    detailed = []

    for mesh in meshes:
        # Skip meshes already connected to nBase nodes
        conns = cmds.listConnections(mesh, sh=True, type="nBase") or []
        if conns:
            cmds.warning(f"Already driven by {conns[0]}, skipped: {mesh}")
            continue

        cloth_name, out_mesh_name = cloth_names[mesh]

        # Get the mesh transform
        mesh_tform = cmds.listRelatives(mesh, p=True, path=True)[0]

        # Create nCloth node
        ncloth = cmds.createNode("nCloth", **cloth_flags)
        ncloth_tr = cmds.listRelatives(ncloth, p=True)[0]

        ncloth_tr = cmds.rename(ncloth_tr, cloth_name)
        ncloth = cmds.listRelatives(ncloth_tr, type='nCloth')[0]

        mel.eval(f'hideParticleAttrs("{ncloth}");')
        new_cloth_nodes.append(ncloth)

        # Connect attributes
        cmds.connectAttr("time1.outTime", f"{ncloth}.currentTime")
        cmds.connectAttr(f"{mesh}.worldMesh", f"{ncloth}.inputMesh")

        # Create output mesh
        out_mesh = ""
        if not world_space:
            out_mesh = cmds.createNode("mesh", parent=mesh_tform, name=out_mesh_name)
            cmds.setAttr(f"{ncloth}.localSpaceOutput", True)
        else:
            out_mesh = cmds.createNode("mesh", name=out_mesh_name)

        # Transfer shading connections
        _apply_shading(mesh, out_mesh)

        # Set up attributes
        cmds.setAttr(f"{out_mesh}.quadSplit", 0)
        cmds.connectAttr(f"{ncloth}.outputMesh", f"{out_mesh}.inMesh")
        add_active_to_nsystem(ncloth, nucleus)
        cmds.connectAttr(f"{nucleus}.startFrame", f"{ncloth}.startFrame")
        cmds.setAttr(f"{mesh}.intermediateObject", 1)

        # Lock transform attributes
        cloth_tforms = cmds.listRelatives(ncloth, p=True, path=True)
        cmds.setAttr(f"{cloth_tforms[0]}.translate", lock=True)
        cmds.setAttr(f"{cloth_tforms[0]}.rotate", lock=True)
        cmds.setAttr(f"{cloth_tforms[0]}.scale", lock=True)

        # Calculate thickness
        _set_ncloth_attributes(ncloth, mesh)

        detailed.append({'ncloth': ncloth,
                         'transform': cloth_tforms[0],
                         'output_mesh': out_mesh,
                         'input_mesh': mesh})

    if cmds.about(batch=True):
        for cloth in new_cloth_nodes:
            cmds.getAttr(f"{cloth}.forceDynamics")

    if full_output:
        return detailed

    return new_cloth_nodes


def _apply_shading(original_mesh: str, out_mesh: str):
    """
    Transfers shading from the original mesh to the nCloth output mesh.

    Args:
        original_mesh (str): Name of the original mesh.
        out_mesh (str): Name of the output mesh.
    """
    shading_groups = cmds.listConnections(f"{original_mesh}.instObjGroups[0]", d=True, sh=True, type="shadingEngine")
    if shading_groups:
        cmds.sets(out_mesh, e=True, forceElement=shading_groups[0])
    else:
        cmds.sets(out_mesh, e=True, forceElement="initialShadingGroup")


def _set_ncloth_attributes(ncloth: str, mesh: str):
    """
    Sets key attributes for the nCloth node based on the mesh's properties.

    Args:
        ncloth (str): Name of the nCloth node.
        mesh (str): Original mesh node.
    """
    bbox = cmds.exactWorldBoundingBox(mesh)
    x, y, z = bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2]
    bbox_surface_area = 2 * ((x * y) + (x * z) + (y * z))
    num_faces = cmds.polyEvaluate(mesh, face=True)
    max_ratio = 0.005
    min_width = 0.0001
    obj_size = sqrt(bbox_surface_area)
    new_width = obj_size * max_ratio
    if num_faces > 0:
        estimated_edge_length = sqrt(bbox_surface_area / num_faces)
        thickness = 0.13 * estimated_edge_length
        if thickness > new_width:
            cmds.setAttr(f"{ncloth}.selfCollisionFlag", 3)  # vertex face
        else:
            new_width = thickness
            cmds.setAttr(f"{ncloth}.selfCollideWidthScale", 1)

    new_width = max(new_width, min_width)
    cmds.setAttr(f"{ncloth}.thickness", new_width)
    cmds.setAttr(f"{ncloth}.pushOutRadius", new_width * 4.0)