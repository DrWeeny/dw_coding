"""
This script is used to store deformer relationship and maps. (mostly for texture deformer)
"""
from __future__ import division

import getpass
import maya.cmds as cmds
import maya.utils as mu
import os
import re
from itertools import chain
from pathlib import Path


import json
from typing import Any, Dict, Optional, List


from collections import defaultdict
from dw_maya.dw_maya_utils.dw_maya_data import merge_two_dicts
import dw_maya.dw_decorators as dwdeco

def save_json(file_path: str, data: Dict[str, Any], indent=4, defer=False) -> bool:
    """
    Save data to a JSON file, optionally deferring to run when Maya is idle.

    Args:
        file_path (str): Path where the JSON file will be saved.
        data (dict): Dictionary to be stored in JSON format.
        indent (int): JSON indentation level.
        defer (bool): If True, save the JSON file when Maya is idle.
    Returns:
        bool: True if successful, False otherwise.
    """
    if defer:
        mu.executeDeferred(_write_json, file_path, data, indent)
        return True
    return _write_json(file_path, data, indent)

def _write_json(file_path: str, data: dict, indent=4) -> bool:
    """Helper function to write JSON data to file."""
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w') as json_file:
            json.dump(data, json_file, indent=indent)
        return True
    except Exception as e:
        print(f"Error saving JSON to {file_path}: {e}")
        return False


def load_json(path: str) -> Optional[Dict[str, Any]]:
    """
    Load and return data from a JSON file.

    Args:
        path (str): Path to the JSON file.
    Returns:
        Optional[Dict[str, Any]]: Loaded dictionary from the JSON file, or None if loading fails.
    """
    path = Path(path)
    if not path.exists():
        print(f"Error: File {path} does not exist.")
        return None

    try:
        with path.open('r') as fp:
            return json.load(fp)
    except Exception as e:
        print(f"Error loading JSON from {path}: {e}")
        return None


def update_json(key: str, value: Any, path: str) -> bool:
    """
    Add or update a key-value pair in an existing JSON file.

    Args:
        key (str): Key to add or update in the JSON file.
        value (Any): Value to associate with the key.
        path (str): Path to the JSON file.
    Returns:
        bool: True if the update was successful, False otherwise.
    """
    path = Path(path)
    if not path.exists():
        print(f"Error: File {path} does not exist.")
        return False

    try:
        data = load_json(path) or {}
        data[key] = value
        return save_json(str(path), data)
    except Exception as e:
        print(f"Error updating JSON at {path}: {e}")
        return False


