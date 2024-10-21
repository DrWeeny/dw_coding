import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
from dw_maya.dw_decorators import acceptString
import dw_maya.dw_maya_utils as dwu

@acceptString("surface")
def create_follicles(surface: str, uv_input: list = None, uvthreshold: float = 0.05, **kwargs) -> str:
    """
    Creates a follicle on the given surface (mesh or nurbsSurface) based on UV input.

    Args:
        surface (str): The surface on which to create the follicle.
        uv_input (list): UV coordinates [u, v] where the follicle should be created.
        uvthreshold (float): Threshold for adjusting the UV when it is not valid.
        **kwargs: Optional arguments for follicle creation (e.g., name).

    Returns:
        str: Name of the created follicle transform.
    """
    if uv_input is None or len(uv_input) != 2:
        raise ValueError("uv_input must be a list with two elements [u, v].")

    u, v = uv_input
    flags = dwu.Flags(kwargs, None, 'name', 'n', dic={})

    sh = cmds.ls(surface, dag=True, type='shape')
    if not sh:
        raise ValueError(f"Surface {surface} does not exist or does not have a valid shape.")
    sh = sh[0]

    debug = []
    hair = cmds.createNode('follicle', **flags)
    cmds.setAttr(f"{hair}.parameterU", u)
    cmds.setAttr(f"{hair}.parameterV", v)
    hair_dag = cmds.listRelatives(hair, p=True)[0]

    if cmds.objExists(surface):
        ntype = cmds.nodeType(sh)
        cmds.connectAttr(f"{sh}.worldMatrix[0]", f"{hair}.inputWorldMatrix")

        if ntype == "nurbsSurface":
            cmds.connectAttr(f"{sh}.local", f"{hair}.inputSurface")
        elif ntype == "mesh":
            _handle_mesh_follicle(hair, sh, u, v, uvthreshold, debug)

        cmds.connectAttr(f"{hair}.outTranslate", f"{hair_dag}.translate")
        cmds.connectAttr(f"{hair}.outRotate", f"{hair_dag}.rotate")
        cmds.setAttr(f"{hair_dag}.translate", lock=True)
        cmds.setAttr(f"{hair_dag}.rotate", lock=True)
    else:
        cmds.setAttr(f"{hair}.startDirection", 1)

    return hair_dag


def _handle_mesh_follicle(hair: str, mesh: str, u: float, v: float, uvthreshold: float, debug: list):
    """Handles follicle creation on a mesh surface, including UV validation and approximation."""
    current_uv_set = cmds.polyUVSet(mesh, q=True, currentUVSet=True)
    cmds.setAttr(f"{hair}.mapSetName", current_uv_set[0], type="string")

    if not cmds.getAttr(f"{hair}.validUv"):
        _adjust_uv_on_invalid_mesh(hair, mesh, u, v, uvthreshold, debug)


def _adjust_uv_on_invalid_mesh(hair: str, mesh: str, u: float, v: float, uvthreshold: float, debug: list):
    """Adjusts the UV coordinates when the follicle is created on a mesh with invalid UVs."""
    vertices = cmds.ls(f"{mesh}.vtx[:]", fl=True)
    uvpack = [cmds.polyListComponentConversion(vtx, tuv=True)[0] for vtx in vertices]

    distances = []
    for vtx, uvmap in zip(vertices, uvpack):
        uv_values = cmds.polyEditUV(uvmap, query=True)
        for i in range(0, len(uv_values), 2):
            uv_out = uv_values[i:i + 2] + [0]  # UV plus 0 for z-coordinate
            dist = dwu.mag([u, v, 0], uv_out)
            distances.append([vtx, uvmap, dist])

    sorted_distances = sorted(distances, key=lambda x: x[2])
    near_vertices = [item[0] for item in sorted_distances[:4]]

    # Get the centroid of the nearby vertices
    vert_positions = cmds.xform(near_vertices, q=True, t=True)
    x, y, z = (
        sum(vert_positions[0::3]) / len(near_vertices),
        sum(vert_positions[1::3]) / len(near_vertices),
        sum(vert_positions[2::3]) / len(near_vertices)
    )

    nearest_uv = dwu.nearest_uv_on_mesh([vertices[0].split('.')[0]], [[x, y, z]], uvs=True)[0]
    vector2d = [(nearest_uv[1][0] - u) * uvthreshold, (nearest_uv[1][1] - v) * uvthreshold]

    u_approx = u + vector2d[0]
    v_approx = v + vector2d[1]

    cmds.setAttr(f"{hair}.parameterU", u_approx)
    cmds.setAttr(f"{hair}.parameterV", v_approx)

    if not cmds.getAttr(f"{hair}.validUv"):
        debug.append(cmds.listRelatives(hair, p=True)[0])  # Append the hair's transform to debug
