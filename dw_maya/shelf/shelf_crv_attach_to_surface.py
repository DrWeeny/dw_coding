import sys, os

# ----- Edit sysPath -----#
rdPath = '/home/abtidona/private/PycharmProjects/RND/dw_tools/maya/RFX'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
import dw_maya_utils as dwu
import dw_nucleus_utils as dwnx
import dw_duplication as dwdup

msh = dwu.lsTr(sl=True, dag=True, type='mesh')
crvs = dwu.lsTr(sl=True, dag=True, type='nurbsCurve')
dups = dwdup.dupMesh(crvs)
# fols can be feed with curve instead
# this command was originally created for driving
# simulation follicle curves
fol_crea = dwnx.create_surface_fol_driver(msh,
                                          fols=dups,
                                          optimise=.005,
                                          cv_sel=0)
for crv, fol in zip(crvs, fol_crea):
    cmds.parent(crv, fol[1])