import maya.cmds as cmds
import maya.mel as mel
import dw_maya.dw_maya_utils as dwu
from dw_maya.dw_decorators import acceptString

def get_vtx_maps(cloth_node: str) -> list:
    """
    Retrieves the list of vertex maps associated with a given cloth node.

    Args:
        cloth_node (str): The name of the cloth or rigid node in Maya.

    Returns:
        list: List of vertex map names for the specified cloth node, or an empty list if none are found.
    """
    if not cmds.objExists(cloth_node):
        cmds.warning(f"Node '{cloth_node}' does not exist.")
        return []

    if cmds.nodeType(cloth_node) not in ['nCloth', 'nRigid']:
        cmds.warning(f"Node '{cloth_node}' is not of type 'nCloth' or 'nRigid'.")
        return []

    # Get map names by filtering attributes ending with "MapType"
    attrs = cmds.listAttr(cloth_node) or []
    maps = [attr.replace('MapType', '') for attr in attrs if attr.endswith("MapType")]

    return maps


def get_vtx_map_type(cloth_node: str, maptype: str) -> int:
    """
    Retrieves the type of a specified vertex map on a cloth node.

    Args:
        cloth_node (str): The name of the cloth or rigid node.
        maptype (str): The name of the vertex map attribute (must end with 'MapType').

    Returns:
        int: The type of the vertex map:
            - 0: None
            - 1: Vertex
            - 2: Texture
        Returns None if the cloth node or map type attribute does not exist.
    """
    if not cmds.objExists(cloth_node):
        cmds.warning(f"Node '{cloth_node}' does not exist.")
        return None

    if cmds.nodeType(cloth_node) not in ['nCloth', 'nRigid']:
        cmds.warning(f"Node '{cloth_node}' is not of type 'nCloth' or 'nRigid'.")
        return None

    # Check that maptype is a valid attribute ending with "MapType"
    if not maptype.endswith("MapType"):
        cmds.warning(f"Map type '{maptype}' must end with 'MapType'.")
        return None

    map_attr = f"{cloth_node}.{maptype}"
    if not cmds.attributeQuery(maptype, node=cloth_node, exists=True):
        cmds.warning(f"Map type attribute '{map_attr}' does not exist.")
        return None

    # Retrieve and return the map type
    return cmds.getAttr(map_attr)


def set_vtx_map_type(cloth_node: str, maptype: str, value: int) -> bool:
    """
    Sets the vertex map type for a specified cloth or rigid node.

    Args:
        cloth_node (str): The name of the cloth or rigid shape node.
        maptype (str): The name of the vertex map attribute (must end with 'MapType').
        value (int): The type of vertex map to set:
            - 0: None
            - 1: Vertex
            - 2: Texture

    Returns:
        bool: True if the attribute was set successfully, False otherwise.
    """
    # Check if the node exists
    if not cmds.objExists(cloth_node):
        cmds.warning(f"Node '{cloth_node}' does not exist.")
        return False

    # Verify node type
    if cmds.nodeType(cloth_node) not in ['nCloth', 'nRigid']:
        cmds.warning(f"Node '{cloth_node}' is not of type 'nCloth' or 'nRigid'.")
        return False

    # Ensure maptype is valid and ends with "MapType"
    if not maptype.endswith("MapType"):
        cmds.warning(f"Map type '{maptype}' must end with 'MapType'.")
        return False

    # Check if the maptype attribute exists on the node
    map_attr = f"{cloth_node}.{maptype}"
    if not cmds.attributeQuery(maptype, node=cloth_node, exists=True):
        cmds.warning(f"Map type attribute '{map_attr}' does not exist.")
        return False

    # Set the attribute
    try:
        cmds.setAttr(map_attr, value)
        return True
    except Exception as e:
        cmds.warning(f"Failed to set attribute '{map_attr}' with error: {e}")
        return False


def get_vtx_map_data(cloth_node: str, vtx_map: str) -> list:
    """
    Retrieves the influence values per vertex for a given vertex map on a cloth or rigid node.

    Args:
        cloth_node (str): The name of the cloth or rigid node.
        vtx_map (str): The name of the vertex map attribute (must end with 'PerVertex').

    Returns:
        list: The list of influence values per vertex if successful, or an empty list if not.
    """
    # Check if the cloth node exists
    if not cmds.objExists(cloth_node):
        cmds.warning(f"Node '{cloth_node}' does not exist.")
        return []

    # Verify that the node is of type 'nCloth' or 'nRigid'
    if cmds.nodeType(cloth_node) not in ['nCloth', 'nRigid']:
        cmds.warning(f"Node '{cloth_node}' is not of type 'nCloth' or 'nRigid'.")
        return []

    # Validate that the vertex map attribute ends with 'PerVertex' and exists on the node
    if not vtx_map.endswith("PerVertex"):
        cmds.warning(f"Vertex map '{vtx_map}' must end with 'PerVertex'.")
        return []

    map_attr = f"{cloth_node}.{vtx_map}"
    if not cmds.attributeQuery(vtx_map, node=cloth_node, exists=True):
        cmds.warning(f"Vertex map attribute '{map_attr}' does not exist.")
        return []

    # Retrieve and return the influence values
    try:
        return cmds.getAttr(map_attr) or []
    except Exception as e:
        cmds.warning(f"Failed to retrieve vertex map data for '{map_attr}': {e}")
        return []



