from maya import cmds, mel

def shrinkWrap(mesh: str, target: str,
               projection: int = 0, closestIfNoIntersection: int = 0,
               reverse: int = 0, bidirectional: int = 0,
               boundingBoxCenter: int = 1, axisReference: int = 0,
               alongX: int = 0, alongY: int = 0, alongZ: int = 0,
               offset: float = 0.0, targetInflation: float = 0.0) -> str:
    """
    Maya python function doesn't work so here it is in python
    Creates a shrink-wrap deformer on the mesh, wrapping it to the target object.
    ChatGPT did reformat the function

    Args:
        mesh (str): The name of the mesh to apply the shrink-wrap deformer on.
        target (str): The target mesh object.
        projection (int, optional): The projection method. Default is 0.
        closestIfNoIntersection (int, optional): Use closest point if no intersection. Default is 0.
        reverse (int, optional): Reverse the deformation. Default is 0.
        bidirectional (int, optional): Use bidirectional projection. Default is 0.
        boundingBoxCenter (int, optional): Use bounding box center. Default is 1.
        axisReference (int, optional): Axis reference for deformation. Default is 0.
        alongX (int, optional): Deform along the X-axis. Default is 0.
        alongY (int, optional): Deform along the Y-axis. Default is 0.
        alongZ (int, optional): Deform along the Z-axis. Default is 0.
        offset (float, optional): Offset for deformation. Default is 0.0.
        targetInflation (float, optional): Target inflation amount. Default is 0.0.

    Returns:
        str: The name of the shrink-wrap deformer node.
    """

    # Get the target mesh shape
    targetMesh = getTargetMesh(target)
    if not targetMesh:
        raise ValueError(f"Target mesh '{target}' not found.")

    # Find the surface of the mesh
    surf = cmds.listRelatives(mesh, path=True)
    surface = surf[0]

    # Create shrink-wrap deformer
    shrinkwrapNode = cmds.deformer(surface, type='shrinkWrap')[0]

    # Set shrink-wrap attributes
    cmds.setAttr(f"{shrinkwrapNode}.projection", projection)
    cmds.setAttr(f"{shrinkwrapNode}.closestIfNoIntersection", closestIfNoIntersection)
    cmds.setAttr(f"{shrinkwrapNode}.reverse", reverse)
    cmds.setAttr(f"{shrinkwrapNode}.bidirectional", bidirectional)
    cmds.setAttr(f"{shrinkwrapNode}.boundingBoxCenter", boundingBoxCenter)
    cmds.setAttr(f"{shrinkwrapNode}.axisReference", axisReference)
    cmds.setAttr(f"{shrinkwrapNode}.alongX", alongX)
    cmds.setAttr(f"{shrinkwrapNode}.alongY", alongY)
    cmds.setAttr(f"{shrinkwrapNode}.alongZ", alongZ)
    cmds.setAttr(f"{shrinkwrapNode}.offset", offset)
    cmds.setAttr(f"{shrinkwrapNode}.targetInflation", targetInflation)

    # Connect target mesh attributes to the shrinkwrap node
    cmds.connectAttr(f"{targetMesh}.worldMesh[0]", f"{shrinkwrapNode}.target")
    cmds.connectAttr(f"{targetMesh}.continuity", f"{shrinkwrapNode}.continuity")
    cmds.connectAttr(f"{targetMesh}.smoothUVs", f"{shrinkwrapNode}.smoothUVs")
    cmds.connectAttr(f"{targetMesh}.keepBorder", f"{shrinkwrapNode}.keepBorder")
    cmds.connectAttr(f"{targetMesh}.boundaryRadius", f"{shrinkwrapNode}.boundaryRadius")
    cmds.connectAttr(f"{targetMesh}.keepHardEdges", f"{shrinkwrapNode}.keepHardEdges")
    cmds.connectAttr(f"{targetMesh}.propagateEdgeHardness", f"{shrinkwrapNode}.propagateEdgeHardness")
    cmds.connectAttr(f"{targetMesh}.keepMapBorders", f"{shrinkwrapNode}.keepMapBorders")

    return shrinkwrapNode


def getTargetMesh(targetTrans: str):
    """
    Retrieves the non-intermediate mesh shape from the given transform node.

    Args:
        targetTrans (str): The name of the transform node to check.

    Returns:
        str: The name of the non-intermediate mesh shape node, or None if not found.
    """
    # Check if the provided transform exists
    if not cmds.objExists(targetTrans):
        print(f"Error: Target transform '{targetTrans}' does not exist.")
        return None

    # Retrieve all shape nodes under the transform
    shape_nodes = cmds.ls(targetTrans, dag=True, shapes=True)

    for shape in shape_nodes:
        # Skip intermediate objects
        if cmds.getAttr(f"{shape}.io"):
            continue

        # Return the first valid mesh
        if cmds.nodeType(shape) == "mesh":
            return shape

    # No valid mesh found
    return None
