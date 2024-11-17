import sys

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
from functools import partial
import maya.OpenMaya as om
import time

import dw_maya.dw_maya_utils as dwu

'dw script : selection of functions to work with keyframed vertices'

class myGlobalsVar:
    def __init__(self):
        self.meshName = ''
        self.meshShape = 'test'
        self.storedSelection = []
        self.PointwValue = []
    
    def _setMeshShape(self):
        self.meshShape = cmds.listRelatives(self.meshName , s=1, ni=1)[0]

    def __str__(self):
        return "member of Test"

varBS = myGlobalsVar()

def pickmyMesh(*args):
    """
    Get the mesh transform node from the current selection.

    Returns:
        str: The name of the transform node containing the selected mesh.

    Raises:
        RuntimeError: If the selection is not a valid mesh.
    """
    # Get the first selected object
    selection = cmds.ls(sl=True, o=True)

    if not selection:
        cmds.error("No object selected. Please select a mesh.")
        return

    my_mesh = selection[0]
    # If the selected object is a mesh, return its parent transform
    if cmds.nodeType(my_mesh) == 'mesh':
        return cmds.listRelatives(my_mesh, p=True)[0]
    # If the selected object is a transform, check if it has a valid mesh shape
    elif cmds.nodeType(my_mesh) == 'transform':
        shape_nodes = cmds.listRelatives(my_mesh, s=True) or []
        if not shape_nodes or cmds.nodeType(shape_nodes[0]) != 'mesh':
            cmds.error("Selected object is not a valid mesh. Please select a mesh.")
            return
        return my_mesh
    else:
        cmds.error('select a mesh')

def sel_vtx(my_shape, select=True, *args):
    """
    Get the list of vertex components for the specified shape.

    Args:
        my_shape (str): The name of the shape node.
        select (bool): If True, selects the vertices in Maya.
        *args: Additional arguments (not used).

    Returns:
        list: A list of vertex components (e.g., ["myShape.vtx[0]", "myShape.vtx[1]", ...]).

    Raises:
        RuntimeError: If the shape node does not exist or is not valid.
    """
    if not cmds.objExists(my_shape):
        raise RuntimeError(f"The specified shape '{my_shape}' does not exist.")

    if cmds.nodeType(my_shape) != "mesh":
        raise RuntimeError(f"The specified shape '{my_shape}' is not a valid mesh.")

    # Select vertices if requested
    if select:
        cmds.select(f"{my_shape}.vtx[:]", r=True)

    # Return the list of vertex components
    return cmds.ls(f"{my_shape}.vtx[:]", flatten=True)


def vtx_set_key(mesh_name='', *args):
    """
    Sets keyframes for all points (vertices) of the given mesh.

    Args:
        mesh_name (str): The name of the mesh whose vertices will have their positions keyed.
        *args: Additional arguments (not used).

    Raises:
        RuntimeError: If the mesh name is not provided or does not exist.
    """
    if not mesh_name:
        raise RuntimeError("Mesh name must be provided.")

    if not cmds.objExists(mesh_name):
        raise RuntimeError(f"The specified mesh '{mesh_name}' does not exist.")

    if cmds.nodeType(mesh_name) != 'mesh':
        raise RuntimeError(f"The specified object '{mesh_name}' is not a valid mesh.")

    # Set keyframes for all vertex positions (px, py, pz)
    cmds.setKeyframe(f"{mesh_name}.pt[:]", attribute=['px', 'py', 'pz'])


def reset_vtx_coord(mesh_name: str, *args):
    """
    Resets the coordinates of all vertices in the specified mesh to (0, 0, 0).

    Args:
        mesh_name (str): The name of the mesh whose vertex coordinates will be reset.
        *args: Additional arguments (not used).

    Raises:
        RuntimeError: If the mesh name is not provided, does not exist, or is not a valid mesh.
    """
    if not mesh_name:
        raise RuntimeError("Mesh name must be provided.")

    if not cmds.objExists(mesh_name):
        raise RuntimeError(f"The specified mesh '{mesh_name}' does not exist.")

    if cmds.nodeType(mesh_name) != 'mesh':
        raise RuntimeError(f"The specified object '{mesh_name}' is not a valid mesh.")

    # Get the total number of vertices
    vertex_count = cmds.polyEvaluate(mesh_name, vertex=True)

    # Create a flattened list of zeros for all vertex coordinates
    values = [0] * (vertex_count * 3)

    # Set the vertex points to (0, 0, 0)
    cmds.setAttr(f"{mesh_name}.pnts[:]", *values, type='float3')


