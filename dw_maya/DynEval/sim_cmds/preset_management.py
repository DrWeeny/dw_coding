import os
import maya.cmds as cmds
import maya.mel as mel
from collections import defaultdict
from operator import itemgetter
import dw_maya.dw_presets_io as dw_json
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_nucleus_utils as dwnx
import dw_maya.dw_duplication as dwdup
import dw_maya.dw_maya_nodes as dwnn
import dw_maya.dw_presets_io as dwpreset
from dw_maya.dw_decorators import acceptString


def save_preset(nxnodes: list, json_file: str) -> bool:
    """
    Saves the preset attributes of specified Maya nodes to a JSON file.

    Args:
        nxnodes (list): List of Maya node names to save presets for.
        json_file (str): Path to the JSON file where the presets will be saved.

    Returns:
        bool: True if saving the preset was successful.

    Raises:
        ValueError: If nxnodes contains non-existent nodes or nodes of unsupported types.
        OSError: If the directory for the JSON file cannot be created.
    """
    # Supported node types for presets
    node_types = ['hairSystem', 'nCloth', 'nRigid', 'dynamicConstraint', 'nucleus', 'follicle']

    # Validate nodes
    valid_nodes = cmds.ls(nxnodes, type=node_types, dag=True, long=True)
    if not valid_nodes:
        raise ValueError(f"No valid nodes of types {node_types} found in the provided list.")

    # Generate attribute dictionary for preset
    attr_dic = dwpreset.createAttrPreset(valid_nodes)
    attr_dic['data_type'] = cmds.ls(valid_nodes, type=node_types)

    # Ensure the directory exists for saving the JSON file
    try:
        dw_json.make_dir(os.path.dirname(json_file))
    except OSError as e:
        raise OSError(f"Failed to create directory for saving JSON file: {e}")

    # Save JSON preset
    dw_json.saveJson(json_file, attr_dic)
    return True


def load_preset(nxnodes: list, json_file: str):
    """
    Loads and applies attribute presets from a JSON file to specified Maya nodes.

    Args:
        nxnodes (list): List of Maya node names to apply presets to.
        json_file (str): Path to the JSON file containing the presets.

    Raises:
        FileNotFoundError: If the specified JSON file does not exist.
        ValueError: If no valid nodes of the supported types are found in `nxnodes`.
    """
    # Supported node types for presets
    node_types = ['hairSystem', 'nCloth', 'nRigid', 'dynamicConstraint', 'nucleus', 'follicle']

    # Filter nodes to include only those of the supported types
    valid_nodes = cmds.ls(nxnodes, type=node_types)
    if not valid_nodes:
        raise ValueError(f"No valid nodes of types {node_types} found in the provided list.")

    # Load the JSON data if the file exists
    if not os.path.isfile(json_file):
        raise FileNotFoundError(f"Preset file '{json_file}' does not exist.")

    data = dw_json.loadJson(json_file)

    # Apply attributes to nodes from JSON data
    for node in valid_nodes:
        source_data = data.get(node)
        if source_data:
            for attr, value in source_data.items():
                # Apply the blend attributes if they exist in the JSON data
                target = node
                dwpreset.blendAttr(node, target, attr, data, blend=1)

    print('Dynamic attributes imported successfully!')

