import re
from typing import List, Optional, Union, Tuple
from maya import cmds, mel
from dw_logger import get_logger

logger = get_logger()


def find_type_in_history(obj: str, obj_type: List[str], future: bool = False, past: bool = False) -> Optional[str]:
    """Find the closest node of specified type in the object's history.

    Args:
        obj: Name of the source object to search from
        obj_type: List of Maya node types to search for
        future: Whether to search forward connections
        past: Whether to search backward connections

    Returns:
        The name of the closest matching node, or None if not found

    Example:
        >>> find_type_in_history("pSphere1", ["nCloth"], past=True)
        'pSphere1Shape_nCloth'
    """
    if past and future:
        past_list = cmds.listHistory(obj, f=False, bf=True, af=True) or []
        future_list = cmds.listHistory(obj, f=True, bf=True, af=True) or []
        past_objs = cmds.ls(past_list, type=obj_type) or []
        future_objs = cmds.ls(future_list, type=obj_type) or []

        if past_objs:
            if future_objs:
                mini = min(len(future_list), len(past_list))
                for i in range(mini):
                    if past_list[i] == past_objs[0]:
                        return past_objs[0]
                    if future_list[i] == future_objs[0]:
                        return future_objs[0]
            return past_objs[0]
        elif future_objs:
            return future_objs[0]
    else:
        if past:
            hist = cmds.listHistory(obj, f=False, bf=True, af=True) or []
            objs = cmds.ls(hist, type=obj_type) or []
            if objs:
                return objs[0]
        if future:
            hist = cmds.listHistory(obj, f=True, bf=True, af=True) or []
            objs = cmds.ls(hist, type=obj_type) or []
            if objs:
                return objs[0]
    return None

def get_nucx_node(node_name: str) -> Optional[str]:
    """Find the nCloth or nRigid node connected to the given object.

    Args:
        node_name: Name of the transform or mesh node

    Returns:
        Name of the connected nucleus node (nCloth/nRigid), or None if not found

    Example:
        >>> get_nucx_node("clothMesh1")
        'clothMesh1Shape_nCloth'
    """
    return find_type_in_history(node_name, ['nCloth', 'nRigid'], future=True, past=True)

def get_mesh_from_nucx_node(nucx_node: str) -> Optional[str]:
    """Get the input mesh connected to the given nucleus node.

    Args:
        nucx_node: Name of the nCloth or nRigid node

    Returns:
        Name of the connected mesh node, or None if not found

    Example:
        >>> get_mesh_from_nucx_node("clothMesh1Shape_nCloth")
        'clothMesh1'
    """
    if cmds.objExists(nucx_node) and cmds.nodeType(nucx_node) in ['nCloth', 'nRigid']:
        mesh = cmds.listConnections(f"{nucx_node}.inputMesh", s=True)
        if mesh:
            return mesh[0]
    return None

def get_nucx_node_from_sel() -> List[str]:
    """Find all nCloth/nRigid nodes connected to currently selected objects.

    Returns:
        List of unique nucleus node names found in selection

    Example:
        >>> get_nucx_node_from_sel()
        ['cloth1_nCloth', 'cloth2_nCloth']
    """
    nucx_nodes = []
    selected = cmds.ls(sl=True) or []
    for node in selected:
        nucx_node = get_nucx_node(node)
        if nucx_node and nucx_node not in nucx_nodes:
            nucx_nodes.append(nucx_node)
    return nucx_nodes

def get_pervertex_maps(cloth_node: str) -> List[str]:
    """Get list of per-vertex maps from a nucleus node.

    Args:
        cloth_node: Name of the nCloth or nRigid node

    Returns:
        List of map names found on the node

    Example:
        >>> get_pervertex_maps("clothMesh1Shape_nCloth")
        ['thickness', 'bounce', 'friction']
    """
    maps = []
    if cmds.objExists(cloth_node) and cmds.nodeType(cloth_node) in ['nCloth', 'nRigid']:
        attrs = cmds.listAttr(cloth_node) or []
        maps = [attr.replace('MapType', '') for attr in attrs if attr.endswith("MapType")]
    return maps

