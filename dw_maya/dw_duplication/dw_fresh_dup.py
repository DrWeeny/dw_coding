from dw_maya.dw_decorators import acceptString
import maya.cmds as cmds
import dw_maya.dw_maya_utils as dwu

@acceptString('sel')
def freshDuplicate(sel=list):
    """
    Function to duplicate selected objects (mesh, nurbsCurve) while preserving connections temporarily.

    Args:
        sel (list): List of selected objects to duplicate.

    Returns:
        list: List of duplicated objects.
    """
    valid_types = ['mesh', 'nurbsCurve']
    # lsTr always returns transforms; resolve each one's live shape explicitly
    transforms = dwu.lsTr(sel, type=valid_types, ni=True)
    output = []  # To store the resulting duplicated objects
    mass_disconnect = []  # To store connection data for later disconnection

    for transform in transforms:
        relatives = cmds.listRelatives(transform,
                                       shapes=True,
                                       noIntermediate=True,
                                       fullPath=True) or []
        shapes = [s for s in relatives if cmds.nodeType(s) in valid_types]
        if not shapes:
            continue
        shape = shapes[0]
        node_type = cmds.nodeType(shape)  # Get the node type (mesh/nurbsCurve)
        zip_names = dwu.unique_name(transform)[0]  # Get unique name for new object

        # Create the new shape node
        new_node = cmds.createNode(node_type, name='dw_tmp_nodeShape#')
        new_transform = cmds.listRelatives(new_node, parent=True)[0]
        new_name = cmds.rename(new_transform, zip_names[-1])  # Rename to unique name
        new_shape = cmds.listRelatives(new_name, ni=True)[0]  # Get the shape of the new node

        # Get input/output connections
        conn_out = dwu.get_type_io(shape)
        conn_in = dwu.get_type_io(new_shape, io=0)

        # Connect the original shape's output to the new shape's input
        cmds.connectAttr(conn_out, conn_in, force=True)
        mass_disconnect.append([conn_out, conn_in, new_shape])  # Store for disconnection

        output.append(new_name)

    # Refresh Maya viewport after duplication
    cmds.refresh()

    # Disconnect the attributes after evaluation to create a clean duplicate
    for out_conn, in_conn, new_shape in mass_disconnect:
        # Pull the copied shape's output so the data is actually evaluated —
        # refresh() alone does not evaluate in batch mode (empty duplicate)
        cmds.dgeval(dwu.get_type_io(new_shape))
        cmds.disconnectAttr(out_conn, in_conn)

    # Select the newly created duplicates in the scene
    cmds.select(output)

    return output
