from maya import cmds, mel
import re
from dw_maya.dw_decorators import acceptString
from typing import Dict, List, Union, Optional, Literal, Tuple
from dw_logger import get_logger

logger = get_logger()


def get_deformer_weights(deformer_node: str) -> Dict[str, List[float]]:
    """
    Get the weight values from a Maya deformer node's weightList attribute.

    Args:
        deformer_node: Name of the deformer node (e.g., cluster, blendShape, etc.)

    Returns:
        Dictionary containing weight values with key 'mainWeight'
        Example: {'mainWeight': [0.0, 0.5, 1.0, ...]}

    Raises:
        ValueError: If deformer node doesn't exist or has no mesh history
        RuntimeError: If unable to get weights from deformer

    Note:
        This function gets weights from weightList[0].weights[] attribute.
        It automatically determines the vertex range from the connected mesh.
    """
    # Validate input
    if not cmds.objExists(deformer_node):
        raise ValueError(f"Deformer node '{deformer_node}' does not exist")

    try:
        # Find connected mesh using history
        mesh_history = [
            node for node in cmds.listHistory(deformer_node, future=True)
            if cmds.nodeType(node) == "mesh"
        ]

        if not mesh_history:
            raise ValueError(f"No mesh found in history of deformer '{deformer_node}'")

        # Get mesh name (first mesh in history)
        mesh_shape = mesh_history[0]

        # Get mesh transform node
        mesh_transform = cmds.listRelatives(mesh_shape, parent=True)
        if not mesh_transform:
            raise ValueError(f"Cannot find transform node for mesh shape '{mesh_shape}'")

        mesh = mesh_transform[0]

        # Get vertex count and create range string
        vertex_count = cmds.polyEvaluate(mesh, vertex=True)
        weight_range = f"0:{vertex_count - 1}"

    except Exception as e:
        logger.warning(f"Error getting mesh info: {e}")
        # Fallback to full range if mesh info cannot be determined
        weight_range = ":"

    try:
        # Construct weight attribute path
        weight_attr = f'{deformer_node}.weightList[0].weights[{weight_range}]'

        # Get weight values
        weights = cmds.getAttr(weight_attr)
        if weights is None:
            raise RuntimeError(f"Unable to get weights from '{weight_attr}'")

        # Convert to list if single value is returned
        if not isinstance(weights, (list, tuple)):
            weights = [weights]

        return {'weightList': list(weights)}

    except Exception as e:
        raise RuntimeError(f"Error getting weights from deformer '{deformer_node}': {e}")


def get_blendshape_info(blendshape_node: str) -> Dict[
    str, Union[List[float], List[Tuple[int, str]], List[Union[List[float], str]]]]:
    """
    Get comprehensive information about a Maya blendShape deformer.

    Args:
        blendshape_node: Name of the blendShape node

    Returns:
        Dictionary containing:
            - 'weightList': Base weights of the blendShape
            - 'targetName': List of tuples (index, target_name)
            - 'targetsWeight': List of weight arrays for each target

    Raises:
        ValueError: If blendShape node doesn't exist or has no mesh history
        RuntimeError: If unable to get weights or target information
    """
    # Validate input
    if not cmds.objExists(blendshape_node):
        raise ValueError(f"BlendShape node '{blendshape_node}' does not exist")

    if cmds.nodeType(blendshape_node) != "blendShape":
        raise ValueError(f"Node '{blendshape_node}' is not a blendShape deformer")

    try:
        # Find connected mesh
        mesh_history = [
            node for node in cmds.listHistory(blendshape_node, future=True)
            if cmds.nodeType(node) == "mesh"
        ]

        if not mesh_history:
            raise ValueError(f"No mesh found in history of blendShape '{blendshape_node}'")

        # Get mesh transform
        mesh_shape = mesh_history[0]
        mesh_transform = cmds.listRelatives(mesh_shape, parent=True)
        if not mesh_transform:
            raise ValueError(f"Cannot find transform node for mesh shape '{mesh_shape}'")

        mesh = mesh_transform[0]

        # Get vertex count
        vertex_count = cmds.polyEvaluate(mesh, vertex=True)
        weight_range = f"0:{vertex_count - 1}"

        # Get blendShape target information
        target_names = cmds.blendShape(blendshape_node, query=True, target=True) or []
        target_count = len(target_names)

        # Create target indices and names pairs
        targets = list(zip(range(target_count), target_names))

        # Get base weights
        base_weights_attr = f'{blendshape_node}.inputTarget[0].baseWeights[{weight_range}]'
        base_weights = cmds.getAttr(base_weights_attr)

        # Ensure base_weights is a list
        if not isinstance(base_weights, (list, tuple)):
            base_weights = [base_weights] if base_weights is not None else []

        # Get target weights for each target
        target_weights = []
        for target_idx in range(target_count):
            try:
                weights_attr = (f'{blendshape_node}.inputTarget[0].'
                                f'inputTargetGroup[{target_idx}].targetWeights[{weight_range}]')
                weights = cmds.getAttr(weights_attr)

                # Ensure weights is a list
                if not isinstance(weights, (list, tuple)):
                    weights = [weights] if weights is not None else []

                target_weights.append(list(weights))

            except Exception as e:
                logger.warning(f"Error getting weights for target {target_idx}: {e}")
                target_weights.append('error')

        return {
            'weightList': list(base_weights),
            'targetName': targets,
            'targetsWeight': target_weights
        }

    except Exception as e:
        raise RuntimeError(f"Error getting blendShape info for '{blendshape_node}': {e}")


