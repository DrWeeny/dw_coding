import maya.cmds as cmds

def dup_abc():
    """
    Duplicates an Alembic cached object by importing the Alembic file associated with the selected mesh
    and renames the newly imported meshes with an '_abc_v1' suffix.

    :return: List of newly imported meshes
    """

    # Get the selected mesh shapes
    shape = cmds.ls(sl=True, dag=True, type="mesh")

    # Retrieve the AlembicNode from the selected object's history
    abc_nodes = [i for i in cmds.listHistory(shape) if cmds.nodeType(i) == 'AlembicNode']

    if not abc_nodes:
        cmds.error("No AlembicNode found in the history of the selected object.")
        return

    # Get the file path of the Alembic cache from the AlembicNode
    cache_path = cmds.getAttr(f'{abc_nodes[0]}.abc_File')

    # List all current nodes in the scene before import
    existing_nodes = set(cmds.ls())

    # Import the Alembic cache into the scene
    cmds.AbcImport(cache_path, mode='import')

    # Determine which new nodes were added to the scene
    imported_meshes = set(cmds.ls()) - existing_nodes

    # Generate unique names for the imported meshes with '_abc_v1' pattern
    for mesh in imported_meshes:
        if cmds.objExists(mesh):
            new_name = f'{mesh}_abc_v1'
            cmds.rename(mesh, new_name)

    return list(imported_meshes)