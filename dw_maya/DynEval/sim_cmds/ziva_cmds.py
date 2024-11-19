#!/usr/bin/env python
#----------------------------------------------------------------------------#
#------------------------------------------------------------------ HEADER --#

"""
@author:
    abtidona

@description:
    this is a description

@applications:
    - groom
    - cfx
    - fur
"""

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#

# built-in
import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

# internal
from maya import cmds, mel
from collections import defaultdict
from pathlib import Path


# internal

# external
import dw_maya.dw_alembic_utils as dwabc
import dw_maya.dw_presets_io as dw_json
import dw_maya.dw_ziva_utils as dwziva
#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

def ziva_sys() -> defaultdict:

    ziva_dic = defaultdict(dict)
    if 'zSolver' not in cmds.ls(nt=True):
        return {}
    zsolver = cmds.ls(type='zSolver')

    for zs in zsolver:

        a7 = zs.split(':')[0]
        if not ziva_dic[a7]:
            ziva_dic[a7] = defaultdict(list)

        if 'muscle' in zs or 'fascia' in zs:
            ziva_dic[a7]['muscle'].append(zs)
        else:
            ziva_dic[a7]['skin'].append(zs)

    return ziva_dic

def create_cache(file_path: str, nodes: list, time_range: list = None, **kwargs) -> str:
    """
    Exports an Alembic cache for specified nodes over a given time range.

    Args:
        file_path (str): Full path to the Alembic file to create (must end with .abc).
        nodes (list): List of Maya nodes to cache.
        time_range (list, optional): Start and end frame for caching [start, end].
        **kwargs: Additional options for cache export (e.g., samplesPerFrame).

    Returns:
        str: The file path of the created Alembic cache.
    """

    # Validate input
    if not file_path.endswith('.abc'):
        raise ValueError("File path must end with .abc extension.")
    if not nodes or not isinstance(nodes, list):
        raise ValueError("Nodes list cannot be empty and must be of type list.")
    if not time_range or len(time_range) != 2:
        raise ValueError("Time range must be provided as [start, end].")

    # Setup directory and permissions
    file_path = Path(file_path)
    cache_dir = file_path.parent
    dw_json.make_chmod_dir(str(cache_dir), limiter=len(cache_dir.parts) - 4)

    # Export Alembic cache
    try:
        dwabc.exportAbc(
            str(file_path),
            nodes,
            frameRange=time_range,
            samplesPerFrame=kwargs.get("samplesPerFrame", 1)
        )
        # Set file permissions
        os.chmod(file_path, kwargs.get("file_permissions", 0o777))
    except Exception as e:
        cmds.error(f"Failed to create cache: {e}")

    return str(file_path)


def materialize(path: str):
    """
    Imports an Alembic cache from the specified path.

    Args:
        path (str): Path to the Alembic (.abc) file.

    Returns:
        The result of `dwabc.importAbc` function, typically the imported node or None if unsuccessful.
    """
    file_path = Path(path)

    if not file_path.exists() or file_path.suffix != '.abc':
        raise ValueError(f"Invalid path or file type: {path}. Please provide a valid .abc file path.")

    return dwabc.importAbc(str(file_path))


def cache_is_attached(cache_node: str, cache_name: str) -> bool:
    """
    Checks if a cache node is attached to the specified cache name.

    Args:
        cache_node (str): Name of the cache node.
        cache_name (str): Name or path segment of the cache file.

    Returns:
        bool: True if the cache is attached, False otherwise.
    """
    # Ensure cache node exists and is of the correct type
    nnode = cmds.ls(cache_node, type=['AlembicNode', 'rfxAlembicCacheDeformer'])
    if not nnode:
        return False

    # Attributes to check
    filename_extensions = ['abc_File', 'filename']
    attrs = [f"{n}.{ext}" for ext in filename_extensions for n in nnode]
    attrs = cmds.ls(attrs)

    # Check if the cache_name is in any attribute's value
    return any(cache_name in cmds.getAttr(a) for a in attrs)


def assign_cache(abc_target: str, file: str) -> bool:
    """
    Assigns an Alembic file to the specified target attribute.

    Args:
        abc_target (str): The name of the Alembic target attribute.
        file (str): The full path to the Alembic file.

    Returns:
        bool: True if successful, False otherwise.
    """
    if not cmds.objExists(abc_target):
        raise ValueError(f"Target attribute '{abc_target}' does not exist.")

    cmds.setAttr(f"{abc_target}.filename", file, type="string")
    return True



def get_preset(zsolver: str) -> dict:
    """
    Retrieves attribute presets from a Ziva solver.

    Args:
        zsolver (str): The name of the Ziva solver node.

    Returns:
        dict: The attribute preset dictionary.
    """
    zs = dwziva.ZSolver(zsolver)
    return zs.attrPreset(1)


def load_preset(zsolver: str, preset: dict, blend: float = 1.0):
    """
    Loads a preset onto the given Ziva solver with blending.

    Args:
        zsolver (str): The name of the Ziva solver node.
        preset (dict): The preset dictionary to load.
        blend (float): Blend value for the preset, default is 1.0.

    """
    namespace = zsolver.split(':')[0] if ':' in zsolver else ':'
    zs = dwziva.ZSolver(zsolver)
    zs.loadPreset(preset=preset, blend=blend, targ_ns=namespace)