def save_json_safely(file_path: str, data: dict, indent=4):
    """
    Write JSON data to a file in a thread-safe manner for Maya.

    Args:
        data (dict): Data to write to JSON.
        file_path (str): Path to the JSON file.
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure directory exists

    with file_path.open('w') as json_file:
        json.dump(data, json_file, indent=indent)

def merge_nested_dict(dict1, dict2):
    """
    Recursively merge two dictionaries, where values from `dict2` override those in `dict1`.
    If a value is a dictionary in both `dict1` and `dict2`, it will be merged recursively.
    Otherwise, values from `dict2` overwrite `dict1`.

    Args:
        dict1 (dict): Base dictionary to merge into.
        dict2 (dict): Dictionary to merge, overriding or adding to `dict1`.

    Returns:
        dict: A new dictionary with merged values.
    """
    merged = dict1.copy()  # Make a copy of dict1 to avoid modifying it directly

    for key in dict2:
        if key in merged:
            if isinstance(merged[key], dict) and isinstance(dict2[key], dict):
                # Recursively merge if both are dictionaries
                merged[key] = merge_nested_dict(merged[key], dict2[key])
            else:
                # If one of the values is not a dict, replace the existing value
                merged[key] = dict2[key]
        else:
            # Key only exists in dict2, add it to the result
            merged[key] = dict2[key]

    return merged

def merge_json(file_path: str, new_data: dict, indent=4, defer=False) -> bool:
    """
    Merge new data into an existing JSON file.

    Args:
        file_path (str): Path to the JSON file.
        new_data (dict): Dictionary to merge with the existing data.
        indent (int): JSON indentation level.
        defer (bool): If True, merge and save JSON when Maya is idle.
    Returns:
        bool: True if successful, False otherwise.
    """
    if defer:
        mu.executeDeferred(_merge_and_save_json, file_path, new_data, indent)
        return True
    return _merge_and_save_json(file_path, new_data, indent)

def _merge_and_save_json(file_path: str, new_data: dict, indent=4) -> bool:
    """Helper function to merge data into an existing JSON file and save it."""
    path = Path(file_path)
    try:
        if path.exists():
            current_data = load_json(str(path)) or {}
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            current_data = {}

        # Merge and save
        merged_data = merge_nested_dict(current_data, new_data)
        return save_json(str(path), merged_data, indent)
    except Exception as e:
        print(f"Error merging JSON at {file_path}: {e}")
        return False

@dwdeco.acceptString('deformer_list')
def get_list_of_deformer_weights(deformer_list: List[str]) -> Dict[str, Dict]:
    """
    Accept a list of deformers or a single deformer (using the @acceptString decorator)
    and return a dictionary of deformer weights.

    :param deformer_list: A list of deformer names.
    :return: A dictionary with the deformer weights.
    """
    defomer_weights_dict = {}

    # Loop over each deformer in the list
    for deformer in deformer_list:
        deformer_weights = get_deformer_weights(deformer)
        defomer_weights_dict = merge_two_dicts(defomer_weights_dict, deformer_weights)

    return defomer_weights_dict


def get_deformer_weights(deformer: str) -> dict:
    """
    Get a dictionary containing all weights for a given deformer by index.

    :param deformer: str - The name of the deformer.
    :return: dict - The key is 'deformerName_deformerType_index_meshTransform', and the value is a list of weight values.
    """
    # Attribute to query for the deformer
    attr = 'weightList'

    # Get the indices of multi-attributes (connections) on the weight list
    connection_indices = cmds.getAttr(f'{deformer}.{attr}', multiIndices=True)

    # Determine the deformer type (e.g., 'skinCluster', 'cluster', etc.)
    deformer_type = cmds.nodeType(deformer)

    # Dictionary to store weights for each connection
    connection_dict = {}

    for index in connection_indices:
        # Find the mesh connected to the output geometry at the current index
        connected_shape = cmds.listConnections(f'{deformer}.outputGeometry[{index}]', sh=True)

        if connected_shape:
            # Get the number of vertices in the connected shape
            num_vertices = cmds.polyEvaluate(connected_shape[0], vertex=True)

            # Fetch the weights for this particular index
            weights = cmds.getAttr(f'{deformer}.{attr}[{index}].weights[0:{num_vertices - 1}]')

            # Format the key: 'deformer_deformerType_index_connectedShape'
            key = f'{deformer}_{deformer_type}_{index}_{connected_shape[0]}'

            # Store the weights in the dictionary
            connection_dict[key] = weights

    return connection_dict


def get_folder(custom_path=None):
    """
    Returns a folder path for storing files. If a custom path is provided, it returns that path.
    If no custom path is provided and a Maya scene is open, it defaults to a subfolder in the Maya scene directory.

    Args:
        custom_path (str, optional): If provided, returns this as the folder path. Must start with '/'.

    Returns:
        str or bool: A valid folder path as a string, or False if no valid path is found.
    """

    # Check if the current Maya file is saved (exists in the file system)
    fullpath = cmds.file(q=1, loc=1)
    is_in_file = fullpath != 'unknown'

    user = getpass.getuser()

    # If no custom path is provided, return a default folder in the scene directory
    if not custom_path and is_in_file:
        # Default folder structure in the current scene's directory
        scene_dir = os.path.dirname(fullpath)
        rig_data = os.path.join(scene_dir, 'json', user)

        # Create the folder if it doesn't exist
        if not os.path.exists(rig_data):
            os.makedirs(rig_data)

        return rig_data

    # If a custom path is provided, ensure it starts and ends with '/'
    elif custom_path:
        if custom_path.startswith('/'):
            if not custom_path.endswith('/'):
                custom_path += '/'
            return custom_path
        else:
            return False

    # If no valid scene is open and no custom path is provided
    return False


# create the folder tree
def make_dir(path=str):
    """
    create all the path folder tree
    :return: path string
    """
    if not os.path.exists(path):
        os.makedirs(path)
    return path


# save the deformer dictionnary
def saveDeformerJson(name: str, myWeightsDic: dict, fpath=None):
    """
    Save a deformer weights dictionary to a JSON file.

    Args:
        name (str): The name of the JSON file (without extension).
        myWeightsDic (dict): The dictionary containing deformer weights.
        fpath (str, optional): Custom folder path. If not provided, defaults to project folder.

    Returns:
        str: The full file path of the saved JSON file.
    """

    # Get the folder path (either custom or default)
    folder = get_folder(fpath)

    # Create the folder if it doesn't exist
    path = make_dir(folder)

    # Create the full path for the JSON file
    file_fullpath = os.path.join(path, f'{name}.json')

    # Save the JSON file
    save_json(file_fullpath, myWeightsDic)

    print(f'Successfully saved the deformer file: {name} at {folder}')

    return file_fullpath


# load the deformer dictionnary
def loadDeformerJson(_file: str):
    """
    Load a deformer weights dictionary from a JSON file.

    Args:
        _file (str): The full file path or name of the JSON file (without extension).

    Returns:
        dict or None: The loaded deformer weights dictionary or None if the file is not found.
    """

    # If the provided _file is a full path
    if os.path.exists(_file) and _file.endswith('.json'):
        if os.path.exists(_file):
            return load_json(_file)
        else:
            cmds.warning('json file path missing to load deformer :\n{}'.format(_file))
    elif not '/' in _file:
        # If the file path is just a name (without a full path), look in the default folder
        folder = get_folder()
        # Ensure the filename has no extension, then build the full path
        if '.' in _file:
            _file = _file.split('.')[0]
        file_fullpath = os.path.join(folder, f'{_file}.json')
        if os.path.exists(file_fullpath):
            return load_json(file_fullpath)
        else:
            cmds.warning(f'JSON file not found at path: {file_fullpath}')

    else:
        cmds.warning(f'Invalid file path or unsupported file format: {_file}')


# fuction to set the deformer weights, one connection index at the time
def setDeformerWeights(deformerName: str, weights_list: list, connection_index=0, target_checker=None):
    """
    Set the deformer weights for a specific connection index.

    Args:
        deformerName (str): Name of the deformer (e.g. skinCluster, lattice, etc.).
        weights_list (list of float): The list of weights to apply.
        connection_index (int): The index of the connection (e.g., the geometry influenced).
        target_checker (str, optional): The target mesh to ensure the weights are applied to the correct geometry.

    Returns:
        None
    """
    # Get the number of weights
    nb = len(weights_list)

    # TODO : how goes namespace
    # Check for target_checker to determine connection index dynamically
    if target_checker:
        # List all connected geometries
        meshes_in = cmds.listConnections('{}.outputGeometry[:]'.format(deformerName))

        # Check if the target_checker is in the connected geometries
        if target_checker in meshes_in:
            # Find the corresponding connection index for the target geometry
            con_id = cmds.listConnections('{}.inMesh'.format(target_checker), p=True)

            for ci in con_id:
                if ci.startswith(deformerName):
                    # Extract the connection index from the connection string (e.g., outputGeometry[0])
                    connection_index = int(re.search(r'\[(\d+)\]', ci).group(1))
                    break
        else:
            cmds.warning(f"Target checker '{target_checker}' not found in {deformerName}'s connected geometries.")
            return

    # Set the weights on the deformer at the specified connection index
    try:
        cmds.setAttr('{}.weightList[{}].weights[0:{}]'.format(deformerName, connection_index, nb - 1),
                     *weights_list, size=nb)
    except Exception as e:
        cmds.warning(f"Error setting weights on deformer '{deformerName}': {str(e)}")


# apply all the weights from json
def setDeformersFromJson(_file=None):
    """
    Apply deformer weights from a JSON file.

    Args:
        _file (str): The path to the JSON file that contains the deformer weights.

    Raises:
        RuntimeError: If the file path is not specified or the regular expression search fails.
    """

    if _file:
        myDic = loadDeformerJson(_file)
    else:
        cmds.error('specify either -shortName or -fullpath flags')

    # Regular expression to capture 'deformer_Name'_'indexNumber'_'shape_name'
    pattern = re.compile(r'^(\w+)_(\w+)_(\d+)_(\w+)$')

    for k, weights in myDic.items():
        match = pattern.search(k)

        if not match:
            cmds.warning(f"Skipping key '{k}' - does not match the expected pattern.")
            continue

        # Extract the relevant data from the match groups
        deformer = match.group(1)
        node_type = match.group(2)  # Not currently used
        index = int(match.group(3))  # Convert index to integer
        targetMesh = match.group(4)

        # Apply the deformer weights
        try:
            setDeformerWeights(deformer, weights, index, targetMesh)
            print(f"Applied weights to deformer '{deformer}' on '{targetMesh}' at index {index}.")
        except Exception as e:
            cmds.warning(
                f"Failed to apply weights to deformer '{deformer}' on '{targetMesh}' at index {index}: {str(e)}")

# if there is not the deformer, create it
def createDeformersFromJson(_file=None, remap={}):
    """
    Create deformers from a JSON file, if they don't already exist.

    Args:
        _file (str): Path to the JSON file containing the deformer data.
        remap (dict): A dictionary for remapping target meshes, if needed.

    Returns:
        list: A list of deformer names that were processed.
    """
    if not _file:
        cmds.error('Specify either -shortName or -fullpath flags')

    # Load the deformer weights dictionary from the JSON file
    myDic = loadDeformerJson(_file)

    # Regular expression to capture 'deformer_Name'_'indexNumber'_'shape_name'
    pattern = re.compile(r'^(\w+)_(\w+)_(\d+)_(\w+)$')

    deformer_list = {}


    for key in myDic.keys():
        match = pattern.search(key)
        if not match:
            cmds.warning(f"Skipping key '{key}' - does not match expected pattern.")
            continue

        deformer, node_type, index, targetMesh = match.group(1), match.group(2), match.group(3), match.group(4)

        # Remap the target mesh if necessary
        if targetMesh in remap:
            targetMesh = remap[targetMesh]

        # Group deformer information by deformer name
        if deformer in deformer_list:
            deformer_list[deformer].append([index, targetMesh])
        else:
            deformer_list[deformer] = [[index, targetMesh]]
            deformer_list[f'{deformer}-type'] = node_type

    # Create the deformers if they do not exist
    created_deformers = []

    for deformer, targets in deformer_list.items():
        if not deformer.endswith('-type'):
            # Sort targets by index
            sorted_targets = [i[1] for i in sorted(deformer_list[deformer], key=lambda x: int(x[0]))]
            node_type = deformer_list.get(f'{deformer}-type')

            if node_type == 'textureDeformer':
                if not cmds.objExists(deformer):
                    node = cmds.textureDeformer(sorted_targets, n=deformer)
                    print(f"Created textureDeformer '{deformer}' on {sorted_targets}")
            else:
                cmds.warning(f"Deformer type '{node_type}' not supported yet for '{deformer}'")

            created_deformers.append(deformer)

    return created_deformers


# ===================================================================================================
# NCLOTH UTILS ======================================================================================
# ===================================================================================================


gAEAttrPresetExcludeAttrs = ["doubleSided",
                             "rotateQuaternionX",
                             "rotateQuaternionY",
                             "rotateQuaternionZ",
                             "rotateQuaternionW",
                             "outStippleThreshold",
                             "face",
                             "boundary",
                             "currentDisplayLayer",
                             "useComponentPivot",
                             "currentRenderLayer",	# layer needs to exist
                             "springStiffness",
                             "springDamping",
                             "springRestLength",
                             "caching",
                             "overridePlayback",
                             "overrideEnabled",
                             "playFromCache",
                             "nodeState"]


gAEAttrPresetExcludeNodeAttrs = [
                                    "timeToUnitConversion.output",	# should be output-only
                                    "unitToTimeConversion.output",
                                    "oceanShader.outFoam",
                                    "solidNoise.outColorR",
                                    "solidNoise.outColorG",
                                    "solidNoise.outColorB",
                                    "solidNoise.outAlpha",
                                    "joint.rotatePivotX",			# normalised, so they affect one another
                                    "joint.rotatePivotY",
                                    "joint.rotatePivotZ",
                                    "hikFKJoint.rotatePivotX",
                                    "hikFKJoint.rotatePivotY",
                                    "hikFKJoint.rotatePivotZ",
                                    "samplerInfo.normalCameraX",	# normalised, so they affect one another
                                    "samplerInfo.normalCameraY",
                                    "samplerInfo.normalCameraZ",
                                    "samplerInfo.rayDirectionX",	# normalised, so they affect one another
                                    "samplerInfo.rayDirectionY",
                                    "samplerInfo.rayDirectionZ",
                                    "airField.maxDistance",		# can be set below their minimum value by presets
                                    "dragField.maxDistance",
                                    "gravityField.maxDistance",
                                    "newtonField.maxDistance",
                                    "radialField.maxDistance",
                                    "turbulenceField.maxDistance",
                                    "uniformField.maxDistance",
                                    "volumeAxisField.maxDistance",
                                    "vortexField.maxDistance",
                                    "torusField.maxDistance",
                                    "FurFeedback.realUSamples",	# dynamic/internal, affected by other attributes
                                    "FurFeedback.realVSamples",
                                    "globalStitch.updateSampling", # reset by the 'sampling' attribute
                                    "fluidShape.controlPoints.xValue",
                                    "fluidShape.controlPoints.yValue",
                                    "fluidShape.controlPoints.zValue",
                                    "fluidShape.weights",
                                    "fluidShape.seed",
                                    "stroke.pathCurve.samples", # because these depend on the actual curve thats connected
                                    "stroke.pathCurve.opposite",
                                    "cpStitcher.outputPropertyChangeNotify",
                                    "cpStitcher.outputCreaseAngleChangeNotify",
                                    "nCloth.collisionDamp",
                                    "nCloth.collisionDampMap",
                                    "nCloth.collisionDampPerVertex",
                                    "nCloth.collisionDampMapType",
                                    "nCloth.displayThickness",
                                    "nCloth.numDampingIterations",
                                    "nCloth.numSelfCollisionIterations",
                                    "nCloth.numSelfCollisionSubcycles",
                                    "nCloth.sphereTree",
                                    "nCloth.numStretchIter",
                                    "nCloth.maxStretchIter",
                                    "nCloth.stretchSubcycles",
                                    "nCloth.numBendIter",
                                    "nCloth.linksTension",
                                    "nCloth.numShearIter",
                                    "nCloth.numRigidityIterations",
                                    "nCloth.selfCrossoverCheck",
                                    "nCloth.newStretchModel",
                                    "nCloth.selfCollisionThicknessScale",
                                    "nCloth.pressureStrength",
                                    "nCloth.betterVolumeConserve",
                                    "nCloth.maxPressureIter",
                                    "nCloth.solverOverride",
                                    "nCloth.gravity",
                                    "nCloth.gravityDirectionX",
                                    "nCloth.gravityDirectionY",
                                    "nCloth.gravityDirectionZ",
                                    "nCloth.dragOffset",
                                    "nCloth.windSpeed",
                                    "nCloth.windDirectionX",
                                    "nCloth.windDirectionY",
                                    "nCloth.windDirectionZ",
                                    "nCloth.collisionDrag"]

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


@dwdeco.acceptString('nodeName')
def createAttrPreset(nodeName: list, stripNamespace: bool = True) -> dict:
    """
    Derived from a Maya procedure to create attribute presets for the given nodes.

    Args:
        nodeName (list): List of node names to create presets for.
        stripNamespace (bool): Whether to strip namespaces from node names (default: True).

    Returns:
        dict: A nested dictionary with node attributes and their corresponding values.
               Attrs[nodeName]['nodeType'] : The node type.
               Attrs[nodeName][attr] : Attribute values.
    """

    Attrs = {}

    for n in nodeName:
        # Strip namespace if necessary
        key_n = n.split(':')[-1] if stripNamespace else n

        # Initialize node dictionary
        Attrs[key_n] = {}
        node_type = cmds.nodeType(n)
        Attrs[key_n]['nodeType'] = node_type

        # Fetch string attributes
        string_attrs = cmds.listAttr(n, multi=True, read=True, write=True, visible=True, hasData=True)
        if string_attrs:
            for attr in string_attrs:
                obj_attr = f"{n}.{attr}"
                if cmds.objExists(obj_attr):
                    attr_type = cmds.getAttr(obj_attr, sl=True, type=True)
                    if attr_type == "string":
                        # Skip null string data
                        if not cmds.listAttr(obj_attr, hasNullData=True):
                            Attrs[key_n][attr] = cmds.getAttr(obj_attr)

        # Fetch scalar attributes (floats, ints, bools, enums)
        scalar_attrs = cmds.listAttr(n, multi=True, write=True, scalar=True, visible=True, hasData=True)
        if scalar_attrs:
            for attr in scalar_attrs:
                # Skip invalid attributes for current node type
                if not validNodeTypeAttrForCurrentPreset(node_type, attr):
                    continue
                obj_attr = f"{n}.{attr}"
                Attrs[key_n][attr] = cmds.getAttr(obj_attr)

    return Attrs


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

