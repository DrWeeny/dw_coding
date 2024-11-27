

from maya import cmds


def getVertexMap(vertex: str, get_map_index: bool = False):
    """
    Retrieve the UV coordinates or UV map index of a specified vertex.

    Args:
        vertex (str): The vertex component (e.g., "pCube1.vtx[0]").
        get_map_index (bool): If True, returns the UV map index; if False, returns UV coordinates.

    Returns:
        list: UV map index if `get_map_index` is True, otherwise UV coordinates [U, V].

    Raises:
        ValueError: If the vertex does not exist or is not valid.
    """
    # Validate that the input is a vertex
    if not vertex or not cmds.ls(vertex, type='float3'):
        cmds.error(f"Invalid vertex provided: '{vertex}'")
        return

    # Convert the vertex to a UV map
    vtx_map = cmds.polyListComponentConversion(vertex, tuv=True)

    # If getMapIndex is True, return the UV map index
    if get_map_index:
        return vtx_map

    # Query the UV coordinates for the converted UV map
    uv_value = cmds.polyEditUV(vtx_map, query=True)

    # Return only the first two UV values (U, V)
    if len(uv_value) > 2:
        return uv_value[:2]

    return uv_value
