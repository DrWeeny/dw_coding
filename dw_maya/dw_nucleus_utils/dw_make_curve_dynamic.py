import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from maya import cmds, mel
from .dw_nx_mel import *
import dw_maya.dw_maya_utils as dwu
from dw_maya.dw_decorators import acceptString
from. dw_add_active_to_nsystem import add_active_to_nsystem
from .dw_attach_nobject_to_hairsystem import attach_nobject_to_hair
from .dw_make_collide import set_collider_preset

def create_hair_curve_node(hsys: str, surface: str, u: float, v: float, uvapprox: list, num_cvs: int,
                           do_out: bool, do_start: bool, do_rest: bool, is_passive: bool,
                           start_curve: str, length: float, hsysgrp: str, hsysout_hairgrp: str,
                           sim_type: int) -> str:
    """
    Create a hair follicle and connect it to a surface or mesh.

    Args:
        hsys (str): Hair system node name.
        surface (str): Surface or mesh to attach the follicle.
        u (float): U coordinate for UV attachment.
        v (float): V coordinate for UV attachment.
        uvapprox (list): Fallback UV approximation if the initial values are invalid.
        num_cvs (int): Number of control vertices for the curve.
        do_out (bool): Whether to create output curves for the follicle.
        do_start (bool): Whether to create a start curve for the follicle.
        do_rest (bool): Whether to create a rest curve for the follicle.
        is_passive (bool): Whether the follicle should be passive.
        start_curve (str): Name of a curve to use for the start position.
        length (float): Length of hair curve to create (ignored if start curve is provided).
        hsysgrp (str): Parent group for follicles.
        hsysout_hairgrp (str): Parent group for output hair curves.
        sim_type (int): 1 = dynamic, 2 = static.

    Notes:
        This is a low level mel routine that sets up a hair follicle
        and manages all the attachments. It is used by the "Create Hair" menu as
        well as "make selected curves dynamic". It is useful if one wishes to
        custom script creation of hairs or dynamic curves. Any strings passed
        into this routine should be the names of existing shape nodes of the
        type required by the arguments. In the argument $hsys requires a valid
        hairSystem node, however the other stringscan be set to "" and
        the hairsystem node will either not implement that node or create one.
        The argument end_hairsys_id is a simple 1 element int array that is
        used to keep track of the index we connect to between calls,
        so that it is faster when looping over large numbers of hairs.
        Initialize the first element of this array to zero, and
        if you are creating follicles in a loop then keep this initialization
        outside of the loop.
        For examples of the usage of this call look at createHair.mel.

    Returns:
        str: Name of the follicle's transform node.
    """

    if not hsys:
        return ""

    hair = cmds.createNode('follicle')
    cmds.setAttr(f"{hair}.parameterU", u)
    cmds.setAttr(f"{hair}.parameterV", v)
    hair_dag = cmds.listRelatives(hair, p=True)[0]

    if surface and cmds.objExists(surface):
        ntype = cmds.nodeType(surface)
        cmds.connectAttr(f"{surface}.worldMatrix[0]", f"{hair}.inputWorldMatrix")

        if ntype == "nurbsSurface":
            cmds.connectAttr(f"{surface}.local", f"{hair}.inputSurface")
        elif ntype == "mesh":
            cmds.connectAttr(f"{surface}.outMesh", f"{hair}.inputMesh")
            current_uvset = cmds.polyUVSet(surface, q=True, currentUVSet=True)[0]
            cmds.setAttr(f"{hair}.mapSetName", current_uvset, type="string")

            if not cmds.getAttr(f"{hair}.validUv") and uvapprox:
                cmds.setAttr(f"{hair}.parameterU", uvapprox[0])
                cmds.setAttr(f"{hair}.parameterV", uvapprox[1])

        cmds.connectAttr(f"{hair}.outTranslate", f"{hair_dag}.translate")
        cmds.connectAttr(f"{hair}.outRotate", f"{hair_dag}.rotate")
        cmds.setAttr(f"{hair_dag}.translate", lock=True)
        cmds.setAttr(f"{hair_dag}.rotate", lock=True)
    else:
        cmds.setAttr(f"{hair}.startDirection", 1)

    if do_start:
        if start_curve and cmds.objExists(start_curve):
            _type = cmds.nodeType(start_curve)
            if _type == "nurbsCurve":
                do_start_curve = True
            elif _type == "curveFromSurfaceCoS":
                do_start_curve, cos = True, True
        else:
            do_start_curve = False

        if not do_start_curve:
            flags = polylineflags(num_cvs, length)
            if not flags:
                cmds.delete(hair)
                return ""

    if do_rest:
        flags = polylineflags(num_cvs, length)
        if not flags:
            cmds.delete(hair)
            return ""

    if hsysgrp:
        hair_dag = cmds.parent(hair_dag, hsysgrp, relative=True)[0]
        # Group the follicles into the passed in parent node.
        # -relative here is simply in the hope that
        # this might be slightly more efficient

    curve = ""
    if do_start:
        if do_start_curve:
            curve = start_curve if cos else cmds.listRelatives(start_curve, p=True)[0]
            hair_dag = cmds.parent(hair_dag, cmds.listRelatives(curve, p=True)[0], relative=True)[0]
        else:
            curve = cmds.curve(**flags)
            display_type = "passive" if is_passive else "start"
            mel.eval(f'initHairCurveDisplay "{curve}" "{display_type}";')

        if cos:
            cmds.connectAttr(f"{curve}.oc", f"{hair}.startPosition")
        else:
            cmds.connectAttr(f"{curve}.local", f"{hair}.startPosition")
            cmds.connectAttr(f"{curve}.worldMatrix[0]", f"{hair}.startPositionMatrix")

    if do_rest:
        rest = cmds.duplicate(curve, rr=True)[0] if do_start_curve else cmds.curve(**flags)
        mel.eval(f'initHairCurveDisplay "{rest}" "rest";')
        cmds.parent(rest, hair_dag, relative=True)
        cmds.connectAttr(f"{rest}.worldSpace[0]", f"{hair}.restPosition")
        cmds.setAttr(f"{hair}.restPose", 3)

    # Handle simulation method
    if sim_type == 2:
        cmds.setAttr(f"{hair}.simulationMethod", 0)
    elif is_passive:
        cmds.setAttr(f"{hair}.simulationMethod", 1)
    # connect hair to end of hsys array
    # We use the following array so that the last index used can
    # be passed back to the calling routine, so that we
    # minimize searching. The calling routine should set
    # end_hairsys_id to zero on the first call and then
    # and then allow it to track the last free slot.
    # The input hair is a sparce multi and holes can be created
    # when some hairs are deleted. We always try to fill in the holes
    # when creating new hairs.


    # Connect hair to hair system
    hair_index = get_next_free_multi_index(f"{hsys}.inputHair")
    cmds.connectAttr(f"{hair}.outHair", f"{hsys}.inputHair[{hair_index}]")

    if do_out:
        cmds.connectAttr(f"{hsys}.outputHair[{hair_index}]", f"{hair}.currentPosition")
        crv = cmds.createNode('nurbsCurve')
        cmds.connectAttr(f"{hair}.outCurve", f"{crv}.create")
        display_type = "passive" if is_passive else "current"
        mel.eval(f'initHairCurveDisplay "{crv}" "{display_type}";')

        if hsysout_hairgrp:
            crv = cmds.parent(cmds.listRelatives(crv, p=True)[0], hsysout_hairgrp, relative=True)[0]

    return hair_dag


