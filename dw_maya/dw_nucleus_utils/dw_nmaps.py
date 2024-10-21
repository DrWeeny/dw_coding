import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from maya import cmds, mel


def getVertexMap(vertex, getMapIndex=False):
    """
    Retrieves the UV coordinates or UV map index of a specified vertex.

    Args:
        vertex (str): The vertex component (e.g., "pCube1.vtx[0]").
        getMapIndex (bool): If True, return the UV map index. Default is False (returns UV coordinates).

    Returns:
        list: UV map index if `getMapIndex` is True, else the UV coordinates [U, V].
    """
    # Validate that the input is a vertex
    if not vertex or not cmds.ls(vertex, type='float3'):
        cmds.error("Invalid vertex provided.")
        return

    # Convert the vertex to a UV map
    vtx_map = cmds.polyListComponentConversion(vertex, tuv=True)

    # If getMapIndex is True, return the UV map index
    if getMapIndex:
        return vtx_map

    # Query the UV coordinates for the converted UV map
    uv_value = cmds.polyEditUV(vtx_map, query=True)

    # Return only the first two UV values (U, V)
    if len(uv_value) > 2:
        return uv_value[:2]

    return uv_value
