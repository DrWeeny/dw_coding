import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
from dw_maya.dw_decorators import acceptString
import dw_maya.dw_maya_utils as dwu
from .dw_create_follicle import create_follicles
import dw_maya.dw_deformers as dwdef

@acceptString('target')
def create_surface_fol_driver(target: list, fols: list, optimise: float = 0.01, cv_sel: int = -1):
    """
    Creates follicles on the target surface, drives them using the provided curves or follicles, and optionally merges them if they are too close.

    Used to create follicles from hair tips on a proxy mesh so I could drive the follicles/hair from simulation
    See orient follicles
    Args:
        target (list): List of target mesh surfaces.
        fols (list): List of input follicles or curves.
        optimise (float): Optimization threshold to merge nearby follicles (default 0.01).
        cv_sel (int): Index of the CV to use for placement (default -1).

    Returns:
        list: A list of tuples mapping input follicles to their created counterparts on the surface.
    """
    _fols = dwu.lsTr(fols, dag=True, type='follicle', long=True)
    if _fols:
        fols = _fols

    crvs = cmds.ls(fols, dag=True, type='nurbsCurve', long=True)
    if not crvs:
        cmds.error('Please provide some follicle or curve input.')

    # Adjust curve pivots
    dwu.change_curve_pivot(crvs)

    # Get the CV points based on the provided cv_sel index
    first_cvs = [cmds.ls(f"{c}.cv[:]", fl=True)[cv_sel] for c in crvs]
    sh_cvs = [f"{c}.{cv.split('.')[-1]}" for c, cv in zip(crvs, first_cvs)]

    # Find the closest UVs on the target surface
    uv_results = dwu.nearest_uv_on_mesh(target, sh_cvs, uvs=True)

    # Create follicles at the nearest UV locations
    target_fols = [create_follicles(r[0], r[1], optimise) for r in uv_results]
    target_fols = [dwu.lsTr(fol, long=True) for fol in target_fols]

    # If optimization is enabled, merge nearby follicles
    if optimise:
        copy_fols = target_fols[:]
        positions = [cmds.xform(fol, q=True, t=True) for fol in target_fols]

        new_list = []
        for idx, pos in enumerate(positions):
            # Find matching follicles within the optimization distance
            matching_fols = [
                target_fols[i] for i, p in enumerate(positions)
                if dwu.mag(pos, p) <= optimise
            ]
            if matching_fols:
                for match in matching_fols:
                    if match in copy_fols and match not in new_list:
                        copy_fols[target_fols.index(match)] = target_fols[idx]
                        new_list.extend([match, target_fols[idx]])

        # Remove redundant follicles after optimization
        to_remove = list(set(target_fols) - set(copy_fols))
        if to_remove:
            cmds.delete(to_remove)

        return list(zip(fols, copy_fols))

    return list(zip(fols, target_fols))


def orient_follicle_driver(surface: str, fols: list, **kwargs) -> list:
    """
    Creates orientation or aim constraints between follicles and a surface. It connects the
    constraints to a weight attribute on the surface for control, and optionally optimizes follicle positions.

    Args:
        surface (str): The target surface on which the follicles will be created.
        fols (list): A list of follicles or curves to drive the constraints.
        **kwargs: Additional arguments to control behavior, including:
            - weight (float): The weight of the constraint.
            - name (str): Name of the constraint.
            - aimVector (tuple): The aim vector for the aim constraint.
            - maintainOffset (bool): Whether to maintain offset.
            - orient (bool): Whether to use orientation constraint (default).
            - aim (bool): Whether to use aim constraint instead.
            - optimise (float): Distance threshold for optimizing follicle positions.

    Returns:
        list: A list of follicles connected to the surface.
    """
    # Enable editing of reference locked attributes
    cmds.optionVar(iv=('refLockEditable', True))

    # Collect flags from kwargs
    flags = dwu.flags(kwargs, 1, 'weight', 'w', dic={})
    flags = dwu.flags(kwargs, None, 'name', 'n', dic=flags)
    flags = dwu.flags(kwargs, None, 'aimVector', 'aim', dic=flags)
    flags = dwu.flags(kwargs, True, 'maintainOffset', 'mo', dic=flags)

    # flags for orient/aim modes and optimization
    orient_mode = dwu.flags(kwargs, True, 'orient', 'o')
    aim_mode = dwu.flags(kwargs, False, 'aim', 'a')
    opti_threshold = dwu.flags(kwargs, 0.05, 'optimise', 'opti')

    # Create follicles and map them to the target surface
    fol_and_targ = create_surface_fol_driver(surface, fols, opti_threshold)

    # Prepare lists for storing constraint and output follicle data
    constraints = []
    output_follicles = []

    # Convert follicles to transforms and curves
    follicle_transforms = dwu.lsTr(fols, dag=True, type='follicle', long=True)
    curves = cmds.ls(follicle_transforms, dag=True, type='nurbsCurve', long=True)

    # Apply either orient or aim constraints
    for (follicle_target, curve_transform) in zip(fol_and_targ, dwu.lsTr(curves, long=True)):
        if orient_mode and not aim_mode:
            cons = cmds.orientConstraint(follicle_target[1], curve_transform, **flags)[0]
        else:
            cons = cmds.aimConstraint(follicle_target[1], curve_transform, **flags)[0]

        constraints.append(cons)
        output_follicles.append(follicle_target[1])

    # Set up the weight attribute for the constraints (either aim or orient)
    attr_name = 'weightAim' if aim_mode else 'weightOrient'
    if not cmds.objExists(f'{surface}.{attr_name}'):
        cmds.addAttr(surface, ln=attr_name, at='double', min=0, dv=1)
        cmds.setAttr(f'{surface}.{attr_name}', e=True, keyable=True)

    # Connect the surface attribute to the first weight attribute of each constraint
    for cons in constraints:
        weight_attrs = [a for a in cmds.listAttr(cons) if 'W0' in a]
        cmds.connectAttr(f'{surface}.{attr_name}', f'{cons}.{weight_attrs[0]}', force=True)

    return output_follicles


