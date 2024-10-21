import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from maya import cmds, mel


def extractFaces(selectedFaces, toPartsMesh):
    """
    Extracts the specified faces from a mesh and separates them into new mesh objects.

    Args:
        selectedFaces (list): List of face components to extract (e.g., ["mesh.f[0:5]"]).
        toPartsMesh (str): The name of the mesh object that will be separated into parts.

    Returns:
        list: List of the new mesh objects created from the extracted faces.
    """
    if not selectedFaces:
        cmds.warning("No faces selected for extraction.")
        return

    if not cmds.objExists(toPartsMesh):
        cmds.error("Mesh '{}' does not exist.".format(toPartsMesh))
        return

    # Detach the selected faces
    cmds.polyChipOff(selectedFaces, ch=1, kft=1, dup=0, off=0)

    # Separate the detached faces into separate mesh objects
    cmds.polySeparate(selectedFaces[0].split('.')[0], rs=1, ch=1)

    # Get the transformed parts (meshes) and delete construction history
    myTransform = list(set([cmds.listRelatives(i, p=1)[0] for i in
                            cmds.ls(toPartsMesh, dag=True, type="mesh")]))
    for i in myTransform:
        cmds.delete(i, ch=1)

    return myTransform  # Return the new meshes created


def uncombineMesh(selectedMesh, keepHistory=True):
    """
    Separates a combined mesh into individual mesh objects.

    Args:
        selectedMesh (str): The name of the combined mesh object to uncombine.
        keepHistory (bool): If False, delete the construction history of the separated meshes. Default is True.

    Returns:
        list: List of the new mesh objects created from separating the combined mesh.
    """
    if not cmds.objExists(selectedMesh):
        cmds.error("Mesh '{}' does not exist.".format(selectedMesh))
        return []

    # Separate the combined mesh into individual meshes
    meshes = cmds.polySeparate(selectedMesh, ch=1)

    # If not keeping history, delete construction history
    if not keepHistory:
        for i in meshes:
            cmds.delete(i, ch=1)

    return meshes  # Return the separated meshes
