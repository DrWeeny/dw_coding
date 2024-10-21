import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
from dw_maya.dw_decorators import acceptString
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_duplication as dwdup

@acceptString('crvs')
def crv_band(crvs=list, setup=False):
    """
    TODO : not finished
    Create extruded meshes from curves, combine them, and set up wrapping for curve manipulation.

    Args:
        crvs (list): List of nurbsCurve names.
        setup (bool): If True, performs setup for wrapping or blending curves with the extruded geometry.

    Returns:
        list: Names of extruded geometry objects.
    """

    extruded = []
    sel = dwu.lsTr(crvs, type='nurbsCurve')

    # Step 1: Extrude each curve into geometry
    for curve in sel:
        out_extr = cmds.extrude(curve, ch=True, rn=False, po=1, et=0, upn=0,
                                d=[0, 0, 1], length=0.2, rotation=0, scale=1, dl=3)
        extruded.append(out_extr[0])

    # If not doing the setup, return the extruded geometry
    if not setup:
        return extruded

    # Step 2: Combine extruded geometries into a single mesh
    combined_name = sel[0] + '_combined'
    combined_geo = cmds.polyUnite(extruded, ch=1, mergeUVSets=1, centerPivot=1, name=combined_name)[0]

    # Step 3: Separate the combined geometry back into individual parts (if needed)
    separated_geos = cmds.polySeparate(combined_geo, ch=1)

    # Step 4: Duplicate curves for wrapping setup
    dups_crvs = dwdup.dupMesh(sel, prefix='band')

    # Step 5: Set up wrapping or binding to extruded meshes (optional)
    for original_curve, extruded_geo in zip(sel, separated_geos):
        # Create a wrap deformer to blend the curves with extruded meshes
        cmds.wrap(original_curve, extruded_geo, exclusive=None, weightThreshold=0.0, maxDistance=1.0,
                  influenceType=2, falloffMode=0)

    # Return the separated geometry names
    return separated_geos