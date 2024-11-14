import sys, os
from math import sqrt

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from maya import cmds, mel
from .dw_nx_mel import *
from dw_maya.dw_decorators import acceptString
from .dw_create_nucleus import create_nucleus
from. dw_add_active_to_nsystem import add_active_to_nsystem


import re
import maya.cmds as cmds
import maya.mel as mel
from math import sqrt
from typing import List, Optional


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
        **kwargs: Additional arguments like `name`, `parent`, etc.

    Returns:
        list: A list of newly created nCloth nodes.

    Raises:
        RuntimeError: If no valid meshes are selected for nCloth creation.
    """

    # Set default cloth creation flags
    cloth_flags = {}
    cloth_name = kwargs.get('name') or kwargs.get('n') or 'nCloth1'
    cloth_flags['parent'] = kwargs.get('parent') or kwargs.get('p')

    pattern = cloth_name if '{' in cloth_name and '}' in cloth_name else None

    # Find mesh shapes
    meshes = cmds.listRelatives(meshes, f=True, ni=True, s=True, type="mesh")

    if not meshes:
        cmds.error("No mesh selected for nCloth creation.")

    # Create or use existing nucleus node
    nucleus = nucleus_node or create_nucleus()

    _iter = 0
    regex = re.compile('_ncloth', re.IGNORECASE)

    out_mesh_name = "outputCloth#"
    if '_' in cloth_name and not regex.search(cloth_name):
        part = cloth_name.split('_')[0]
        out_mesh_name = f"{part}_outputcloth_mshShape"
    else:
        out_mesh_name = regex.sub('_outputcloth_mshShape', cloth_name)

    new_cloth_nodes = []

    for mesh in meshes:
        # Skip meshes already connected to nBase nodes
        conns = cmds.listConnections(mesh, sh=True, type="nBase") or []
        if conns:
            continue

        # Get the mesh transform
        mesh_tform = cmds.listRelatives(mesh, p=True, path=True)[0]

        # Create nCloth node
        ncloth = cmds.createNode("nCloth", **cloth_flags)
        ncloth_tr = cmds.listRelatives(ncloth, p=True)[0]

        if pattern:
            id = re.findall(r'\d+', mesh_tform)
            _iter = int(id[-1]) if id else _iter + 1
            tmp_name = pattern.format(_iter)
            cloth_name = regex.sub('_outputcloth_mshShape', tmp_name) if regex.search(
                tmp_name) else f"{tmp_name}_ncloth"
            out_mesh_name = regex.sub('_outputcloth_mshShape', tmp_name)

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

    if cmds.about(batch=True):
        for cloth in new_cloth_nodes:
            cmds.getAttr(f"{cloth}.forceDynamics")

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