@acceptString('curves')
def makeCurvesDynamic(curves: list, **kwargs) -> dict:
    """
    Converts Maya curves to dynamic hair system curves.

    Args:
        curves (list): List of curve transform nodes to be made dynamic.
        surfaceAttach (list): Mesh or nurbs surface to attach the curves to.
        snapToSurface (int): Whether to snap the curve to the surface.
        matchPosition (int): Whether to rebuild the curve with matching positions.
        doOutputCurves (int): Whether to create output curves.
        nucleus (str): Name of the nucleus node.
        hsysName (str): Name to give to this setup.

    Returns:
        dict: A dictionary containing:
            - 'curves': List of output curves.
            - 'hsys': The hair system node name.
            - 'nucleus': The nucleus node name.
            - 'follicles': List of created follicles (optional).
            - 'nrigids': List of created nRigid nodes (optional).
            - 'debug': List of potential issues (optional).
    """
    # Extract relevant flags from kwargs
    curves_out = dwu.Flags(kwargs, [], 'curves_out')
    surface_attach = dwu.Flags(kwargs, [], 'surfaceAttach')
    snap_to_surface = dwu.Flags(kwargs, 0, 'snapToSurface')
    match_position = dwu.Flags(kwargs, 1, 'matchPosition')
    do_output_curves = dwu.Flags(kwargs, 1, 'doOutputCurves')
    hsys_name = dwu.Flags(kwargs, None, 'hsysName')
    nucleus = dwu.Flags(kwargs, None, 'nucleus')
    do_collide_mesh = dwu.Flags(kwargs, True, 'doCollideMesh')
    uvthreshold = dwu.Flags(kwargs, .05, 'uvthreshold')

    # Initialize variables
    follicles, weird, nrigids = [], [], []
    made_hair_curve = False
    hsys_group, hsys_output_hair_group = "", ""
    uapprox, vapprox = 0, 0

    # Validate and process curves
    curves = cmds.ls(curves, dag=True, type='nurbsCurve', ni=True)
    if not curves:
        cmds.error('No curves provided.')

    surfaces, meshes = [], []
    if surface_attach:
        surfaces = cmds.ls(surface_attach, dag=True, type='nurbsSurface')
        meshes = cmds.ls(surface_attach, dag=True, type='mesh')
    attach_to_surface = surfaces or meshes

    # Setup temporary nodes for closest point on surface/mesh
    surface_cl_pos, mesh_cl_pos, min_u, size_u, min_v, size_v = [], [], [], [], [], []
    if attach_to_surface:
        surface_cl_pos, mesh_cl_pos = setup_closest_point_nodes(surfaces, meshes, min_u, size_u, min_v, size_v)

    # Iterate through curves and process them
    for curve in curves:
        outname = None
        if isinstance(curve, (list, tuple)):
            outname = curve[1]
            curve = curve[0]

        if curve_already_attached(curve):
            continue

        # Create hair system if not already created
        if not made_hair_curve:
            hsys, nucleus, hsys_group, hsys_output_hair_group = setup_hair_system(hsys_name, nucleus, do_output_curves)
            made_hair_curve = True

        # Find surface/mesh to attach and snap curve if necessary
        surf, u, v, near_pos = "", 0, 0, [0, 0, 0]
        near_dist = 10000000.0
        curve_base = cmds.xform(f"{curve}.cv[0]", q=True, ws=True, t=True)

        if surfaces:
            for j, surface in enumerate(surfaces):
                cmds.setAttr(f"{surface_cl_pos[j]}.inPosition", *curve_base, type='double3')
                surf_pos = cmds.getAttr(f"{surface_cl_pos[j]}.position")[0]
                dist = dwu.mag(surf_pos, curve_base)
                if dist < near_dist:
                    near_dist = dist
                    surf = surfaces[j]
                    near_pos = surf_pos
                    u = (cmds.getAttr(f"{surface_cl_pos[j]}.parameterU") + min_u[j]) / size_u[j]
                    v = (cmds.getAttr(f"{surface_cl_pos[j]}.parameterV") + min_v[j]) / size_v[j]

        if meshes:
            for j, mesh in enumerate(meshes):
                convert_fac = convert_to_cm_factor()
                cmds.setAttr(f"{mesh_cl_pos[j]}.inPosition", *[i * convert_fac for i in curve_base], type='double3')
                surf_pos = cmds.getAttr(f"{mesh_cl_pos[j]}.position")[0]
                surf_pos = [i * convert_fac for i in surf_pos]
                dist = dwu.mag(surf_pos, curve_base)
                if dist < near_dist:
                    near_dist = dist
                    near_pos = surf_pos
                    surf = meshes[j]
                    pos = cmds.getAttr(f"{mesh_cl_pos[j]}.position")[0]
                    u = cmds.getAttr(f"{mesh_cl_pos[j]}.parameterU")
                    v = cmds.getAttr(f"{mesh_cl_pos[j]}.parameterV")

                    face = cmds.getAttr(f"{mesh_cl_pos[j]}.nearestFaceIndex")
                    vert = cmds.polyListComponentConversion(f"{surf}.f[{face}]", tv=True)
                    vert_pos = cmds.xform(vert, q=True, t=True)
                    x, y, z = sum(vert_pos[0::3]) / (len(vert_pos) / 3), sum(vert_pos[1::3]) / (len(vert_pos) / 3), sum(
                        vert_pos[2::3]) / (len(vert_pos) / 3)
                    cmds.setAttr(f"{mesh_cl_pos[j]}.inPosition", x, y, z, type='double3')
                    u_center = cmds.getAttr(f"{mesh_cl_pos[j]}.parameterU")
                    v_center = cmds.getAttr(f"{mesh_cl_pos[j]}.parameterV")
                    vector2d = [(u_center - u) * uvthreshold, (v_center - v) * uvthreshold]
                    uapprox = u + vector2d[0]
                    vapprox = v + vector2d[1]

        if snap_to_surface:
            cmds.move((near_pos[0] - curve_base[0]), (near_pos[1] - curve_base[1]), (near_pos[2] - curve_base[2]),
                      curve, r=True)

        # Rebuild curve if matchPosition is enabled
        curve, deg = rebuild_curve_if_needed(curve, match_position)

        # Create hair curve node
        hname = create_hair_curve_node(hsys, surf, u, v, [uapprox, vapprox], 0, do_output_curves, True, False, False,
                                       curve, 1, hsys_group, hsys_output_hair_group, 1)

        # Rename follicle and curve if necessary
        hname, follicles = rename_follicle_and_curve(hname, outname, follicles, weird)

    # Clean up temporary nodes
    cleanup_temp_nodes(surface_cl_pos, mesh_cl_pos)

    # Attach follicles to nRigid nodes for collision, if required
    if made_hair_curve and attach_to_surface:
        nrigids = attach_follicles_to_mesh(hsys, meshes, do_collide_mesh)

    # Final cleanup and return result
    return finalize_result(follicles, hsys, nucleus, nrigids, weird)