def set_deformer_weights(deformer: str,
                         weights: List[float],
                         target_type: Literal['deformer', 'blendshape'] = 'deformer',
                         **kwargs) -> None:
    """
    Set weights on a deformer node, supporting both regular deformer weights
    and blendShape base weights.

    Args:
        deformer: Name of the deformer node
        weights: List of weight values to set
        target_type: Type of weights to set:
            - 'deformer': regular deformer weightList (e.g., cluster, softMod)
            - 'blendshape': blendShape base weights

    Kwargs:
        invert (bool): Invert the weights before setting them (1.0 becomes 0.0)

    Raises:
        ValueError: If deformer doesn't exist or weights list is empty
        RuntimeError: If setting weights fails

    Example:
        # Set weights on a cluster
        set_deformer_weights("cluster1", weights, "deformer")

        # Set inverted weights on a blendShape
        set_deformer_weights("blendShape1", weights, "blendshape", invert=True)
    """
    if not weights:
        raise ValueError("Weights list cannot be empty")

    if not cmds.objExists(deformer):
        raise ValueError(f"Deformer '{deformer}' does not exist")

    try:
        # Process weights
        processed_weights = weights.copy()  # Create a copy to avoid modifying original

        # Invert weights if requested
        if kwargs.get('invert', False):
            processed_weights = [1.0 - w for w in processed_weights]
            logger.debug(f"Inverted weights for {deformer}")

        weight_count = len(processed_weights)
        weight_range = f"0:{weight_count - 1}"

        # Construct attribute path based on target type
        if target_type == 'deformer':
            attr_path = f'{deformer}.weightList[0].weights[{weight_range}]'
        elif target_type == 'blendshape':
            attr_path = f'{deformer}.inputTarget[0].baseWeights[{weight_range}]'
        else:
            raise ValueError(f"Invalid target_type: {target_type}")

        # Set the weights
        cmds.setAttr(attr_path, *processed_weights, size=weight_count)

        logger.debug(f"Successfully set {weight_count} weights on {deformer}")

    except Exception as e:
        raise RuntimeError(f"Failed to set weights on '{deformer}': {e}")



def blend_this_frame(frameTag="frmXXX_VX"):
    """
    utility to blend a mesh to another only on one frame
    used for shot sculpting
    """
    my_sel = cmds.ls(sl=1)

    bs_name = cmds.blendShape(my_sel[0:-1], my_sel[-1])

    for i in my_sel[0:-1]:
        myMeshFrame = int(i.split('_')[-1])

        cmds.setKeyframe(bs_name, attribute=i.split(':')[-1], t=myMeshFrame, v=1)
        cmds.setKeyframe(bs_name, attribute=i.split(':')[-1], t=[myMeshFrame - 1, myMeshFrame + 1], v=0)

        cmds.setKeyframe(i, attribute='visibility', t=myMeshFrame, v=1)
        cmds.setKeyframe(i, attribute='visibility', t=[myMeshFrame - 1, myMeshFrame + 1], v=0)


