import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from maya import cmds, mel
from dw_maya.dw_decorators import acceptString
import dw_maya.dw_maya_utils as dwu
from .dw_nx_mel import *


@acceptString('selection')
def add_pfx_to_hsys(selection):
    """ add a pfx by eval mel

    Args:
        selection (list): nodes

    Notes:
        TODO convert mel
    """
    for i in selection:
        cmds.select(i)
        mel.eval('addPfxToHairSystem;')


def conform_curves(curves, ext='crv', clean_shape=True, clean_set=True, clean_hist=True):
    """
    Clean the input/output curves, sets, intermediate shapes, and suffix.

    Args:
        curves (list): List of nurbsCurve transforms or shapes.
        ext (str): Suffix for curve renaming, default is "_crv".
        clean_shape (bool): Delete intermediate shapes if True.
        clean_set (bool): Remove curves from any sets if True.
        clean_hist (bool): Delete history of the curves if True.

    Returns:
        list: List of conformed curves.
    """
    output = []
    curves_sh = cmds.ls(curves, dag=True, type='nurbsCurve', long=True)
    curves_tr = cmds.listRelatives(curves_sh, p=True, f=True)

    # Clean intermediate shapes
    if clean_shape:
        if len(curves_tr) == len(curves_sh):
            curves_sh_ni = cmds.ls(curves_sh, ni=True, dag=True, type='nurbsCurve', long=True)
            if len(curves_sh) != len(curves_sh_ni):
                to_del = list(set(curves_sh) - set(curves_sh_ni))
                cmds.delete(to_del)

            for curve in curves_tr:
                sh = cmds.listRelatives(curve, f=True)
                valid_shapes = [s for s in sh if len(s.split('|')[-1]) == len(s.split('|')[-2]) + 5]
                invalid_shapes = [s for s in sh if s not in valid_shapes]

                if len(valid_shapes) > 1:
                    cmds.delete(valid_shapes[1:])
                if invalid_shapes:
                    cmds.delete(invalid_shapes)

    # Rebuild curves to degree 3
    for curve_sh in cmds.ls(curves, dag=True, type='nurbsCurve'):
        curve_tr = cmds.listRelatives(curve_sh, p=True)[0]
        degree = cmds.getAttr(f"{curve_sh}.degree")

        if degree != 3:
            cmds.rebuildCurve(curve_sh, ch=True, rpo=True, rt=False, kep=True, kt=False, s=False, d=3, tol=0.01)

        # Clean set connections
        if clean_set:
            disconnect_from_sets(curve_sh, curve_tr)

        # Delete history
        if clean_hist:
            cmds.delete(curve_tr, ch=True)

        # Rename with the specified extension
        if isinstance(ext, str) and not curve_tr.endswith(ext):
            curve_tr = cmds.rename(curve_tr, f"{curve_tr}_{ext}")

        output.append(curve_tr)

    return output

def disconnect_from_sets(curve_sh, curve_tr):
    """Helper function to disconnect a curve from any sets."""
    disc = []
    con_set = cmds.listConnections(curve_sh, type='objectSet', p=True)
    if con_set:
        dest_set = [d for d in cmds.listConnections(con_set, d=True) if d.split('.')[0] in curve_sh]
        disc += zip(dest_set, con_set)

    conp_set = cmds.listConnections(curve_tr, type='objectSet', p=True)
    if conp_set:
        destp_set = [d for d in cmds.listConnections(conp_set, p=True) if d.split('.')[0] in curve_tr]
        disc += zip(destp_set, conp_set)

    for out, _input in disc:
        cmds.disconnectAttr(out, _input)


def toNiCurves(sel: list, value: bool = True) -> list:
    """
    Toggle intermediate visibility of selected curves.

    Args:
        sel (list): List of selected objects.
        value (bool): Set to True to hide intermediates, False to reveal.

    Returns:
        list: The current selection for further use (useful for nCloth switch).
    """
    crv_sh = cmds.ls(sel, dag=True, type='nurbsCurve')
    for s in crv_sh:
        cmds.setAttr(f'{s}.intermediateObject', value)

    return sel


@acceptString('surface', 'crvs')
def snap_curves(surface: list, crvs: list, index: int = 0, pivot: bool = True):
    """
    Snap the CVs of curves to the nearest point on a surface.

    Args:
        surface (list): List of surfaces to snap to.
        crvs (list): List of curves to snap.
        index (int): The CV index to snap.
        pivot (bool): Whether to adjust the pivot of the curve.
    """
    _crvs = dwu.lsTr(crvs, dag=True, type='nurbsCurve')
    cvs = [f'{i}.cv[{index}]' for i in _crvs]
    snap_positions = dwu.nearest_uv_on_mesh(surface, cvs, position=True)

    if pivot:
        dwu.change_curve_pivot(_crvs)

    convert_factor = convert_to_cm_factor()

    for cv, snap_position in zip(cvs, snap_positions):
        curve_base = cmds.xform(cv, q=True, ws=True, t=True)
        near_pos = [pos * convert_factor for pos in snap_position[1]]

        cmds.move(near_pos[0] - curve_base[0],
                  near_pos[1] - curve_base[1],
                  near_pos[2] - curve_base[2],
                  cv.split('.')[0], r=True)


def get_index_offset_for_hair(curve: str, for_edge: bool, hair_offsets: list, hair_system_name: list) -> int:
    """
    Calculate the index offset for a hair curve based on its follicle and hair system.

    Args:
        curve (str): The name of the hair curve.
        for_edge (bool): Whether the calculation is for an edge or not.
        hair_offsets (list): The list of offsets for each hair follicle.
        hair_system_name (list): A list containing the hair system name (used as a cache).

    Returns:
        int: The offset index for the specified hair curve.
    """
    offset = 0
    follicle = find_type_in_history(curve, "follicle", future=True, past=True)

    if follicle:
        hsys = find_type_in_history(follicle, "hairSystem", future=True, past=True)

        if hsys:
            hair_con = cmds.connectionInfo(follicle + ".currentPosition", sfd=True)
            obj_comp, index = hair_con[:-1].split('[')
            hair_ind = int(index)

            if hair_ind == 0:
                return 0

            set_cache = False
            start_ind = 0

            # Cache hair system name and initialize hair offsets
            if not hair_system_name:
                hair_system_name.append(hsys)
                hair_offsets.clear()
                set_cache = True
            elif hsys == hair_system_name[0]:
                off_size = len(hair_offsets)
                if hair_ind < off_size:
                    return hair_offsets[hair_ind]
                set_cache = True
                if off_size > 0:
                    start_ind = off_size
                    offset = hair_offsets[-1]

            # Process hair follicles in the hair system
            num_curves = cmds.getAttr(f"{hsys}.inputHair", size=True)
            for i in range(start_ind, num_curves):
                if set_cache:
                    hair_offsets.append(offset)

                connections = cmds.listConnections(f"{hsys}.inputHair[{i}]", sh=True)
                if connections:
                    current_follicle = connections[0]
                    if follicle == current_follicle:
                        break
                    elif cmds.getAttr(f"{current_follicle}.simulationMethod") == 2:
                        # Dynamic hair follicle
                        start_position_con = cmds.listConnections(f"{current_follicle}.startPosition", sh=True)
                        curve_connected = start_position_con[0] if start_position_con else ""

                        if curve_connected:
                            size = cmds.getAttr(f"{curve_connected}.cp", size=True)
                            if size > 1:
                                size = int(size * cmds.getAttr(f"{current_follicle}.sampleDensity"))
                            if for_edge:
                                size -= 1
                            if size > 0:
                                offset += size

    return offset

