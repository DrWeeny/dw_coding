import sys, os

# ----- Edit sysPath -----#
rdPath = '/home/abtidona/private/PycharmProjects/RND/dw_tools/maya/RFX'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

import dw_maya_utils as dwu
import maya.cmds as cmds

sel = cmds.ls(sl=True)
cmds.delete(sel[0::3])
cmds.delete(sel[2::3])

sel = cmds.ls(sl=True)

extruded = []
sel = dwu.lsTr(sl=True, dag=True, type='nurbsCurve')
for s in sel:
    out_extr = cmds.extrude(s, ch=True, rn=False, po=1, et=0, upn=0,
                            d=[0, 0, 1], length=.2, rotation=0, scale=1,
                            dl=3)
    extruded.append(out_extr)

# Each crs will be wrapped to the mesh
name = sel[0] + '_combined'
# Combine them
comb_geos = cmds.polyUnite([i[0] for i in extruded],
                           ch=1, mergeUVSets=1, centerPivot=1,
                           name=name)
cmds.delete(comb_geos, ch=True)