# Helper functions for better readability and modularization

def setup_closest_point_nodes(surfaces, meshes, min_u, size_u, min_v, size_v):
    surface_cl_pos, mesh_cl_pos = [], []
    if surfaces:
        for i, surface in enumerate(surfaces):
            node = cmds.createNode('closestPointOnSurface')
            surface_cl_pos.append(node)
            cmds.connectAttr(f"{surface}.worldSpace[0]", f"{node}.inputSurface")

            min_u.append(cmds.getAttr(f"{surface}.mnu"))
            max_u = cmds.getAttr(f"{surface}.mxu")
            size_u.append(max_u - min_u[i])

            min_v.append(cmds.getAttr(f"{surface}.mnv"))
            max_v = cmds.getAttr(f"{surface}.mxv")
            size_v.append(max_v - min_v[i])

    if meshes:
        for i, mesh in enumerate(meshes):
            if not cmds.pluginInfo('nearestPointOnMesh', query=True, l=True):
                cmds.loadPlugin('nearestPointOnMesh')

            node = cmds.createNode('nearestPointOnMesh')
            mesh_cl_pos.append(node)
            cmds.connectAttr(f"{mesh}.worldMesh", f"{node}.inMesh")

    return surface_cl_pos, mesh_cl_pos


def curve_already_attached(curve):
    """Check if curve is already attached to a follicle."""
    connections = cmds.listConnections(f"{curve}.worldSpace[0]", sh=True)
    if connections:
        for con in connections:
            if cmds.nodeType(con) == "follicle":
                return True
        return cmds.getAttr(f"{curve}.io") != 0
    return False


