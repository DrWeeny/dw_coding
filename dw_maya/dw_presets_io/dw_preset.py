import maya.cmds as cmds
import re
import dw_maya.dw_decorators as dwdeco
from dw_maya.dw_constants import gAEAttrPresetExcludeAttrs, gAEAttrPresetExcludeNodeAttrs
from collections import defaultdict


def validNodeTypeAttrForCurrentPreset(node_type: str, attr: str) -> bool:
    """
    Check whether a given attribute of a node type is valid for the current preset.

    Args:
        node_type (str): The node type to check (e.g., 'mesh', 'nurbsCurve').
        attr (str): The attribute to check (e.g., 'parent[1].child[2].x').

    Returns:
        bool: True if the attribute is valid for the current preset, False otherwise.
    """

    # Validate input types
    if not isinstance(node_type, str) or not isinstance(attr, str):
        raise ValueError("Both 'node_type' and 'attr' must be strings.")

    # Remove any array indices (e.g., '[1]') from the attribute using regex.
    cleaned_attr = re.sub(r'\[\d*\]', '', attr)

    # Check if the cleaned attribute is in the global exclude list
    if cleaned_attr in gAEAttrPresetExcludeAttrs:
        return False

    # Check if the specific node-type attribute is in the node-specific exclude list
    node_specific_attr = f"{node_type}.{cleaned_attr}"
    if node_specific_attr in gAEAttrPresetExcludeNodeAttrs:
        return False

    # If none of the checks were triggered, return True (attribute is valid)
    return True


def filter_channelbox_attrs(node):
    """Return only attributes visible in the channel box for the given node."""
    return cmds.listAttr(node, keyable=True, visible=True, read=True, settable=True, unlocked=True)


def filter_attributes(attr_list, filter_match=None, filter_exclude=None):
    import fnmatch

    if isinstance(attr_list, str):
        attr_list = [attr_list]
    if isinstance(filter_match, str):
        filter_match = [filter_match]
    if isinstance(filter_exclude, str):
        filter_exclude = [filter_exclude]

    # Include only attributes matching filter_include patterns
    if filter_match:
        attr_list = [a for a in attr_list if any(fnmatch.fnmatch(a, pat) for pat in filter_match)]
    # Exclude attributes matching filter_exclude patterns
    if filter_exclude:
        attr_list = [a for a in attr_list if not any(fnmatch.fnmatch(a, pat) for pat in filter_exclude)]
    return attr_list

@dwdeco.acceptString('nodeName')
def createAttrPreset(nodeName: list,
                     stripNamespace: bool = True,
                     filter_match:list=None,
                     filter_exclude:list=None,
                     in_channelbox:bool=False) -> dict:
    """
    Derived from a Maya procedure to create attribute presets for the given nodes.

    Args:
        nodeName (list): List of node names to create presets for.
        stripNamespace (bool): Whether to strip namespaces from node names (default: True).

    Returns:

        dict: A nested dictionary with node attributes and their corresponding values.
               attr_data[nodeName]['nodeType'] : The node type.
               attr_data[nodeName][attr] : Attribute values.
    """

    attr_data = {}

    for n in nodeName:
        # Strip namespace if necessary
        key_n = n.split(':')[-1] if stripNamespace else n
        attr_data[key_n] = {}

        # if this option is enable it will filter all visible/keyable attributes
        if in_channelbox:
            _future_filter = filter_channelbox_attrs(n)
            if _future_filter:
                if not filter_match:
                    filter_match = []
                filter_match.extend(_future_filter)

        # Initialize node dictionary
        node_type = cmds.nodeType(n)
        if filter_match or filter_exclude:
            _node_type = filter_attributes(node_type,
                                           filter_match=filter_match,
                                           filter_exclude=filter_exclude)
            if _node_type:
                attr_data[key_n]['nodeType'] = _node_type[0]
        else:
            attr_data[key_n]['nodeType'] = node_type

        # Fetch string attributes
        string_attrs = cmds.listAttr(n, multi=True, read=True, write=True, visible=True, hasData=True)
        if filter_match or filter_exclude:
            string_attrs = filter_attributes(string_attrs,
                                             filter_match=filter_match,
                                             filter_exclude=filter_exclude)
        if string_attrs:
            for attr in string_attrs:
                obj_attr = f"{n}.{attr}"
                if cmds.objExists(obj_attr):
                    attr_type = cmds.getAttr(obj_attr, sl=True, type=True)
                    if attr_type == "string":
                        # Skip null string data
                        if not cmds.listAttr(obj_attr, hasNullData=True):
                            attr_data[key_n][attr] = cmds.getAttr(obj_attr)


        # Fetch scalar attributes (floats, ints, bools, enums)
        scalar_attrs = cmds.listAttr(n, multi=True, write=True, scalar=True, visible=True, hasData=True)
        if filter_match or filter_exclude:
            scalar_attrs = filter_attributes(scalar_attrs,
                                             filter_match=filter_match,
                                             filter_exclude=filter_exclude)
        if scalar_attrs:
            for attr in scalar_attrs:
                # Skip invalid attributes for current node type
                if not validNodeTypeAttrForCurrentPreset(node_type, attr):
                    continue
                obj_attr = f"{n}.{attr}"
                attr_data[key_n][attr] = cmds.getAttr(obj_attr)

    return attr_data