def get_nucx_map_type(nucx_node: str, mapType: str) -> Optional[int]:
    """Get the type of a nucleus map attribute.

    Args:
        nucx_node: Name of the nCloth or nRigid node
        mapType: Name of the map attribute (must end with 'MapType')

    Returns:
        Map type value (0=None, 1=Vertex, 2=Texture) or None if invalid

    Example:
        >>> get_nucx_map_type("clothMesh1Shape_nCloth", "thicknessMapType")
        1
    """
    if cmds.objExists(nucx_node) and cmds.nodeType(nucx_node) in ['nCloth', 'nRigid']:
        return cmds.getAttr(f"{nucx_node}.{mapType}")
    return None

def set_nucx_map_type(nucx_node: str, mapType: str, value: int) -> bool:
    """Set the type of a nucleus map attribute.

    Args:
        nucx_node: Name of the nCloth or nRigid node
        mapType: Name of the map attribute (must end with 'MapType')
        value: Map type to set (0=None, 1=Vertex, 2=Texture)

    Returns:
        True if successful, False otherwise

    Example:
        >>> set_nucx_map_type("clothMesh1Shape_nCloth", "thicknessMapType", 1)
        True
    """
    if cmds.objExists(nucx_node) and cmds.nodeType(nucx_node) in ['nCloth', 'nRigid']:
        cmds.setAttr(f"{nucx_node}.{mapType}", value)
        return True
    return False

def get_nucx_map_data(nucx_node: str, nucx_map: str) -> Optional[List[float]]:
    """Get per-vertex map values from a nucleus node.

    Args:
        nucx_node: Name of the nCloth or nRigid node
        nucx_map: Name of the map attribute (must end with 'PerVertex')

    Returns:
        List of per-vertex values, or None if invalid

    Example:
        >>> get_nucx_map_data("clothMesh1Shape_nCloth", "thicknessPerVertex")
        [1.0, 0.8, 0.7, ...]
    """
    if cmds.objExists(nucx_node) and cmds.nodeType(nucx_node) in ['nCloth', 'nRigid']:
        return cmds.getAttr(f"{nucx_node}.{nucx_map}")
    return None

def set_nucx_map_data(nucx_node: str, nucx_map: str, value: List[float]) -> None:
    """Set per-vertex map values on a nucleus node.

    Args:
        nucx_node: Name of the nCloth or nRigid node
        nucx_map: Name of the map attribute (must end with 'PerVertex')
        value: List of values to set per vertex

    Example:
        >>> set_nucx_map_data("clothMesh1Shape_nCloth", "thicknessPerVertex", [1.0] * 100)
    """
    cmds.setAttr(f'{nucx_node}.{nucx_map}', value, type='doubleArray')


def get_mesh_selected_vtx(nucx_node: str, index_only: bool = False) -> List[Union[int, str]]:
    """Get selected vertices from the mesh connected to a nucleus node.

    Args:
        nucx_node: Name of the nCloth or nRigid node
        index_only: If True, return only vertex indices; if False, return full names

    Returns:
        List of vertex indices or full vertex names

    Example:
        >>> getModelSelectedVtx("clothMesh1Shape_nCloth", True)
        [0, 1, 2, 3]
        >>> getModelSelectedVtx("clothMesh1Shape_nCloth", False)
        ['clothMesh1.vtx[0]', 'clothMesh1.vtx[1]']
    """
    sel = cmds.ls(sl=True) or []
    model = get_mesh_from_nucx_node(nucx_node)
    sel_vtx: List[Union[int, str]] = []

    if not model:
        return sel_vtx

    for node in sel:
        if node.startswith(model) and node.endswith(']'):
            sel_name = node.split('.')[0]
            ind = node.split('.')[-1].replace('vtx[', '').replace(']', '')
            if ':' not in ind:
                if index_only:
                    sel_vtx.append(int(ind))
                else:
                    sel_vtx.append(f"{sel_name}.vtx[{ind}]")
            else:
                deb, fin = map(int, ind.split(':'))
                for n in range(deb, fin + 1):
                    if index_only:
                        sel_vtx.append(n)
                    else:
                        sel_vtx.append(f"{sel_name}.vtx[{n}]")
    return sel_vtx