def setup_hair_system(hsys_name, nucleus, do_output_curves):
    """Create and configure a new hair system if one doesn't exist."""
    hsys = cmds.createNode('hairSystem', name=f"{hsys_name}Shape")
    hsys_tr = cmds.listRelatives(hsys, p=True)[0]
    cmds.rename(hsys_tr, hsys_name)

    cmds.removeMultiInstance(f"{hsys}.stiffnessScale[1]", b=True)
    cmds.setAttr(f"{hsys}.clumpWidth", 0.00001)
    cmds.setAttr(f"{hsys}.hairsPerClump", 1)
    cmds.connectAttr('time1.outTime', f"{hsys}.currentTime")

    if not nucleus:
        nucleus = mel.eval('getActiveNucleusNode( false, true );')

    add_active_to_nsystem(hsys, nucleus)
    cmds.connectAttr(f"{nucleus}.startFrame", f"{hsys}.startFrame")

    hsys_group = cmds.group(empty=True, name=f"{hsys_name}Follicles")
    hsys_output_hair_group = cmds.group(empty=True, name=f"{hsys_name}OutputCurves_grp") if do_output_curves else ""

    return hsys, nucleus, hsys_group, hsys_output_hair_group


def rebuild_curve_if_needed(curve, match_position):
    """Rebuild the curve if matching positions is enabled."""
    if match_position:
        deg = cmds.getAttr(f"{curve}.degree")
        if deg > 1:
            rebuild = cmds.rebuildCurve(curve, name=f"{curve}_rebuild", ch=1, rpo=0, rt=0, end=1, kr=0, kcp=1, kep=1,
                                        kt=False, s=0, d=1, tol=0.1)
            rebuild_curve = cmds.ls(rebuild[0], dag=True, type='nurbsCurve')[0]
            cmds.parent(rebuild_curve, cmds.listRelatives(curve, p=True)[0], r=True, s=True)
            return rebuild_curve, deg
    return curve, -1


