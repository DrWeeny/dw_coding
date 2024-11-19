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


def has_cache(ncloth: str):
    """Check if the given nCloth node has any associated cache files.

    Args:
        ncloth (str): The name of the nCloth shape node.

    Returns:
        list: A list of unique cache nodes connected to the nCloth history,
              or an empty list if none are found.
    """
    nx = dwnn.MayaNode(ncloth)

    # Ensure the node has a shape history
    meshes = cmds.listHistory(nx.sh, f=True) if nx.sh else None
    if not meshes:
        return []

    # List any cacheFile connections, ensuring uniqueness
    cache_nodes = cmds.listConnections(meshes, type='cacheFile')
    return list(set(cache_nodes)) if cache_nodes else []


@acceptString("ncloth")
def delete_caches(ncloth: list, delete_file=None):
    """
    Delete cache nodes associated with the provided nCloth nodes. If `delete_file` is specified,
    delete the entire cache file for each node (feature not yet implemented).

    Args:
        ncloth (list): A list of nCloth nodes.
        delete_file (str, optional): The path of the XML cache file to delete.
                                     **Note**: This feature is currently not implemented.

    Raises:
        Warning: If the `delete_file` feature is invoked, or if no cache nodes are found.
    """
    to_del = []

    # Collect cache nodes from the provided nCloth nodes
    for n in ncloth:
        nx = dwnn.MayaNode(n)
        if not nx.node:
            cmds.warning(f"Please provide a valid nCloth node, found: '{n}'")
            continue

        cache_nodes = nx.playFromCache.lsconnections(type='cacheFile')
        if cache_nodes:
            to_del.extend(set(cache_nodes))

    if not to_del:
        cmds.warning("No cache nodes found to delete.")
        return

    if delete_file:
        cmds.warning("The `delete_file` feature is currently not implemented.")
    else:
        cmds.delete(to_del)


def attach_ncache(filename: str, ncloth: str):
    """
    Attach a cache file to the specified nCloth node.

    Args:
        filename (str): The path to the cache file (e.g., XML).
        ncloth (str): The name of the nCloth node to attach the cache to.

    Returns:
        list: The cache node attached to the nCloth node.

    Raises:
        ValueError: If `filename` or `ncloth` is invalid.
    """
    if not isinstance(filename, str) or not filename:
        raise ValueError(f"Invalid filename: '{filename}'. Must be a non-empty string.")
    if not isinstance(ncloth, str) or not cmds.objExists(ncloth):
        raise ValueError(f"Invalid nCloth node: '{ncloth}' does not exist.")

    nx = dwnn.MayaNode(ncloth)
    nclothshape = nx.sh.split('|')[-1]

    # Attach the cache
    cache_node = dwnx.attach_ncache(filename, nclothshape)
    return cache_node


def cache_is_attached(nxnode: str, cache_name: str) -> bool:
    """
    Check if the specified cache file is connected to the given nCloth or hairSystem node.

    Args:
        nxnode (str): The name of the nCloth or hairSystem node to check.
        cache_name (str): The name of the cache file to verify.

    Returns:
        bool: True if the specified cache is attached to the node, False otherwise.
    Raises:
        ValueError: If nxnode is not a valid nCloth or hairSystem node.
    """
    if not isinstance(nxnode, str) or not cmds.objExists(nxnode):
        raise ValueError(f"Invalid node: '{nxnode}'. Node does not exist.")
    if not isinstance(cache_name, str) or not cache_name:
        raise ValueError("Invalid cache name. Must be a non-empty string.")

    nnode = cmds.ls(nxnode, type=['nCloth', 'hairSystem'])
    if not nnode:
        raise ValueError(f"'{nxnode}' is not an nCloth or hairSystem node.")

    # Get cache file connections and check for matching cache name
    cache_connections = cmds.listConnections(nnode, type='cacheFile') or []
    for cache in set(cache_connections):
        cache_attr = f"{cache}.cacheName"
        if cmds.objExists(cache_attr) and cmds.getAttr(cache_attr) == cache_name:
            return True

    return False


