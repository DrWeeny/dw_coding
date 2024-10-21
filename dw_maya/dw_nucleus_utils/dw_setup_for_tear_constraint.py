import sys, os
import maya.cmds as cmds

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from .dw_nx_mel import *
import dw_maya.dw_maya_utils as dwu

def setup_for_tear_constraint(objects: list, selection: list) -> bool:
    """
    Prepares objects for a tear constraint in an nCloth simulation.

    Args:
        objects (list): List of object names to apply the tear constraint.
        selection (list): List of selected components for tear constraint.

    Returns:
        bool: True if successful, False otherwise.
    """
    new_selection = []

    for obj in objects:
        # Find the nCloth node in the object's history
        n_cloth = find_type_in_history(obj, "nCloth", future=1, past=1)
        if not n_cloth:
            cmds.warning("No nCloth node found.")
            return False

        # Get the output mesh of the nCloth
        out_mesh_connections = cmds.listConnections(f"{n_cloth}.outputMesh", shapes=True)
        if not out_mesh_connections:
            cmds.warning("No output mesh connected to nCloth.")
            return False
        out_mesh_node = out_mesh_connections[0]

        # Get the input mesh of the nCloth
        in_mesh_connections = cmds.listConnections(f"{n_cloth}.inputMesh", shapes=True)
        if not in_mesh_connections:
            cmds.warning("No input mesh connected to nCloth.")
            return False
        in_mesh_node = in_mesh_connections[0]

        if cmds.nodeType(in_mesh_node) != "mesh":
            cmds.warning("Input mesh is not of type 'mesh'.")
            return False

        obj_components = []
        tforms = dwu.lsTr(obj)
        obj_tform = tforms[0]
        obj_comp = obj_tform + "."
        in_mesh_comp = in_mesh_node + "."

        # Process selection to find matching components
        for sel in selection:
            if sel.startswith(obj_comp):
                obj_components.append(sel.replace(obj_tform, in_mesh_node))
            elif sel.startswith(in_mesh_comp):
                obj_components.append(sel)

        if obj_components:
            # Handle intermediate object flag
            intermediate = cmds.getAttr(f"{in_mesh_node}.intermediateObject")
            if intermediate:
                cmds.setAttr(f"{in_mesh_node}.intermediateObject", False)

            # Determine component type (vertex, edge, face)
            comp_type = "v"
            if obj_components[0].split('.')[-1].startswith("e["):
                comp_type = "e"
            elif obj_components[0].split('.')[-1].startswith("f["):
                comp_type = "f"

            # Convert selection to edges if needed
            if comp_type != "e":
                old_selection = cmds.ls(sl=True)
                if comp_type == "v":
                    cmds.ConvertSelectionToContainedEdges()
                elif comp_type == "f":
                    cmds.ConvertSelectionToEdges()

                new_sel = cmds.ls(flatten=True, sl=True)
                if new_sel:
                    new_comp = []
                    obj_comp = obj + "."
                    for sel in new_sel:
                        if sel.startswith(obj_comp):
                            new_comp.append(sel.replace(obj, in_mesh_node))
                        elif sel.startswith(in_mesh_comp):
                            new_comp.append(str(sel))
                    if new_comp:
                        obj_components = new_comp
                        comp_type = "e"
                    else:
                        cmds.select(old_selection, r=True)
                else:
                    cmds.select(old_selection, r=True)

            # Apply poly split operation based on component type
            cmds.select(clear=True)
            if comp_type == "e":
                cmds.polySplitEdge(obj_components, ch=True)
            else:
                cmds.polySplitVertex(obj_components, ch=True)

            # Adjust bend resistance
            bend_resistance = cmds.getAttr(f"{n_cloth}.bendResistance")
            if bend_resistance > 0.2 and comp_type != "e":
                cmds.ConvertSelectionToEdges()
            elif bend_resistance < 0.2 and comp_type != "v":
                cmds.ConvertSelectionToVertices()

            # Add modified components to the new selection
            new_comp = cmds.ls(flatten=True, sl=True)
            for sel in new_comp:
                new_selection.append(sel.replace(in_mesh_node, obj_tform))

            # Restore intermediate object flag
            if intermediate:
                cmds.setAttr(f"{in_mesh_node}.intermediateObject", True)

        else:
            cmds.polySplitVertex(in_mesh_node, ch=True)
            new_selection.append(obj)

        # Set up poly merge and soft edge nodes if necessary
        if cmds.nodeType(out_mesh_node) != "polyMergeVert":
            merge = cmds.createNode('polyMergeVert')
            soft = cmds.createNode('polySoftEdge')
            cmds.setAttr(f"{merge}.inputComponents", 1, "vtx[*]", type='componentList')
            cmds.setAttr(f"{merge}.distance", 0.001)
            cmds.setAttr(f"{soft}.inputComponents", 1, "e[*]", type='componentList')
            cmds.setAttr(f"{soft}.angle", 180)

            connection = cmds.connectionInfo(f"{n_cloth}.outputMesh", dfs=True)
            cmds.connectAttr(f"{n_cloth}.outputMesh", f"{merge}.inputPolymesh", force=True)
            cmds.connectAttr(f"{merge}.output", f"{soft}.inputPolymesh", force=True)
            cmds.connectAttr(f"{soft}.output", connection[0], force=True)

    cmds.select(new_selection)
    return True
