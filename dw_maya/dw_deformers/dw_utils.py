import sys, os
# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

from maya import cmds, mel

from dw_maya.dw_decorators import acceptString


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

    Valid Flags:
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
        kwargs: Flags that specify the operation to perform. Accepts:
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