def rename_follicle_and_curve(hname, outname, follicles, weird):
    """Rename the follicle and output curve, if necessary."""
    if outname:
        new_hname = outname.replace('_crv', '_fol') if outname.endswith('_crv') else f"{outname}_fol"
        if hname:
            hname = cmds.rename(hname, new_hname)
            curve_tmp = cmds.listConnections(f"{hname}.outCurve")
            if curve_tmp:
                cmds.rename(curve_tmp[0], outname)
        else:
            weird.append(outname)
    else:
        hname = cmds.rename(hname, f"{hname}_fol")

    follicles.append(hname)
    return hname, follicles


def cleanup_temp_nodes(surface_cl_pos, mesh_cl_pos):
    """Delete temporary nodes created for surface/mesh closest point calculation."""
    for node in surface_cl_pos + mesh_cl_pos:
        cmds.delete(node)


def attach_follicles_to_mesh(hsys, meshes, do_collide_mesh):
    """Attach follicles to meshes to enable collisions."""
    nrigids = []
    if meshes and do_collide_mesh:
        for mesh in meshes:
            cn_sh = cmds.ls(mesh, dag=True, ni=True, type='mesh')
            if cn_sh:
                r = attach_nobject_to_hair(hsys, cn_sh[0], do_collide_mesh)
                set_collider_preset(r, 0, 0)
                nrigids.append(r)
    return nrigids


def finalize_result(follicles, hsys, nucleus, nrigids, weird):
    """Compile the final result dictionary with follicles, nucleus, and other nodes."""
    result = {'curves': cmds.listConnections([f"{fol}.outCurve" for fol in follicles]), 'hsys': hsys,
              'nucleus': nucleus}
    if follicles:
        result['follicles'] = follicles
    if nrigids:
        result['nrigids'] = nrigids
    if weird:
        result['debug'] = weird
    return result