def blendThisAttr(frameSpacing=int(1), *args):
    """
    used to freeze a maya attribute
    """
    from dw_maya.dw_channelbox_utils import get_channels
    my_sel = get_channels()

    myMeshFrame = int(cmds.currentTime(q=1))  # currentFrame

    for i in my_sel:
        cmds.setKeyframe(i.split('.')[0], attribute=i.split('.')[-1], t=myMeshFrame, v=cmds.getAttr(i))
        cmds.setKeyframe(i.split('.')[0], attribute=i.split('.')[-1],
                         t=[myMeshFrame - frameSpacing, myMeshFrame + frameSpacing], v=0)

def blendshape_add_target():
    """
    Add a target on a blendshape
    """
    bs_node = cmds.ls(sl=True)[0]
    myMeshBlendshaped = cmds.ls(sl=True)[-1]
    meshToAdd = cmds.ls(sl=True)[1]

    insIndex = len(cmds.blendShape(bs_node, q=1, t=1))

    cmds.blendShape(bs_node, edit=True, t=(myMeshBlendshaped, insIndex, meshToAdd, 1))


def get_deformers_weights(deformers: Union[str, List[str]]) -> Dict[str, List[float]]:
    """
    Get weights from multiple deformers and combine them into a single dictionary.

    Args:
        deformers: Single deformer name or list of deformer names

    Returns:
        Dictionary mapping deformer names to their weight lists
        Example: {'cluster1': [0.0, 0.5, 1.0], 'cluster2': [1.0, 0.5, 0.0]}

    Raises:
        ValueError: If input is empty or contains invalid deformers
        RuntimeError: If unable to get weights from any deformer

    Example:
        weights = get_deformers_weights(['cluster1', 'cluster2'])
        weights = get_deformers_weights('blendShape1')
    """
    if not deformers:
        raise ValueError("No deformers provided")

    # Convert single string to list for consistent processing
    if isinstance(deformers, str):
        deformers = [deformers]

    weights_dict = {}
    errors = []

    # Process each deformer
    for deformer in deformers:
        try:
            if not cmds.objExists(deformer):
                raise ValueError(f"Deformer '{deformer}' does not exist")

            # Get weights using the existing get_deformer_weights function
            deformer_data = get_deformer_weights(deformer)

            # Add to main dictionary
            weights_dict[deformer] = deformer_data.get('mainWeight', [])

            logger.debug(f"Successfully got weights from {deformer}")

        except Exception as e:
            errors.append(f"Error processing {deformer}: {str(e)}")
            logger.warning(f"Failed to get weights from {deformer}: {e}")
            continue

    # Report any errors that occurred
    if errors:
        logger.warning(f"Encountered {len(errors)} errors while processing deformers:\n"
                       + "\n".join(errors))

    if not weights_dict:
        raise RuntimeError("Failed to get weights from any deformers")

    return weights_dict


