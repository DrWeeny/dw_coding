import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
import maya.mel as mel
from typing import Optional, List
import re

def convert_to_cm_factor() -> float:
    """
    Convert the current linear unit in Maya to a factor for conversion to centimeters.

    Returns:
        float: The conversion factor to centimeters.
    """
    unit_to_cm = {
        "mm": 0.1,   # Millimeter to centimeter
        "cm": 1.0,   # Centimeter to centimeter (no conversion needed)
        "m": 100.0,  # Meter to centimeter
        "in": 2.54,  # Inch to centimeter
        "ft": 30.48, # Foot to centimeter
        "yd": 91.44  # Yard to centimeter
    }

    unit = cmds.currentUnit(query=True, linear=True)
    return unit_to_cm.get(unit, 1.0)  # Default to 1.0 if the unit is unknown


def find_type_in_history(obj: str, target_type: str, future: bool = False, past: bool = False) -> Optional[str]:
    """
    Search through an object's history (either in the past, future, or both) to find the first occurrence
    of a node of a given type.

    Args:
        obj (str): The name of the object whose history is to be searched.
        target_type (str): The node type to search for in the history.
        future (bool): Whether to search in the future history of the object.
        past (bool): Whether to search in the past history of the object.

    Returns:
        Optional[str]: The name of the first node of the given type, or None if not found.
    """
    if not past and not future:
        return None  # No need to search if both flags are False

    past_objs, future_objs = [], []

    if past:
        past_history = cmds.listHistory(obj, future=False, bf=True, af=True) or []
        past_objs = cmds.ls(past_history, type=target_type)

    if future:
        future_history = cmds.listHistory(obj, future=True, bf=True, af=True) or []
        future_objs = cmds.ls(future_history, type=target_type)

    if past_objs and future_objs:
        min_length = min(len(past_history), len(future_history))
        for i in range(min_length):
            if past_history[i] in past_objs:
                return past_objs[0]
            if future_history[i] in future_objs:
                return future_objs[0]
    elif past_objs:
        return past_objs[0]
    elif future_objs:
        return future_objs[0]

    return None

def get_next_free_multi_index(attr: str,
                              max_connections: int = 10_000_000,
                              str_result: bool = False) -> int:
    """
    Get the next available multi-index for a given attribute.

    Args:
        attr (str): The attribute in the form "node.attrName".
        max_connections (int): The maximum number of indices to check (default is 10 million).

    Returns:
        int: The next available index for the multi-attribute.
    """
    # Remove any existing index from the attribute string (e.g., from node.attr[0] to node.attr)
    attr = re.sub(r'\[\d+]$', '', attr)
    node, attribute = attr.split('.')

    for i in range(max_connections):
        attr_id = f'{node}.{attribute}[{i}]'
        # Check if there are any connections for the current index
        if not cmds.connectionInfo(attr_id, sfd=True):
            if str_result:
                return attr_id
            else:
                return i

    raise RuntimeError(f"No available index found in {max_connections} attempts.")


def object_layer(obj: str) -> str:
    """
    Determine the display layer to which an object belongs.

    Args:
        obj (str): The name of the object to check.

    Returns:
        str: The name of the display layer the object belongs to, or "defaultLayer" if none.
    """
    draw_override = f"{obj}.drawOverride"

    if not cmds.objExists(draw_override):
        return "defaultLayer"

    # Find the connected display layer
    conn_list = cmds.listConnections(draw_override, t='displayLayer', d=False)

    if conn_list:
        return conn_list[0]  # If a connection exists, return the first one

    return "defaultLayer"


def obj_is_drawn(shape: str) -> bool:
    """
    Check if the given shape is visible, either directly or within its display layer.

    Args:
        shape (str): The name of the shape node.

    Returns:
        bool: True if the shape is visible, False if it is hidden or in a hidden layer.
    """
    # Check if the shape itself is visible
    if not cmds.getAttr(f"{shape}.visibility"):
        return False

    # Check if the shape's display layer is visible
    layer = object_layer(shape)
    if not cmds.getAttr(f"{layer}.visibility"):
        return not cmds.getAttr(f"{layer}.enabled")

    return True


