import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from maya import cmds, mel

def attach_nobject_to_hair(hsys: str, mesh: str, collide: int) -> str:
    """Attach a mesh to a hair system or make it collide as an nRigid/nCloth.

    Args:
        hsys (str): Hair system node.
        mesh (str): Mesh to attach.
        collide (int): Whether to make the mesh a colliding object (1 for true, 0 for false).

    Returns:
        str: The name of the created or connected nObject, or an empty string on failure.
    """
    if not mesh or cmds.nodeType(mesh) != "mesh":
        if collide:
            cmds.warning(f"{mesh} is not a valid mesh to collide.")
        return ""

    nobject = _get_existing_nobject(mesh)
    if nobject:
        if cmds.nodeType(nobject) == "nCloth":
            _connect_start_mesh_to_cloth(nobject, mesh)
    elif collide:
        nobject = _create_nRigid_for_collide(hsys, mesh)

    if nobject:
        _connect_nobject_to_hairsystem(hsys, nobject)

    return nobject or ""


def _get_existing_nobject(mesh: str) -> str:
    """Check if the mesh is already connected to an nBase or nCloth.

    Args:
        mesh (str): Mesh node name.

    Returns:
        str: The name of the existing nObject or an empty string.
    """
    nobject = ""
    objs = cmds.listConnections(mesh + ".worldMesh[0]", type='nBase', sh=1)
    if objs:
        nobject = objs[0]
    else:
        objs = cmds.listConnections(mesh + ".inMesh", type='nCloth', sh=1)
        if objs:
            nobject = objs[0]
    return nobject


def _connect_start_mesh_to_cloth(ncloth: str, mesh: str):
    """Connect the start mesh to the cloth node.

    Args:
        ncloth (str): nCloth node name.
        mesh (str): Mesh node name.
    """
    attr = ncloth + ".outputStartMesh"
    objs = cmds.listConnections(attr, type='mesh', sh=1)

    if objs:
        start_mesh = objs[0]
    else:
        tform = cmds.listRelatives(mesh, parent=True)[0]
        start_mesh_name = "outputStartCloth#"
        worldspace = cmds.getAttr(ncloth + ".localSpaceOutput")

        start_mesh = cmds.createNode('mesh', parent=tform if worldspace else None, name=start_mesh_name)
        cmds.connectAttr(ncloth + ".outputStartMesh", start_mesh + ".inMesh")
        cmds.setAttr(start_mesh + ".intermediateObject", True)

    if start_mesh and start_mesh != mesh:
        cmds.select(mesh, r=True)
        cmds.select(start_mesh, add=True)
        mel.eval('transplantHair 1 0;')


def _create_nRigid_for_collide(hsys: str, mesh: str) -> str:
    """Create an nRigid object for collision.

    Args:
        hsys (str): Hair system node.
        mesh (str): Mesh node to collide.

    Returns:
        str: Name of the created nObject.
    """
    nucleus = cmds.listConnections(hsys, type='nucleus')
    if nucleus:
        rigids = makeCollideNCloth(mesh, nucleus[0])
        if rigids:
            nobject = rigids[0]
            cmds.setAttr(nobject + ".collide", False)
            return nobject
    return ""


def _connect_nobject_to_hairsystem(hsys: str, nobject: str):
    """Connect an nObject to the hair system.

    Args:
        hsys (str): Hair system node.
        nobject (str): The nObject to attach.
    """
    if not cmds.listConnections(nobject + ".nucleusId", source=True):
        cmds.connectAttr(nobject + ".nucleusId", hsys + ".attachObjectId")
