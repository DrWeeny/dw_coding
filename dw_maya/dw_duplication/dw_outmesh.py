from dw_maya.dw_decorators import acceptString
import maya.api.OpenMaya as om  # API python 2.0
import dw_maya.dw_maya_utils as dwu
from maya import cmds, mel
import re
from . import freshDuplicate, dupMesh
from operator import itemgetter



def dw_delete(mesh, idList):
    """
    Deletes the specified faces from the given mesh using the OpenMaya API.

    :param mesh: The name of the mesh to delete faces from.
    :param idList: A list of face indices to delete.
    :raises RuntimeError: If there is a failure in retrieving the mesh using OpenMaya.
    """
    try:
        # Create a selection list and add the mesh to it
        selectionList = om.MSelectionList()
        selectionList.add(mesh)

        # Get the DAG path of the mesh and retrieve the MFnMesh function set
        nodeDagPath = selectionList.getDagPath(0)
        mfnMesh = om.MFnMesh(nodeDagPath)

        # Delete the specified faces
        for faceId in idList:
            mfnMesh.deleteFace(faceId)

        # Update the mesh surface after modifications
        mfnMesh.updateSurface()

    except Exception as e:
        # Raise a specific runtime error with the mesh name and original exception
        raise RuntimeError(f'Failed to process {mesh}: {e}')

@acceptString('sel')
def outmesh(sel, **kwargs):
    """
    Duplicates the provided mesh or its components and processes them for output.

    :param sel: either component or a mesh name (faces, edges, vertices).
    :param kwargs: optional flags such as 'fresh' to force fresh duplication.
    :return: List of new duplicated meshes or mesh components.
    """

    # Get 'fresh' flag from kwargs, defaulting to False if not present
    fresh = dwu.flags(kwargs, False, 'fresh')

    # Determine if selection is a full mesh or specific components
    obj = list(set(cmds.ls(sel, o=True)))

    # Regex pattern to identify components (faces, edges, vertices)
    p = re.compile(r'\.(f|e|vtx)\[\d{1,}:?\d{1,}?\]')
    test_sel = all([p.search(i) for i in sel])

    # Handle full object selections
    if len(obj) == len(sel):
        obj = sel
    else:
        if not test_sel:
            # Sort selected components to match the original object list
            sel_sorted = []
            for o in obj:
                idx = sel.index(o)
                sel_sorted.append([o, idx])

            obj = [i[0] for i in sorted(sel_sorted, key=itemgetter(1))]

    output = []

    # If selection is not a component (full mesh)
    if not test_sel:
        if fresh:
            new_objs = freshDuplicate(obj)
        else:
            new_objs = dupMesh(obj)

        # Iterate over the original and new meshes to connect their attributes
        for shape, target in zip(obj, new_objs):
            s, t = cmds.listRelatives(shape, target, s=1, ni=1)
            conn_out = dwu.get_type_io(s)
            conn_in = dwu.get_type_io(t, io=0)
            cmds.connectAttr(conn_out, conn_in)
        output += new_objs

    # Handle mesh components (faces, edges, vertices)
    else:
        if p.search(sel[0]):
            toface = cmds.polyListComponentConversion(sel, tf=True)
        else:
            toface = sel

        faceNb = cmds.polyEvaluate(obj[0], f=True)
        allComponents = range(faceNb)
        selComponents = cmds.ls(toface, flatten=True)
        selComponents = [int(re.findall(r'\d+', i)[-1]) for i in selComponents]

        selInverted = list(set(allComponents) - set(selComponents))

        # Duplicate the selected mesh for outmesh processing
        new_mesh = dupMesh(sel[0].split('.')[0])[0]
        shape, target = cmds.listRelatives(sel[0].split('.')[0], new_mesh, s=1, ni=1)
        cmds.connectAttr(f'{shape}.outMesh', f'{target}.inMesh')
        output.append(new_mesh)

        # Delete the unselected faces (invert the selection)
        maya_range = dwu.create_maya_ranges(selInverted)
        selToDel = [f'{new_mesh}.f[{i}]' for i in maya_range]
        cmds.delete(selToDel)

    return output