def match_channel_start(channels: List[str], name: str) -> int:
    """
    Find the index of the first channel that starts with the given name.

    Args:
        channels (List[str]): A list of channel names.
        name (str): The string to match at the start of the channel name.

    Returns:
        int: The index of the matching channel, or -1 if no match is found.
    """
    return next((i for i, ch in enumerate(channels) if ch.startswith(name)), -1)


def match_channel_without_pre_string(channels: List[str], orig_string: str, token: str) -> int:
    """
    Removes the pre-string (the part before a specified token) from channel names
    and searches for a match of the original string without the pre-string.

    Args:
        channels (List[str]): List of channel names.
        orig_string (str): The original string to match against.
        token (str): The token used to split the strings.

    Returns:
        int: The index of the matching channel, or -1 if no match is found.
    """
    new_channels = [ch.split(token)[-1] for ch in channels]
    name = orig_string.split(token)[-1]
    return match_channel_start(new_channels, name)


def find_channel_for_object(index: int, channels: List[str], obj: str) -> str:
    """
    Finds the channel that corresponds to an object, checking the name directly,
    and removing possible pre-strings separated by ':' or '|'.

    Args:
        index (int): The default index to use if no other match is found.
        channels (List[str]): The list of channel names.
        obj (str): The name of the object to match with a channel.

    Returns:
        str: The matching channel name or a warning if no match is found.
    """
    result = channels[index]
    channel_count = len(channels)

    if channel_count == 1:
        return result

    found_match = match_channel_start(channels, obj)

    if found_match == -1:
        # Try removing namespaces and prefixes
        found_match = match_channel_without_pre_string(channels, obj, ":")
        if found_match == -1:
            # Remove namespace if any, split by colon
            obj = obj.split(":")[-1]
            found_match = match_channel_without_pre_string(channels, obj, "|")

        if found_match == -1:
            # Remove any pipeline hierarchy (|)
            obj = obj.split("|")[-1]
            found_match = match_channel_without_pre_string(channels, obj, ":")

    if found_match != -1:
        result = channels[found_match]
    else:
        # If no match found, issue a warning
        mess = f"m_doImportCacheFile.kNoChannelNameMatch : \nresult: {result}\nobj: {obj}"
        cmds.warning(mess)

    return result

def convert_channelname_to_inattr(channelname: str) -> str:
    """
    Converts a channel name in the form of 'plug_attribute' into the format 'plug.attribute'.

    Args:
        channelname (str): The channel name to convert.

    Returns:
        str: The converted attribute in the format 'plug.attribute'.
    """
    parts = channelname.rsplit("_", 1)
    return f"{parts[0]}.{parts[1]}" if len(parts) == 2 else channelname


def polylineflags(num_cvs: int, crv_length: float) -> dict:
    """
    Convert a polyline to Maya flag arguments for curve creation.

    Args:
        num_cvs (int): Number of control vertices (CVs) for the curve.
        crv_length (float): The total length of the curve.

    Returns:
        dict: A dictionary of Maya flags to use as kwargs.
    """
    if num_cvs < 2:
        return {}

    flags = {
        'd': 1,  # Degree of the curve
        'p': [[0, 0, float(i) * (crv_length / (num_cvs - 1))] for i in range(num_cvs)],  # Points list
        'k': list(range(num_cvs))  # Knots
    }

    return flags


def is_all_components(obj: str, num_components: int, comp_type: int) -> bool:
    """
    Checks if the given object contains the specified number of components of a certain type.

    Args:
        obj (str): Name of the object.
        num_components (int): Expected number of components.
        comp_type (int): Type of components to check.
            2: Vertices
            3: Edges
            4: Faces
            7: Particle points
            8: Hair CV (not supported by Autodesk Maya)

    Returns:
        bool: True if the object contains the specified number of components, otherwise False.
    """
    count = 0

    if comp_type == 2:
        count = cmds.polyEvaluate(obj, v=True)  # Vertices
    elif comp_type == 3:
        count = cmds.polyEvaluate(obj, e=True)  # Edges
    elif comp_type == 4:
        count = cmds.polyEvaluate(obj, f=True)  # Faces
    elif comp_type == 7:
        count = int(cmds.particle(obj, query=True, count=True))  # Particle points
    elif comp_type == 8:
        cmds.warning("Hair CV count not supported by Autodesk Maya")
        count = 0  # Hair CVs (unsupported)
    else:
        cmds.warning("Invalid component type specified.")

    return count == num_components