@dwdeco.acceptString('nodeName')
def createConnectionPreset(nodeName: list, future: int = 0) -> dict:
    """
    Create a preset for the connections of given nodes and their attribute states.

    Args:
        nodeName (list): List of node names to create presets for.
        future (int): Whether to include future connections (default: 0).

    Returns:
        dict: A dictionary of connection and attribute presets for the nodes.
    """
    ignoreList = ['nodeGraphEditorInfo', 'defaultRenderUtilityList', 'defaultTextureList']
    con_txt = defaultdict(lambda: defaultdict(list))

    for node in nodeName:
        # Get node history (future if specified)
        history = cmds.listHistory(node, ac=True, f=future, pdo=True)

        # Skip if history is None (can happen with certain node types like nConstraint, follicle)
        if history is None:
            cmds.warning(f"Could not get history for node: {node}. Skipping connection preset for this node.")
            continue

        for idx, hist_node in enumerate(history):
            # List connections: for first node, only source connections, for others, all connections
            connections = cmds.listConnections(hist_node, p=True, s=True, d=False) if not idx else cmds.listConnections(
                hist_node, p=True)

            if connections:
                # Filter out ignored types and fetch targets
                valid_conns = [con for con in connections if cmds.nodeType(con) not in ignoreList]
                if valid_conns:
                    targets = cmds.listConnections(valid_conns, p=True)
                    if targets:
                        con_txt[node]['connections'].extend(zip(valid_conns, targets))

        # Remove duplicate connections
        con_txt[node]['connections'] = list(set(con_txt[node]['connections']))

        # Create attribute presets for each node in the history
        for hist_node in history:
            if hist_node != 'connections':
                con_txt[node][f'node_{hist_node}'] = createAttrPreset(hist_node)

    return con_txt

# sub fonctions for reconnect preset
def remapNodeName(attr, correspondance):
    """
    Remaps node names based on the correspondance dictionary.

    Args:
        attr (str): The attribute string with node and attribute names.
        correspondance (dict): The mapping of original node names to new node names.

    Returns:
        str: The remapped attribute string with the updated node name.
    """
    attr_name_parts = attr.split('.')
    node_name = attr_name_parts[0]

    # Replace the node name with the new name from correspondance, if it exists
    if node_name in correspondance:
        attr_name_parts[0] = correspondance[node_name]

    return '.'.join(attr_name_parts)


def reconnectAttributes(src, target):
    """
    Reconnects attributes between source and target nodes, handling exceptions.

    Args:
        src (str): The source attribute.
        target (str): The target attribute.
    """
    try:
        if not cmds.listConnections(src, p=True):
            cmds.connectAttr(src, target, f=True)
        else:
            existing_connection = cmds.listConnections(src, p=True)[0]
            if existing_connection != target:
                cmds.connectAttr(src, target, f=True)
    except Exception:
        # If the source connection fails, try the reverse
        try:
            if not cmds.listConnections(target, p=True):
                cmds.connectAttr(target, src, f=True)
            else:
                existing_connection = cmds.listConnections(target, p=True)[0]
                if existing_connection != src:
                    cmds.connectAttr(target, src, f=True)
        except Exception as e:
            print(f"Could not connect {src} -> {target}: {str(e)}")


def reconnectPreset(mydic=dict, targ_ns=':', create=True):
    """
    Reconnect or recreate nodes and their connections based on a dictionary preset.

    Args:
        mydic (dict): The dictionary that stores node connections and attributes.
        targ_ns (str): The target namespace to apply to new nodes (default is root ':').
        create (bool): Whether to create missing nodes (default: True).

    Returns:
        dict: A dictionary mapping original node names to newly created node names.
    """

    correspondance = {}

    # Adjust namespace formatting
    targ_ns = '' if targ_ns == ':' else targ_ns + ':'

    if create:
        for node in mydic:
            for node_key, node_data in mydic[node].items():
                if node_key.startswith('node_'):
                    original_name = node_key.split('node_')[-1]
                    new_name = targ_ns + original_name

                    # Get node type and attributes
                    node_type = node_data[original_name]['nodeType']
                    attrs = node_data[original_name]

                    # Create the node if necessary and store the correspondence
                    new_node = cmds.createNode(node_type, name=new_name)
                    correspondance[original_name] = new_node

                    # Blend or set attributes on the new node
                    for attr in attrs:
                        blendAttr(original_name, new_node, attr, node_data, 1)

    # Handle connections after node creation
    for node in mydic:
        for src, target in mydic[node]['connections']:
            src = remapNodeName(src, correspondance)
            target = remapNodeName(target, correspondance)
            reconnectAttributes(src, target)

    return correspondance