def set_vtx_map_data(cloth_node: str, vtx_map: str, value: list, refresh: bool = False) -> bool:
    """
    Sets the influence values per vertex for a given vertex map on a cloth or rigid node.

    Args:
        cloth_node (str): The name of the cloth or rigid node.
        vtx_map (str): The name of the vertex map attribute (must end with 'PerVertex').
        value (list): The influence values per vertex.
        refresh (bool): Whether to refresh the Maya UI after setting the value.

    Returns:
        bool: True if successful, False otherwise.
    """
    # Validate if the node exists
    if not cmds.objExists(cloth_node):
        cmds.warning(f"Node '{cloth_node}' does not exist.")
        return False

    # Check node type
    if cmds.nodeType(cloth_node) not in ['nCloth', 'nRigid']:
        cmds.warning(f"Node '{cloth_node}' is not of type 'nCloth' or 'nRigid'.")
        return False

    # Validate if vertex map attribute ends with 'PerVertex' and exists on the node
    if not vtx_map.endswith("PerVertex"):
        cmds.warning("Vertex map attribute must end with 'PerVertex'.")
        return False

    map_attr = f"{cloth_node}.{vtx_map}"
    if not cmds.attributeQuery(vtx_map, node=cloth_node, exists=True):
        cmds.warning(f"Vertex map attribute '{map_attr}' does not exist.")
        return False

    # Set the attribute value and optionally refresh the UI
    try:
        cmds.setAttr(map_attr, value, type='doubleArray')
        if refresh:
            cmds.refresh()
        return True
    except Exception as e:
        cmds.warning(f"Failed to set vertex map data for '{map_attr}': {e}")
        return False

@acceptString("cloth_mesh")
def paint_vtx_map(map_attr, cloth_mesh=None, nucleus=None):
    """Enables Maya's vertex paint tool on the specified map attribute.

    Args:
        map_attr (str): Vertex map attribute, typically ending in 'PerVertex' or 'Map'.
        cloth_mesh (str, optional): Mesh associated with the cloth. Defaults to None.
        nucleus (str, optional): Nucleus node, used to force settings if errors occur. Defaults to None.
    """
    map_name = map_attr.split('.')[-1]

    # ======================================================================
    # Mesh Selection Handling
    # ======================================================================
    sel_mesh = dwu.lsTr(sl=True, dag=True, o=True, type='mesh')
    if not sel_mesh and not cloth_mesh:
        cmds.error("No mesh selected and no cloth mesh provided.")
        return
    target_mesh = cloth_mesh or sel_mesh

    components = [".vtx[", ".e[", ".f["]
    is_component = any(comp in target_mesh[0] for comp in components)
    # Convert selected components if vertices are selected
    if is_component:
        target_mesh = cmds.polyListComponentConversion(target_mesh, tv=True)

    cmds.select(target_mesh, r=True)

    # ======================================================================
    # Attempt to Start Painting
    # ======================================================================
    try:
        if 'PerVertex' in map_name:
            map_base = map_name.replace('PerVertex', '')
            mel.eval(f'setNClothMapType("{map_base}", "", 1);')
            mel.eval(f'artAttrNClothToolScript 3 {map_base};')
        elif 'Map' in map_name:
            cmds.error("Map type painting is not implemented.")
    except:
        if nucleus:
            _force_enable_nucleus(nucleus, map_name)
        cmds.error("Please ensure the nucleus and cloth are activated, and try moving to the first frame.")

def _force_enable_nucleus(nucleus, map_name):
    """Helper function to force enable nucleus in case of errors."""
    cmds.setAttr(f'{nucleus}.visibility', 1)
    try:
        cmds.setAttr(f'{nucleus}.enable', 1)
    except:
        pass

    start_frame = cmds.getAttr(f'{nucleus}.startFrame')
    cmds.currentTime(start_frame, u=True)

    try:
        if 'PerVertex' in map_name:
            map_base = map_name.replace('PerVertex', '')
            mel.eval(f'setNClothMapType("{map_base}", "", 1);')
            mel.eval(f'artAttrNClothToolScript 3 {map_base};')
    except:
        cmds.error("Error enabling nucleus; please ensure nucleus and cloth are active and start from the first frame.")

def smooth_pervtx_map(iteration=1):
    """ Enable maya vertex paint tool and launch smooth
        :param clothNode: Cloth node name
        :type clothNode: str
        :param mapName: Vertex map name
        :type mapName: str """
    # Set The Paint Editor and set it to Smooth Operation
    cmds.artAttrCtx('artAttrNClothContext', edit=1, selectedattroper="smooth")
    # Make sure the Paint Editor is init otherwise it wont work
    cmds.refresh()
    for i in range(iteration):
        # smooth operation TODO: delay with maya threading
        cmds.artAttrCtx('artAttrNClothContext', edit=1, clear=1)