def reset_sel_vtx_coord(mesh_name: str, *args):
    """
    Resets the coordinates of the selected vertices in the specified mesh to (0, 0, 0).

    Args:
        mesh_name (str): The name of the mesh containing the selected vertices.
        *args: Additional arguments (not used).

    Raises:
        RuntimeError: If the mesh name is not provided or is invalid, or if no vertices are selected.
    """
    if not mesh_name:
        raise RuntimeError("Mesh name must be provided.")

    if not cmds.objExists(mesh_name):
        raise RuntimeError(f"The specified mesh '{mesh_name}' does not exist.")

    if cmds.nodeType(mesh_name) != 'mesh':
        raise RuntimeError(f"The specified object '{mesh_name}' is not a valid mesh.")

    # Get the selected vertices and replace 'vtx' with 'pnts'
    selected_vertices = cmds.ls(sl=True, flatten=True)
    if not selected_vertices:
        raise RuntimeError("No vertices selected.")

    points_attributes = [vtx.replace("vtx", "pnts") for vtx in selected_vertices]

    # Reset each selected vertex to (0, 0, 0)
    for point_attr in points_attributes:
        vertex_count = len(cmds.ls(point_attr, flatten=True))
        values = [0] * (vertex_count * 3)  # Create a flat list of zeros
        cmds.setAttr(point_attr, *values, type="float3")


def transfer_vertex_coord(mesh_name: str, receiver_mesh: str, *args):
    """
    Transfers vertex coordinates from one mesh to another.

    Args:
        mesh_name (str): The name of the source mesh.
        receiver_mesh (str): The name of the target mesh.
        *args: Additional arguments (not used).

    Raises:
        RuntimeError: If the source or receiver mesh is invalid.
    """
    # Get the source mesh shape and transform
    if cmds.nodeType(mesh_name) == 'transform':
        mesh_shape = cmds.listRelatives(mesh_name, shapes=True, fullPath=True)[0]
    else:
        mesh_shape = mesh_name
        mesh_name = cmds.listRelatives(mesh_name, parent=True, fullPath=True)[0]

    if not mesh_shape or cmds.nodeType(mesh_shape) != 'mesh':
        raise RuntimeError(f"The source '{mesh_name}' is not a valid mesh.")

    # Get the receiver mesh shape
    receiver_shape = cmds.listRelatives(receiver_mesh, shapes=True, fullPath=True)
    if not receiver_shape or cmds.nodeType(receiver_shape[0]) != 'mesh':
        raise RuntimeError(f"The receiver '{receiver_mesh}' is not a valid mesh.")

    receiver_shape = receiver_shape[0]

    # Get the vertex attribute names
    source_points = [i.replace('vtx', 'pnts') for i in cmds.ls(f"{mesh_shape}.pnts[:]")]

    if not source_points:
        raise RuntimeError(f"No vertex points found on the source mesh '{mesh_name}'.")

    # Get the vertex coordinates from the source mesh
    vertex_values = cmds.getAttr(source_points)

    # Unpack the nested vertex values into a flat list
    unpacked_values = [value for vertex in vertex_values for value in vertex]

    # Set the vertex coordinates on the receiver mesh
    cmds.setAttr(
        f"{receiver_shape}.pnts[:]",
        *unpacked_values,
        type="float3"
    )


def delete_keys_on_vtx(mesh: str, *args):
    """
    Deletes animation keys on all vertices of the specified mesh.

    Args:
        mesh (str): The name of the mesh whose vertex keys will be deleted.
        *args: Additional arguments (not used).

    Raises:
        RuntimeError: If the mesh is invalid or if no animation keys are found.
    """
    if not cmds.objExists(mesh):
        raise RuntimeError(f"The specified mesh '{mesh}' does not exist.")

    if cmds.nodeType(mesh) != 'mesh':
        raise RuntimeError(f"The specified object '{mesh}' is not a valid mesh.")

    # Get all vertex components of the mesh
    vertex_components = cmds.ls(f"{mesh}.pnts[:]", flatten=True)

    # Build a list of .pntx, .pnty, .pntz attributes for all vertices
    vertex_attributes = [f"{vtx}.pnt{x}" for vtx in vertex_components for x in "xyz"]

    # Find all connected animation curve nodes
    anim_curve_nodes = cmds.listConnections(vertex_attributes, type="animCurve")

    if not anim_curve_nodes:
        cmds.warning(f"No animation keys found on the vertices of '{mesh}'.")
        return

    # Delete the animation curve nodes
    cmds.delete(anim_curve_nodes)

    # Notify the user (optional: play an audio file if process is slow)
    cmds.inViewMessage(
        message=f"Animation keys deleted for {len(vertex_components)} vertices on '{mesh}'.",
        position='midCenter',
        fade=True
    )