def blendAttrDic(srcNode=str, targetNode=None, preset=dict, blendValue=1):
    """
    Blends attributes from srcNode to targetNode using values from the preset dictionary.

    Args:
        srcNode (str): The source node from which attributes are blended.
        targetNode (str): The target node to which attributes are applied (defaults to srcNode).
        preset (dict): Dictionary containing attribute presets.
        blendValue (float): Blending factor (default: 1).

    """
    if not targetNode:
        targetNode = srcNode

    for attr, value in preset[srcNode].items():
        targetAttr = f"{targetNode}.{attr}"

        if cmds.objExists(targetAttr) and cmds.getAttr(targetAttr, se=True):
            attrType = cmds.getAttr(targetAttr, type=True)

            # Handle blending for numeric values (int, float, long, etc.)
            if blendValue < 0.999 and isinstance(value, (int, float, bool)):
                blendNumericAttr(targetAttr, value, attrType, blendValue)
            else:
                applyAttrDirectly(targetAttr, value, attrType)

def blend_attr_dic(src_node:str, target_node:str=None, preset:dict=None, blend_value:int=1, rm_keyframe:bool=False):
    """
    Blends attributes from srcNode to targetNode using values from the preset dictionary.

    Args:
        src_node (str): The source node from which attributes are blended.
        target_node (str): The target node to which attributes are applied (defaults to srcNode).
        preset (dict): Dictionary containing attribute presets.
        blend_value (float): Blending factor (default: 1).
    """
    if not preset:
        print(f"no preset found for {src_node}")
        return

    if not target_node:
        target_node = src_node

    # Skip processing if the source node isn't in the preset
    if src_node not in preset:
        return

    # Get node type to determine whether to use transform or shape
    node_type = preset[src_node].get('nodeType')

    # Process attributes
    for attr, value in preset[src_node].items():
        # Skip nodeType and legacy *_nodeType attributes
        if attr == 'nodeType' or attr.endswith('_nodeType'):
            continue

        # Determine the correct target node (transform or shape)
        if node_type == "transform":
            # For transform attributes, use the transform node
            target_obj = target_node
        else:
            # For shape or other node types, try to get the shape
            shapes = cmds.listRelatives(target_node, shapes=True)
            target_obj = shapes[0] if shapes else target_node

        targetAttr = f"{target_obj}.{attr}"

        # Check if value is a special token that needs evaluation
        from dw_maya.dw_constants import SPECIAL_TOKENS
        if isinstance(value, str) and value in SPECIAL_TOKENS:
            value = SPECIAL_TOKENS[value]()

        # Check if attribute exists and is settable
        if cmds.objExists(targetAttr) and cmds.getAttr(targetAttr, se=True):
            # Check for and delete any existing animation keys
            if rm_keyframe:
                if cmds.keyframe(targetAttr, query=True, keyframeCount=True):
                    cmds.cutKey(targetAttr)

            attrType = cmds.getAttr(targetAttr, type=True)

            # Handle blending for numeric values
            if blend_value < 0.999 and isinstance(value, (int, float, bool)):
                blendNumericAttr(targetAttr, value, attrType, blend_value)
            else:
                applyAttrDirectly(targetAttr, value, attrType)

def blendNumericAttr(targetAttr, value, attrType, blendValue):
    """
    Handles blending for numeric attributes based on their type.

    Args:
        targetAttr (str): The target attribute.
        value (int, float, long): The value to be blended.
        attrType (str): The type of the attribute.
        blendValue (float): The blend factor.
    """
    currentValue = cmds.getAttr(targetAttr)

    if attrType == 'enum':
        # Handle enum type: binary blend decision
        value = currentValue if blendValue < 0.5 else value
        cmds.setAttr(targetAttr, value)

    elif attrType in ["bool", "short", "long", "byte", "char"]:
        # Blend integer-like values
        blendedValue = int(value * blendValue + currentValue * (1 - blendValue))
        cmds.setAttr(targetAttr, blendedValue)

    elif attrType in ["float", "floatLinear", "double", "doubleLinear", "doubleAngle", "time"]:
        # Blend float and time-based values
        blendedValue = value * blendValue + currentValue * (1 - blendValue)
        cmds.setAttr(targetAttr, blendedValue)


