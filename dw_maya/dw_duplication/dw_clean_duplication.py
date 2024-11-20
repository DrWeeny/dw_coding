from dw_maya.dw_decorators import acceptString
import maya.cmds as cmds


@acceptString('dupList')
def cleanDuplication(dupList, cTransformations=1, cLayer=1, cSet=1, cShader=1, cExtraAttribute=1, parentRoot=1):
    """
    Cleans up duplicated objects by removing history, freezing transformations, removing from layers, sets, shaders, and extra attributes, and optionally re-parenting to root.

    Args:
        dupList (list): List of duplicated objects.
        cTransformations (int): Flag to freeze transformations.
        cLayer (int): Flag to remove from display layers.
        cSet (int): Flag to remove from object sets.
        cShader (int): Flag to remove shaders and reset to lambert1.
        cExtraAttribute (int): Flag to remove extra user-defined attributes.
        parentRoot (int): Flag to re-parent to world root.

    Returns:
        None
    """
    for dup in dupList:
        # Delete History
        cmds.delete(dup, ch=True)

        # Freeze Transformation
        if cTransformations:
            attrs = ['t', 'r', 's']
            axes = ['x', 'y', 'z']
            output_attrs = ['{}.{}{}'.format(dup, attr, axis) for attr in attrs for axis in axes]
            if [0] * 6 + [1] * 3 != [cmds.getAttr(attr) for attr in output_attrs]:
                for attr in output_attrs:
                    cmds.setAttr(attr, e=True, l=False)
                cmds.makeIdentity(dup, apply=True, t=True, r=True, s=True, n=0, pn=True)

        # Gather current connections and history
        current_connections = cmds.listConnections(dup) or []
        current_history = cmds.listHistory(dup, ac=True) or []

        # Delete Child Nodes that are not valid geometry (mesh, nurbsCurve)
        shape_nodes = cmds.ls(dup, dag=True, type=['mesh', 'nurbsCurve'], ni=True)
        shape_nodes.append(dup)
        all_nodes = cmds.ls(dup, dag=True)
        extra_nodes = list(set(all_nodes) - set(shape_nodes))
        if extra_nodes:
            cmds.delete(extra_nodes)

        # Remove from Display Layers
        if cLayer:
            display_layers = [conn for conn in current_connections if cmds.nodeType(conn) == 'displayLayer']
            for layer in display_layers:
                cmds.disconnectAttr(layer + '.drawInfo', dup + '.drawOverride')

        # Remove from Object Sets
        if cSet:
            object_sets = [conn for conn in current_connections if cmds.nodeType(conn) == 'objectSet']
            for obj_set in object_sets:
                inst_obj_group = cmds.listConnections(dup + '.instObjGroups', p=True)
                if inst_obj_group:
                    cmds.disconnectAttr(dup + '.instObjGroups', inst_obj_group[0])

        # Remove Shaders and reset to default (lambert1)
        if cShader:
            shading_engines = [h for h in current_history if cmds.nodeType(h) == 'shadingEngine']
            for shading_engine in shading_engines:
                if shading_engine != 'initialShadingGroup':
                    shader_connections = cmds.listConnections(cmds.listRelatives(dup, shapes=True), p=True)
                    for shader_conn in shader_connections:
                        if shader_conn.startswith(shading_engine):
                            try:
                                cmds.disconnectAttr(cmds.listConnections(shader_conn, p=True)[0], shader_conn)
                            except:
                                cmds.disconnectAttr(shader_conn, cmds.listConnections(shader_conn, p=True)[0])

            # Assign lambert1
            cmds.hyperShade(dup, assign='lambert1')

            # Delete groupId nodes associated with shaders
            shader_inputs = cmds.listConnections(cmds.listRelatives(dup, shapes=True), p=True)
            if shader_inputs:
                group_ids = [gid.split('.')[0] for gid in shader_inputs if cmds.nodeType(gid) == 'groupId']
                if group_ids:
                    cmds.delete(group_ids)

        # Remove Extra Attributes
        if cExtraAttribute:
            sel = cmds.ls(dup, dag=True)
            for s in sel:
                custom_attrs = cmds.listAttr(s, ud=True) or []
                for attr in custom_attrs:
                    try:
                        cmds.setAttr('{}.{}'.format(s, attr), e=True, l=False)
                        cmds.deleteAttr(s, at=attr)
                    except:
                        pass

        # Parent to root if necessary
        if parentRoot:
            if len(cmds.ls(dup, l=True)[0].split('|')) > 2:
                cmds.parent(dup, world=True)