def get_deformer_indexed_weights(deformer: str, separator: str = "@") -> Dict[str, List[float]]:
    """
    Get all weights for each connection index of a deformer.

    Args:
        deformer: Name of the deformer node
        separator: Character to separate parts in the returned dictionary keys
                  (deformer@type@index@mesh)

    Returns:
        Dictionary mapping connection information to weight lists
        Key format: "{deformer}{sep}{type}{sep}{index}{sep}{mesh}"
        Example: {"cluster1@cluster@0@pCube1": [0.0, 0.5, 1.0]}

    Raises:
        ValueError: If deformer doesn't exist or has no connections
        RuntimeError: If unable to get weights
    """
    if not cmds.objExists(deformer):
        raise ValueError(f"Deformer '{deformer}' does not exist")

    try:
        # Get deformer type
        deformer_type = cmds.nodeType(deformer)
        logger.debug(f"Processing {deformer_type} deformer: {deformer}")

        # Get multi indices of weightList connections
        weight_indices = cmds.getAttr(f'{deformer}.weightList', multiIndices=True)
        if weight_indices is None:
            raise ValueError(f"No weightList connections found on {deformer}")

        weights_dict = {}
        errors = []

        # Process each connection index
        for index in weight_indices:
            try:
                # Get connected mesh shape
                connected_shapes = cmds.listConnections(
                    f'{deformer}.outputGeometry[{index}]',
                    source=False,
                    destination=True,
                    shapes=True
                )

                if not connected_shapes:
                    logger.warning(f"No mesh connected to {deformer} at index {index}")
                    continue

                mesh_shape = connected_shapes[0]

                # Get vertex count for connected mesh
                vertex_count = cmds.polyEvaluate(mesh_shape, vertex=True)
                if vertex_count is None:
                    raise ValueError(f"Cannot get vertex count for {mesh_shape}")

                # Get weights
                weights_attr = f'{deformer}.weightList[{index}].weights[0:{vertex_count - 1}]'
                weights = cmds.getAttr(weights_attr)

                # Ensure weights is a list
                if not isinstance(weights, (list, tuple)):
                    weights = [weights] if weights is not None else []

                # Create key using separator
                key = f"{deformer}{separator}{deformer_type}{separator}{index}{separator}{mesh_shape}"
                weights_dict[key] = list(weights)

                logger.debug(f"Got {len(weights)} weights for {key}")

            except Exception as e:
                error_msg = f"Error processing index {index}: {str(e)}"
                errors.append(error_msg)
                logger.warning(error_msg)
                continue

        if errors:
            logger.warning(f"Encountered {len(errors)} errors while processing {deformer}")

        if not weights_dict:
            raise RuntimeError(f"Failed to get any weights from {deformer}")

        return weights_dict

    except Exception as e:
        raise RuntimeError(f"Failed to process deformer '{deformer}': {e}")


def set_deformer_indexed_weights(
        deformer: str,
        weights: List[float],
        connection_index: int = 0,
        target_mesh: Optional[str] = None
) -> None:
    """
    Set weights for a specific connection index of a deformer.
    Can automatically find the correct connection index for a target mesh.

    Args:
        deformer: Name of the deformer node
        weights: List of weight values to set
        connection_index: Index of the deformer connection (default: 0)
        target_mesh: Optional mesh name to automatically find its connection index

    Raises:
        ValueError: If deformer doesn't exist or inputs are invalid
        RuntimeError: If setting weights fails

    Note:
        This function doesn't work with blendShape deformers.
        Use set_deformer_weights() with type='blendshape' instead.
    """
    if not weights:
        raise ValueError("Weights list cannot be empty")

    if not cmds.objExists(deformer):
        raise ValueError(f"Deformer '{deformer}' does not exist")

    if cmds.nodeType(deformer) == "blendShape":
        raise ValueError("This function doesn't support blendShape deformers. "
                         "Use set_deformer_weights() instead.")

    try:
        # If target mesh is specified, find its connection index
        if target_mesh:
            if not cmds.objExists(target_mesh):
                raise ValueError(f"Target mesh '{target_mesh}' does not exist")

            # Get all connected meshes
            connected_meshes = cmds.listConnections(
                f'{deformer}.outputGeometry[*]',
                source=False,
                destination=True
            ) or []

            if target_mesh not in connected_meshes:
                raise ValueError(f"Target mesh '{target_mesh}' is not connected to {deformer}")

            # Find the connection index for the target mesh
            found_index = False
            connections = cmds.listConnections(
                f'{target_mesh}.inMesh',
                source=True,
                destination=False,
                plugs=True
            ) or []

            for connection in connections:
                if connection.startswith(deformer):
                    match = re.search(r'\[(\d+)\]', connection)
                    if match:
                        connection_index = int(match.group(1))
                        found_index = True
                        logger.debug(f"Found connection index {connection_index} "
                                     f"for {target_mesh}")
                        break

            if not found_index:
                raise ValueError(f"Could not find connection index for {target_mesh}")

        # Validate connection index
        if not isinstance(connection_index, int) or connection_index < 0:
            raise ValueError(f"Invalid connection index: {connection_index}")

        # Set the weights
        weight_count = len(weights)
        weight_attr = f'{deformer}.weightList[{connection_index}].weights[0:{weight_count - 1}]'

        cmds.setAttr(weight_attr, *weights, size=weight_count)

        logger.debug(f"Successfully set {weight_count} weights on {deformer} "
                     f"at index {connection_index}")

    except Exception as e:
        raise RuntimeError(f"Failed to set weights on '{deformer}': {e}")