def applyAttrDirectly(targetAttr, value, attrType):
    """
    Directly applies attributes (for string or non-blended numeric types).

    Args:
        targetAttr (str): The target attribute.
        value (any): The value to apply.
        attrType (str): The type of the attribute.
    """
    if isinstance(value, str):
        # Special handling for string attributes like 'notes'
        if attrType == "string" or attrType is None:
            if not cmds.objExists(targetAttr):
                # Handle dynamic attribute creation
                cmds.addAttr(targetAttr, dt="string", ln="notes", sn="nts")

            if cmds.objExists(targetAttr) and cmds.getAttr(targetAttr, settable=True):
                cmds.setAttr(targetAttr, value, type='string')

    elif isinstance(value, (int, float, bool)):
        # Directly set numeric or boolean attributes
        cmds.setAttr(targetAttr, value, c=True)


def blendAttr(srcNode=str, targetNode=None, attr=str, preset=dict, blendValue=1):
    """
    Blends and sets the attribute values from the preset to the target node.

    Args:
        srcNode (str): Source node name.
        targetNode (str): Target node name. Defaults to srcNode if not provided.
        attr (str): Attribute name.
        preset (dict): Dictionary containing the attribute values for the source node.
        blendValue (float): Blending factor for the attribute values.
    """
    if not targetNode:
        targetNode = srcNode

    # Fetch the attribute value from the preset
    value = preset[srcNode][attr]
    targetAttr = f"{targetNode}.{attr}"

    if cmds.objExists(targetAttr) and cmds.getAttr(targetAttr, se=True):
        attrType = cmds.getAttr(targetAttr, type=True)

        # Handle blending of numeric attributes (floats, ints, etc.)
        if blendValue < 0.999 and isinstance(value, (int, float, bool)):
            blendNumericAttr(targetAttr, value, attrType, blendValue)
        else:
            setAttrDirectly(targetAttr, value, attrType, attr)


def blendNumericAttr(targetAttr, value, attrType, blendValue):
    """
    Blends and sets the numeric attributes (float, int, bool, etc.).

    Args:
        targetAttr (str): The attribute to set.
        value (int, float, long): The value to blend with.
        attrType (str): The type of the attribute.
        blendValue (float): The blend factor.
    """
    currentValue = cmds.getAttr(targetAttr)

    if attrType == 'enum':
        # Blend enum type (binary choice based on blendValue)
        value = currentValue if blendValue < 0.5 else value
        cmds.setAttr(targetAttr, value)

    elif attrType in ["bool", "short", "long", "byte", "char"]:
        # Blend integer-like values
        blendedValue = int(value * blendValue + currentValue * (1 - blendValue))
        cmds.setAttr(targetAttr, blendedValue)

    elif attrType in ["float", "floatLinear", "double", "doubleLinear", "doubleAngle", "time"]:
        # Blend float-like values
        blendedValue = value * blendValue + currentValue * (1 - blendValue)
        cmds.setAttr(targetAttr, blendedValue)


def setAttrDirectly(targetAttr, value, attrType, attrName):
    """
    Directly sets the attribute value without blending.

    Args:
        targetAttr (str): The target attribute to set.
        value (any): The value to set.
        attrType (str): The type of the attribute.
        attrName (str): The name of the attribute (for specific cases like notes).
    """
    if isinstance(value, str):
        # Special handling for string attributes like 'notes'
        if attrName in ['notes', 'nts']:
            if not cmds.objExists(targetAttr):
                # Create the attribute if it doesn't exist (for notes)
                cmds.addAttr(targetAttr, dt="string", ln="notes", sn="nts")

        if cmds.objExists(targetAttr) and cmds.getAttr(targetAttr, settable=True):
            cmds.setAttr(targetAttr, value, type='string')

    elif isinstance(value, (int, float, bool)):
        # Directly set numeric or boolean attributes
        cmds.setAttr(targetAttr, value, c=True)


def set_grouping(name, geo_dic):
    """
    Creates sets and groups geometries based on the dictionary structure.

    Args:
        name (str): The name of the main set.
        geo_dic (dict): Dictionary where keys are the group names and values are geometries.
    """
    main_set = cmds.sets(name=name, em=True)
    for group, geometries in geo_dic.items():
        subgroup = cmds.sets(geometries, n=group)
        cmds.sets(subgroup, edit=True, fe=main_set)