def find_related_hair_system(obj: str) -> str:
    """
    Finds the related hair system for a given object.

    Args:
        obj (str): The name of the object to check.

    Returns:
        str: The related hair system or an empty string if not found.
    """
    if cmds.nodeType(obj) == "hairSystem":
        return obj
    elif cmds.nodeType(obj) == "pfxHair":
        hsys = cmds.listConnections(obj, type='hairSystem')
        if hsys:
            return hsys[0]
    elif cmds.nodeType(obj) in ["nurbsCurve", "follicle"]:
        return find_type_in_history(obj, "hairSystem", future=1, past=1)
    return ""


def find_related_nucleus_object(obj: str) -> str:
    """
    Finds the related nucleus object for a given object.

    Args:
        obj (str): The name of the object to check.

    Returns:
        str: The related nucleus object or an empty string if not found.
    """
    if cmds.nodeType(obj) == "nurbsCurve":
        return find_related_hair_system(obj)
    else:
        return find_type_in_history(obj, "nBase", future=1, past=1)


def make_set_for_component(component: str, input_mesh: str, input_mesh_components: str) -> None:
    """
    Creates a dynamic constraint set for the given mesh component.

    Args:
        component (str): The dynamic constraint component.
        input_mesh (str): The input mesh name.
        input_mesh_components (str): The components of the input mesh (e.g., vertices, edges).

    Returns:
        None
    """
    dynamic_set = cmds.sets(input_mesh_components, name="dynamicConstraintSet#")
    cons = cmds.listConnections(dynamic_set + ".groupNodes[0]", source=False, destination=True)
    if not cons:
        cmds.warning("No Group ID node found for the constraint set.")
        return

    gid = cons[0]
    cmds.connectAttr(gid + ".groupId", component + ".componentGroupId")
    cmds.connectAttr(input_mesh + ".worldMesh[0]", component + ".surface")


def get_first_free_constraint_index(nucleus: str) -> int:
    """
    Finds the first available index in the nucleus inputStart attribute.

    Args:
        nucleus (str): The name of the nucleus node.

    Returns:
        int: The first free index for the inputStart attribute.
    """
    input_start_attr = f"{nucleus}.inputStart"
    num_inputs = cmds.getAttr(input_start_attr, size=True)

    for ind in range(num_inputs):
        input_attr = f"{input_start_attr}[{ind}]"
        connection = cmds.connectionInfo(input_attr, sourceFromDestination=True)
        if not connection:
            return ind

    return num_inputs


def get_input_mesh_for_sets(obj: str) -> list:
    """
    Finds the input mesh for the given object that is used in nBase simulations.

    Args:
        obj (str): The name of the object to check.

    Returns:
        list: A list of two mesh names. The first is the input mesh, and the second is the downstream mesh.
              If no valid mesh is found, an empty list is returned.
    """
    meshes = [None, None]
    part_obj = find_type_in_history(obj, "nBase", future=0, past=1)
    upstream = False

    # If no nBase is found in the history, check downstream.
    if not part_obj:
        part_obj = find_type_in_history(obj, "nBase", future=1, past=0)
        if part_obj:
            meshes[0] = obj
            upstream = True
        else:
            cmds.warning("Object is not connected to any nucleus.")
            return []

    # Get the connected mesh from the input of the nBase.
    connections = cmds.listConnections(f"{part_obj}.inputMesh", source=False, destination=True, type='mesh')

    if connections:
        meshes[1] = connections[0]
        if not upstream:
            meshes[0] = meshes[1]
    elif upstream:
        meshes[1] = meshes[0]
    else:
        cmds.warning("Cannot find an input mesh connected to the nucleus.")

    return [m for m in meshes if m]