def is_deformer(node: str) ->bool:
    """
    Check if the given node is a deformer by looking at its inherited node types.

    Args:
        node (str): The name of the node to check.

    Returns:
        bool: True if the node is a deformer, False otherwise.
    """
    # Get the inherited node types of the given node
    test = cmds.nodeType(node, inherited=True) or []

    # Return True if 'geometryFilter' is in the list of inherited types, otherwise False
    return "geometryFilter" in test

@acceptString('object_list')
def maya_edit_sets(deformer_name: str, object_list: list, **kwargs):
    """
    Add or remove objects from a set connected to the given deformer.

    Args:
        deformer_name (str): The name of the deformer.
        object_list (list): List of objects to add or remove.
        **kwargs: Optional flags for Maya's `cmds.sets` function (e.g., 'add', 'remove').

    Valid flags:
        - add: Adds objects to the set.
        - remove: Removes objects from the set.
        - addElement: Adds a single element to the set.
        - rm: Alias for remove.

    Example:
        maya_edit_sets("skinCluster1", ["pCube1"], add=True)
    """
    # Accepted flags
    flags_accepted = ['remove', 'rm', 'add', 'addElement']

    # Ensure the deformer exists
    if not cmds.objExists(deformer_name):
        cmds.error(f"Deformer '{deformer_name}' does not exist.")
        return

    # Get the object set connected to the deformer
    object_set = cmds.listConnections(deformer_name, type="objectSet")

    if not object_set:
        cmds.error(f"No object set found connected to the deformer '{deformer_name}'.")
        return
    object_set = object_set[0]  # The first connected set is used

    # Find the first valid flag in kwargs
    flag = None
    for fa in flags_accepted:
        if kwargs.get(fa):
            flag = fa
            break

    # If a valid flag is found, update the kwargs and edit the set
    if flag:
        kwargs[flag] = object_set
        cmds.sets(object_list, **kwargs)
    else:
        cmds.error("No valid flag ('add', 'remove', 'addElement', 'rm') provided in kwargs.")

def editDeformer(**kwargs):
    """
    Based on selection :
    Edit a deformer by adding or removing objects from the set it affects.

    Args:
        kwargs: flags that specify the operation to perform. Accepts:
            - remove: Removes objects from the set.
            - rm: Alias for remove.
            - add: Adds objects to the set.
            - addElement: Adds a single element to the set.

    Usage:
        Select the objects and the deformer in Maya, then run the command with a flag:
            editDeformer(add=True)
            editDeformer(remove=True)
    """
    flags_accepted = ['remove', 'rm', 'add', 'addElement']

    # Ensure that a valid flag is provided in the kwargs
    if not (set(kwargs.keys()) & set(flags_accepted)):
        print(f"Error: One flag must be set from this list: {flags_accepted}")
        return

    # Check that something is selected
    sel = cmds.ls(sl=True)
    if not sel or len(sel) < 2:
        print("Error: Please select at least one object and a deformer.")
        return

    # Objects to add/remove and the deformer
    objs = sel[:-1]
    deformer_sel = sel[-1]

    # Retrieve the history of the deformer and find any deformers in its history
    history = cmds.listHistory(deformer_sel)
    filter_deformers = [i for i in history if is_deformer(i)]

    if not filter_deformers:
        print(f"Error: No deformers found in the history of {deformer_sel}.")
        return

    # Use the first deformer found in the history and edit the set
    maya_edit_sets(filter_deformers[0], objs, **kwargs)


def editMembership(deformer=None):
    """
    Launch Maya's EditMembershipTool for the specified deformer.

    Args:
        deformer (str, optional): The name of the deformer. If no deformer is provided, the tool will be launched on the currently selected objects.

    Usage:
        editMembership("myCluster")
    """
    if deformer:
        # Select the parent object of the deformer
        parent_object = cmds.listRelatives(deformer, parent=True)
        if parent_object:
            cmds.select(parent_object[0], replace=True)
        else:
            cmds.warning(f"Deformer '{deformer}' has no parent.")
    else:
        cmds.warning("No deformer provided. Please select a deformer.")

    # Launch Maya's Edit Membership Tool
    mel.eval("EditMembershipTool")