def set_key_on_already_keyed(mesh: str, *args):
    """
    Sets keys on vertices that already have animation curves connected.

    Args:
        mesh (str): The name of the mesh to key.
        *args: Additional arguments (not used).

    Raises:
        RuntimeError: If the mesh does not exist or is not valid.
    """
    if not cmds.objExists(mesh):
        raise RuntimeError(f"The specified mesh '{mesh}' does not exist.")

    if cmds.nodeType(mesh) != 'mesh':
        raise RuntimeError(f"The specified object '{mesh}' is not a valid mesh.")

    # Get transform and tweak node
    mesh_transform = cmds.listRelatives(mesh, parent=True)[0]
    tweak_node = cmds.listConnections(mesh, type='tweak')

    # Timing for performance measurements
    time_start = time.time()

    # Collect vertices and ranges based on tweak or direct connections
    if not tweak_node:
        vertex_components = cmds.ls(f"{mesh}_pnts_*__pntx", flatten=True)
        vtx_indices = [
            int(vtx.split('_')[-3])
            for vtx in vertex_components
            if cmds.listConnections(vtx) == [mesh_transform]
        ]
    else:
        vertex_components = cmds.ls("tweak*_vlist_*__xVertex", flatten=True)
        anim_curves = cmds.listConnections(tweak_node, type='animCurve')
        vtx_indices = [int(anim.split('_')[-3]) for anim in anim_curves][0::3]

    # Optimize vertex ranges
    vtx_ranges = dwu.create_maya_ranges(vtx_indices)

    # Generate the list of vertex attributes to key
    list_to_key = [f"{mesh}.pt[{index}]" for index in vtx_ranges]

    connection_check_time = round(time.time() - time_start, 3)

    # Set keyframes for the positions
    cmds.setKeyframe(list_to_key, attribute=['px', 'py', 'pz'])

    time_elapsed = round(time.time() - time_start, 3)

    # Display timing and performance metrics
    message = (
        f"Number of vertices keyed: {len(list_to_key)} // "
        f"Connection check time: {connection_check_time} sec // "
        f"Total time elapsed: {time_elapsed} sec"
    )
    om.MGlobal.displayInfo(message)

    # Optional audio notification for long processes
    if time_elapsed > 3:
        pass  # Add audio notification logic if required


def set_key_on_point_with_value(mesh, *args):
    """
    Sets keyframes on vertices of a mesh with non-zero coordinates.

    Args:
        mesh (str): The name of the mesh whose vertices will be keyed.
        *args: Additional arguments (not used).

    Raises:
        RuntimeError: If the mesh is invalid or does not exist.
    """
    if not cmds.objExists(mesh):
        raise RuntimeError(f"The specified mesh '{mesh}' does not exist.")

    if cmds.nodeType(mesh) != 'mesh':
        raise RuntimeError(f"The specified object '{mesh}' is not a valid mesh.")

    # Get the transform and shape nodes
    mesh_transform = cmds.listRelatives(mesh, parent=True)[0]

    # Timing for performance measurement
    time_start = time.time()

    # Determine points to process
    if '.' not in mesh:
        # Full mesh: select all points
        points = cmds.ls(f"{mesh}.pnts[:]", flatten=True)
        selection = None
    else:
        # Specific selection
        selection = cmds.ls(sl=True)
        points = [sel.replace('vtx', 'pnts') for sel in selection]
        points = cmds.ls(points, flatten=True)

    # Extract non-zero vertex values
    non_zero_indices = []
    for i, point in enumerate(points):
        value = cmds.getAttr(point)
        if value != (0, 0, 0):
            non_zero_indices.append(i)

    # Optimize vertex ranges
    vtx_ranges = dwu.create_maya_ranges(non_zero_indices)

    # Generate the list of vertex attributes to key
    list_to_key = [f"{mesh}.pt[{index}]" for index in vtx_ranges]

    connection_check_time = round(time.time() - time_start, 3)

    # Set keyframes for the positions
    cmds.setKeyframe(list_to_key, attribute=['px', 'py', 'pz'])

    time_elapsed = round(time.time() - time_start, 3)

    # Display performance metrics
    message = (
        f"Number of vertices keyed: {len(list_to_key)} // "
        f"Coord check time: {connection_check_time} sec // "
        f"Total time elapsed: {time_elapsed} sec"
    )
    om.MGlobal.displayInfo(message)

    # Optional audio notification for long processes
    if time_elapsed > 3:
        # Replace `playAudio()` with your preferred notification logic
        cmds.inViewMessage(message="Keyframe operation completed.", position="midCenter", fade=True)