def create_cache(ncloth_shapes: list, cache_dir: str, time_range: list = [], **kwargs) -> list:
    """
    Creates an nCache file for the specified nCloth shapes over a given time range.

    Args:
        ncloth_shapes (list): List of nCloth shape node names to cache.
        cache_dir (str): Directory to save the cache file.
        time_range (list, optional): Start and end frame as [start, end]. Defaults to playback range.
        **kwargs: Additional cache options:
            - fileName (str): Specify cache file name.
            - distribution (str): Cache distribution format, default 'OneFile'.
            - refresh (int): Refresh flag (default is 1).
            - perGeometry (int): Create per-geometry cache files (default is 0).
            - useAsPrefix (int): Use file name as prefix (default is 0).
            - simulationRate (float): Simulation rate (default is 1).
            - sampleMultiplier (int): Sample multiplier (default is 1).
            - doubleToFloat (int): Double-to-float conversion (default is 1).

    Returns:
        list: Created cache file names, or an empty list on failure.

    Raises:
        ValueError: If `ncloth_shapes` or `cache_dir` is invalid, or if `time_range` is incorrectly specified.
    """
    # Validate inputs
    if not isinstance(ncloth_shapes, list) or not all(cmds.objExists(n) for n in ncloth_shapes):
        raise ValueError("ncloth_shapes must be a list of existing nCloth shape nodes.")
    if not isinstance(cache_dir, str) or not cache_dir:
        raise ValueError("cache_dir must be a valid non-empty string.")
    if time_range and (not isinstance(time_range, list) or len(time_range) != 2 or not all(isinstance(i, (int, float)) for i in time_range)):
        raise ValueError("time_range must be a list of two numeric values [start, end].")

    # Set default or provided time range
    feed = {'st': time_range[0] if time_range else cmds.playbackOptions(q=True, min=True),
            'et': time_range[1] if time_range else cmds.playbackOptions(q=True, max=True)}

    # Set additional parameters
    feed.update({
        'format': kwargs.get('distribution', 'OneFile'),
        'refresh': kwargs.get('refresh', 1),
        'singleCache': kwargs.get('perGeometry', 0),
        'prefix': kwargs.get('useAsPrefix', 0),
        'smr': kwargs.get('simulationRate', 1),
        'spm': kwargs.get('sampleMultiplier', 1),
        'doubleToFloat': kwargs.get('doubleToFloat', 1),
    })
    # Optional file name
    if fileName := kwargs.get('fileName'):
        feed['fileName'] = fileName

    # Execute cache command
    try:
        cache_files = cmds.cacheFile(directory=cache_dir, cacheFormat='mcx', cnd=ncloth_shapes, **feed)
    except Exception as e:
        cmds.warning(f"Failed to create cache: {e}")
        return []

    return cache_files


def materialize(mesh: str, cache_path: str) -> str:
    """
    Creates a duplicate of a given mesh and assigns a specified cache file to it.

    Args:
        mesh (str): The name of the mesh transform node to duplicate.
        cache_path (str): Path to the XML cache file.

    Returns:
        str: The name of the newly created mesh transform with cache applied.

    Raises:
        ValueError: If `mesh` is not a valid mesh node or `cache_path` is not a valid file.
        RuntimeError: If the duplication or cache assignment fails.
    """
    # Validate inputs
    if not cmds.objExists(mesh) or cmds.nodeType(mesh) != "transform":
        raise ValueError(f"Provided mesh '{mesh}' is not a valid transform node.")
    if not isinstance(cache_path, str) or not os.path.isfile(cache_path):
        raise ValueError(f"Provided cache_path '{cache_path}' is not a valid file path.")

    # Attempt duplication and cache assignment
    try:
        out = dwdup.dupWCache(mesh, cache_path)
    except Exception as e:
        raise RuntimeError(f"Failed to duplicate and cache mesh '{mesh}': {e}")

    return out


def get_ncloth_mesh(ncloth: str, io: int = 1) -> str:
    """
    Retrieves the connected mesh from an nCloth node, either from its input or output connections.

    Args:
        ncloth (str): The name of the nCloth node.
        io (int, optional): Direction of connection. Defaults to 1.
            - 1: Returns the output mesh connected to the nCloth.
            - 0: Returns the input mesh feeding into the nCloth.

    Returns:
        str: The name of the mesh node associated with the nCloth.

    Raises:
        ValueError: If `ncloth` is not a valid nCloth node or a connected mesh is not found.
    """
    # Validate nCloth node
    if not cmds.objExists(ncloth) or cmds.nodeType(ncloth) != "nCloth":
        raise ValueError(f"Provided nCloth '{ncloth}' is not a valid nCloth node.")

    try:
        if io:
            # Retrieve output mesh history
            hist = cmds.listHistory(f"{ncloth}.outputMesh", lf=False, f=True)
            output_meshes = [i for i in hist if cmds.nodeType(i) == "mesh" and len(i.split(".")) == 1]
            if output_meshes:
                return dwu.lsTr(output_meshes[0], long=True)[0]
        else:
            # Retrieve input mesh history
            input_mesh = next((i for i in cmds.listHistory(ncloth, f=0, bf=1, af=1) if cmds.nodeType(i) == "mesh"), None)
            if input_mesh:
                return input_mesh

        # If no mesh found, raise error
        raise ValueError(f"No connected mesh found for nCloth '{ncloth}' with io={io}.")
    except Exception as e:
        raise RuntimeError(f"An error occurred while retrieving the mesh for nCloth '{ncloth}': {e}")