def paintWeights(deformer=None):
    """
    Launch Maya's Paint Weights Tool for the specified deformer.

    Args:
        deformer (str, optional): The name of the deformer. This could be a softMod or a cluster.

    Usage:
        paintWeights("mySoftMod")
        paintWeights("myCluster")
    """
    if not deformer:
        cmds.warning("No deformer provided. Please specify a deformer.")
        return

    defNode = None
    geo = None

    # Check for softMod deformer
    if cmds.listConnections(deformer, type="softMod"):
        defNode = cmds.listConnections(deformer, type="softMod")
        if defNode:
            geo = cmds.softMod(defNode[0], query=True, geometry=True)
            if geo:
                cmds.select(geo)
                mel.eval(f'artSetToolAndSelectAttr( "artAttrCtx", "softMod.{defNode[0]}.weights" );')
                mel.eval('artAttrInitPaintableAttr;')

    # Check for cluster deformer
    elif cmds.listConnections(deformer, type="cluster"):
        defNode = cmds.listConnections(deformer, type="cluster")
        if defNode:
            geo = cmds.cluster(defNode[0], query=True, geometry=True)
            if geo:
                cmds.select(geo)
                mel.eval(f'artSetToolAndSelectAttr( "artAttrCtx", "cluster.{defNode[0]}.weights" );')
                mel.eval('artAttrInitPaintableAttr;')

    # Handle case where deformer is not found or not supported
    else:
        cmds.warning(f"No supported deformer (softMod or cluster) found for '{deformer}'.")


def create_noise_texture_deformer(
        deformer_name: str = "fence_textDeformer",
        preset_multiplier: float = 1.0) -> Dict[str, str]:
    """
    Create and connect a noise texture setup for a texture deformer.
    Sets up place2dTexture, noise nodes, and animation expressions.

    Args:
        deformer_name: Name of the texture deformer to connect to
        preset_multiplier: Multiplier for animation speed presets

    Returns:
        Dictionary containing created node names
        Example: {'place2d': 'noise1Place2d', 'noise': 'noise1'}

    Raises:
        ValueError: If texture deformer doesn't exist
        RuntimeError: If node creation or connection fails
    """
    if not cmds.objExists(deformer_name):
        raise ValueError(f"Texture deformer '{deformer_name}' does not exist")

    try:
        # Create nodes
        place2d = cmds.createNode('place2dTexture', name='noise1Place2d')
        noise = cmds.createNode('noise', name='noise1')

        # Make connections
        connections = [
            (f'{place2d}.outUV', f'{noise}.uvCoord'),
            (f'{place2d}.outUvFilterSize', f'{noise}.uvFilterSize'),
            (f'{noise}.outColor', f'{deformer_name}.texture')
        ]

        for src, dst in connections:
            cmds.connectAttr(src, dst, force=True)

        # Define attribute settings
        attributes = {
            f'{deformer_name}.pointSpace': 0,
            f'{deformer_name}.direction': 0,
            f'{deformer_name}.strength': 2.5,
            f'{noise}.amplitude': 0.584,
            f'{noise}.ratio': 1,
            f'{noise}.threshold': 0,
            f'{noise}.frequency': 0.5,
            f'{noise}.frequencyRatio': 1,
            f'{noise}.inflection': 0,
            f'{noise}.density': 1,
            f'{noise}.spottyness': 0.5,
            f'{noise}.sizeRand': 0.214,
            f'{noise}.randomness': 0.312,
            f'{noise}.numWaves': 5,
            f'{noise}.implode': 0.221,
            f'{noise}.implodeCenterU': 0.5
        }

        # Set attributes
        for attr, value in attributes.items():
            try:
                cmds.setAttr(attr, value)
            except Exception as e:
                logger.warning(f"Failed to set {attr}: {e}")

        # Create animation expressions
        expressions = [
            (noise, 'time', 10 * preset_multiplier),
            (place2d, 'offsetU', 1 * preset_multiplier),
            (place2d, 'offsetV', 15 * preset_multiplier)
        ]

        for node, attr, speed in expressions:
            expression = f'{node}.{attr} = time * {speed};'
            cmds.expression(object=node, string=expression)

        logger.info(f"Successfully created noise texture setup for {deformer_name}")
        return {'place2d': place2d, 'noise': noise}

    except Exception as e:
        raise RuntimeError(f"Failed to create noise texture setup: {e}")