def create_crv_dual_mesh_driver(outer: str, inner: str, crv: list) -> list:
    """
    Creates a dual-mesh driver using curves wrapped to two meshes (outer and inner).

    The curves are chunked into batches (due to wrap limitations), and then weights are applied.

    Args:
        outer (str): The name of the outer mesh.
        inner (str): The name of the inner mesh.
        crv (list): A list of curves that will drive the dual mesh system.

    Returns:
        list: Nodes created for each chunk of wrapped curves.
    """

    # Get valid mesh transforms for the outer and inner geometries
    geo = dwu.lsTr([outer, inner], type='mesh')

    # Get long path names for the curves of type nurbsCurve
    crv = dwu.lsTr(crv, type='nurbsCurve', long=True)

    # Wrap system can handle up to 251 curves at a time, so chunk the curves accordingly
    crv_chunks = dwu.chunks(crv, 251)

    # Store the nodes created during the process
    nodes = []

    # Process each chunk of curves
    for crv_chunk in crv_chunks:
        # Perform the curve wrap to the two meshes
        cw_nodes = dwdef.cvWrap2Geo(crv_chunk, geo)
        nodes.append(cw_nodes)

    # Apply weights to the wrapped curves
    dwdef.cvWeights2Geo(crv)

    return nodes


def is_conn_to_hairsys(follicle: str) -> bool:
    """Check if a follicle is connected to a hair system."""
    return bool(cmds.listConnections(follicle + '.currentPosition', type='hairSystem'))

def dual_mesh_driver(outer: str, inner: str, grp: list, mode: int = 0) -> str:
    """
    Inner and outer mesh wrapping curves from group, optionally supporting dynamic systems like hair.

    Args:
        outer (str): Outer mesh surface name.
        inner (str): Inner mesh surface name.
        grp (list): List of curves to wrap or bind.
        mode (int): 0 for regular curves, 1 for dynamic systems like hair follicles.

    Returns:
        str: The name of the created group containing wrapped curves.
    """

    out_mesh, in_mesh = dwu.lsTr([outer, inner], type='mesh')

    if mode:
        # Handle dynamic system mode (e.g., hair follicles)
        grp_shapes = dwu.lsTr(grp, ni=True, long=True, type='nurbsCurve', parent=False)
        test_fols = cmds.listConnections(grp_shapes, sh=True, type='follicle')
        fols_shapes = [fol for fol in test_fols if is_conn_to_hairsys(fol)]
        fols_tr = dwu.lsTr(fols_shapes, long=True)
        crv_shapes = dwu.lsTr(fols_tr, type='nurbsCurve', parent=False, long=True)
        crv_transforms = dwu.lsTr(crv_shapes, long=True)
    else:
        # Handle regular curves mode
        crv_shapes = dwu.lsTr(grp, ni=True, type='nurbsCurve', parent=False, long=True)
        crv_transforms = dwu.lsTr(crv_shapes, long=True)

    # Ensure intermediateObject attribute is set to 0
    for curve in crv_shapes:
        cmds.setAttr(curve + '.intermediateObject', 0)

    # Duplicate curves for cvWrap
    cvwrap_curves = []
    duplicates = cmds.duplicate(crv_transforms, n='dw_tmp_name_#')
    for dup, original in zip(duplicates, crv_transforms):
        short_name = original.split(':')[-1].split('|')[-1]
        renamed_curve = cmds.rename(dup, 'cvwrp_' + short_name)
        cvwrap_curves.append(renamed_curve)

    # Extract the name for grouping from the first curve
    short_name = crv_transforms[0].split(':')[-1].split('|')[-1]
    name_parts = short_name.split('_')
    if len(name_parts) >= 2 and name_parts[-2].isdigit():
        name = '_'.join(name_parts[:-2])
    else:
        name = '_'.join(name_parts[:-1])

    # Create group for the cvWrap curves
    cvwrap_group = cmds.group(cvwrap_curves, n=f'cvwrp_{name}_grp', w=True)

    # Create curve dual mesh driver
    create_crv_dual_mesh_driver(out_mesh, in_mesh, cvwrap_curves)

    # Create blend shapes between cvWrap curves and original curves
    blendshape_nodes = []
    for cvwrap, original in zip(cvwrap_curves, crv_transforms):
        bs = cmds.blendShape(cvwrap, original, en=1, tc=1, o='world', w=(0, 1))[0]
        blendshape_nodes.append(bs)

    # Add weight attribute for blend shapes
    attr_name = 'weightBS'
    cmds.addAttr(out_mesh, ln=attr_name, at='double', min=0, dv=1)
    cmds.setAttr(f'{out_mesh}.{attr_name}', e=True, keyable=True)

    # Connect blend shape weights to the weight attribute
    for bs_node in blendshape_nodes:
        cmds.connectAttr(f'{out_mesh}.{attr_name}', f'{bs_node}.en')

    return cvwrap_group
