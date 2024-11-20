import os
import re
from maya import cmds
import dw_maya.dw_decorators as dwdeco
from typing import Any, Dict, Optional, List
from dw_maya.dw_maya_utils.dw_maya_data import merge_two_dicts
from . import get_folder, make_dir, save_json, load_json

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