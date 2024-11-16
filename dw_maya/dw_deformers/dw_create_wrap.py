from maya import cmds, mel


def createWrap(*args, **kwargs):
    """
    Create a wrap deformer that allows one object to deform based on the shape of another.

    Args:
        objWhoDeforms (str): The object that deforms (the surface).
        objInfluence (str): The object that influences the deformation.

    Kwargs:
        weightThreshold (float): The threshold below which the weights are discarded (default: 0.0).
        maxDistance (float): The maximum distance for the deformation (default: 1.0).
        exclusiveBind (bool): Whether to bind exclusively (default: False).
        autoWeightThreshold (bool): Whether to automatically determine the weight threshold (default: True).
        falloffMode (int): Determines how the falloff is calculated (default: 0).
        name (str): Name of the wrap deformer node.

    Returns:
        list: A list containing the wrap node and the duplicated base shape.
    """

    if len(args) < 2:
        cmds.error("Both surface and influence objects are required.")

    influence = args[1]
    surface = args[0]

    shapes = cmds.listRelatives(influence, shapes=True)
    influenceShape = shapes[0]

    shapes = cmds.listRelatives(surface, shapes=True)
    surfaceShape = shapes[0]

    # create wrap deformer
    weightThreshold = kwargs.get('weightThreshold', 0.0)
    maxDistance = kwargs.get('maxDistance', 1.0)
    exclusiveBind = kwargs.get('exclusiveBind', False)
    autoWeightThreshold = kwargs.get('autoWeightThreshold', True)
    falloffMode = kwargs.get('falloffMode', 0)
    name = kwargs.get('name', None)

    if not name:
        wrapData = cmds.deformer(surface, type='wrap')
    else:
        wrapData = cmds.deformer(surface, type='wrap', name=name)
    wrapNode = wrapData[0]

    # Set wrap deformer attributes
    cmds.setAttr(f'{wrapNode}.weightThreshold', weightThreshold)
    cmds.setAttr(f'{wrapNode}.maxDistance', maxDistance)
    cmds.setAttr(f'{wrapNode}.exclusiveBind', exclusiveBind)
    cmds.setAttr(f'{wrapNode}.autoWeightThreshold', autoWeightThreshold)
    cmds.setAttr(f'{wrapNode}.falloffMode', falloffMode)

    # Connect surface to wrap deformer
    cmds.connectAttr(f'{surface}.worldMatrix[0]', f'{wrapNode}.geomMatrix')

    # Duplicate the influence object as the base object
    base = cmds.duplicate(influence, name=f'{influence}Base')[0]
    baseShape = cmds.listRelatives(base, shapes=True, fullPath=True)[0]
    cmds.hide(base)

    # create dropoff attr if it doesn't exist
    if not cmds.attributeQuery('dropoff', n=influence, exists=True):
        cmds.addAttr(influence, sn='dr', ln='dropoff', dv=4.0, min=0.0, max=20.0)
        cmds.setAttr(influence + '.dr', k=True)

    # if type mesh
    if cmds.nodeType(influenceShape) == 'mesh':
        # create smoothness attr if it doesn't exist
        if not cmds.attributeQuery('smoothness', n=influence, exists=True):
            cmds.addAttr(influence, sn='smt', ln='smoothness', dv=0.0, min=0.0)
            cmds.setAttr(influence + '.smt', k=True)

        # create the inflType attr if it doesn't exist
        if not cmds.attributeQuery('inflType', n=influence, exists=True):
            cmds.addAttr(influence, at='short', sn='ift', ln='inflType', dv=2, min=1, max=2)

        cmds.connectAttr(f'{influenceShape}.worldMesh[0]', f'{wrapNode}.driverPoints[0]')
        cmds.connectAttr(f'{baseShape}.worldMesh[0]', f'{wrapNode}.basePoints[0]')
        cmds.connectAttr(f'{influence}.inflType', f'{wrapNode}.inflType[0]')
        cmds.connectAttr(f'{influence}.smoothness', f'{wrapNode}.smoothness[0]')

    # if type nurbsCurve or nurbsSurface
    if cmds.nodeType(influenceShape) == 'nurbsCurve' or cmds.nodeType(influenceShape) == 'nurbsSurface':
        # create the wrapSamples attr if it doesn't exist
        if not cmds.attributeQuery('wrapSamples', n=influence, exists=True):
            cmds.addAttr(influence, at='short', sn='wsm', ln='wrapSamples', dv=10, min=1)
            cmds.setAttr(influence + '.wsm', k=True)

        cmds.connectAttr(f'{influenceShape}.worldSpace[0]', f'{wrapNode}.driverPoints[0]')
        cmds.connectAttr(f'{baseShape}.worldSpace[0]', f'{wrapNode}.basePoints[0]')
        cmds.connectAttr(f'{influence}.wrapSamples', f'{wrapNode}.nurbsSamples[0]')

    # Connect dropoff attribute
    cmds.connectAttr(f'{influence}.dropoff', f'{wrapNode}.dropoff[0]')

    return [wrapNode, base]


def transferWrapConns(wrapPlugs=[], newNode=''):
    """
    Transfer connections from the current wrap deformer to the new node.
    Derived from MEL command but I've let chatGPT refactor the function
    Args:
        wrapPlugs (list): A list of wrap plugs (connections) to be transferred.
        newNode (str): The node to which connections will be transferred.

    """
    for wrapPlug in wrapPlugs:
        # Get the node and attribute connected to the plug
        wrapNode = cmds.plugNode(wrapPlug)
        wrapAttr = cmds.plugAttr(wrapPlug)

        # Process only driverPoints connections
        if wrapAttr.startswith("driverPoints"):
            # Find connections to meshes
            meshConns = cmds.listConnections(wrapPlug, s=True, p=True, sh=True, type="mesh")

            if meshConns:
                # Transfer the connection to the new node
                meshAttr = cmds.plugAttr(meshConns[0])
                cmds.disconnectAttr(meshConns[0], wrapPlug)
                cmds.connectAttr(f'{newNode}.{meshAttr}', wrapPlug)