def ui_deleteKeysOnVtx(mesh, *args):
    delete_keys_on_vtx(mesh)
    reset_sel_vtx_coord(mesh)


def tmp_selection_stored(*args):
    varBS.storedSelection = cmds.ls(sl=True)


def tmp_pick_selection_stored(*args):
     cmds.select(varBS.storedSelection, r=1)


def ui_picker(*args):
    varBS.meshName = pickmyMesh()
    cmds.textFieldButtonGrp(uiDic['meshPick'], e=1, text=varBS.meshName)
    varBS._setMeshShape()
    varBS.PointwValue = []


def ui_force_refresh(funtion, *args):
    funtion(varBS.meshShape)


def ui_force_selection(funtion, *args):
    funtion(varBS.meshShape, 1) 


def ui_force_transfer(funtion, *args):
    funtion(varBS.meshShape, cmds.ls(sl=True)[0])   
  

uiDic = {}
uiDic['width'] = 200

uiDic['keyingFunc'] = [vtx_set_key, set_key_on_already_keyed, set_key_on_point_with_value]
uiDic['keyingFunc_niceName'] = ['Set Key on Vtx', 'Set Key on already keyed vtx', 'Set Key on vtx with values']

def PkF_showUI():
    if cmds.window("Points_Keyframing", exists = True):
        cmds.deleteUI("Points_Keyframing")
    window = cmds.window("Points_Keyframing",h=50 ,w=30, s=False,t="Points Keyframing UI")
    first_layout = cmds.columnLayout(rs=5)
    
    uiDic['meshPick'] = cmds.textFieldButtonGrp( label='Mesh Name', text=varBS.meshName, buttonLabel="Pick Mesh", bc=ui_picker )
    
    cmds.separator()
    
    cmds.button(label ='Select All Vtx', c=partial(ui_force_selection, sel_vtx))

    cmds.separator( w=uiDic['width'], height=20, style='out' )

    second_layout = cmds.rowLayout(nc=len(uiDic['keyingFunc']*2), p=first_layout)
    for my_function in zip(uiDic['keyingFunc'],uiDic['keyingFunc_niceName']):
        cmds.button(label = my_function[1], c=partial(ui_force_refresh, my_function[0]))
        cmds.separator(w=8, style='none')


    thirdLayout = cmds.columnLayout(rs=5, p=first_layout)
    cmds.button(label='Reset Vtx Transf', c=partial(ui_force_refresh, reset_vtx_coord))

    cmds.separator( w=uiDic['width'], height=20, style='out' )

    #cmds.button(label ='Set Key on Vtx', c=partial(vtxSetKey, varBS.meshShape))
    cmds.button(label ='Reset Selected Vtx Transf', c=partial(ui_force_refresh, reset_sel_vtx_coord))

    cmds.separator( w=uiDic['width'], height=20, style='out' )

    cmds.button(label ='Tmp Sel Storage', c= tmp_selection_stored)
    cmds.button(label ='Pick Tmp Storage', c= tmp_pick_selection_stored)
    cmds.button(label ='Transfer vtx position To mesh selected', annotation='pick the target mesh only',
                c= partial(ui_force_transfer, transfer_vertex_coord))
    cmds.button(label ='Delete All keys on vtx', c=partial(ui_force_refresh, ui_deleteKeysOnVtx))
    
    cmds.showWindow( window )
    
#showUI()