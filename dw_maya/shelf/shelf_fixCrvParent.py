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
for crv, fol in fol_crea:
    cmds.parent(crv, fol)

# special way to create one blendShape for multiple curve
blendshape = None
blendshape_set = None
for x, (curve, copy) in enumerate(zip(crvs, dups)):
    if blendshape is None:
        blendshape = cmds.blendShape(copy, curve, origin='world')[0]
        connections = cmds.listConnections(blendshape)
        blendshape_set = cmds.ls(connections, type='objectSet')[0]
    else:
        cmds.sets(curve, add=blendshape_set)
        cmds.blendShape(
            blendshape,
            edit=True,
            before=True,
            target=(curve, x, copy, 1.0))
    cmds.blendShape(blendshape, edit=True, weight=(x, 1.0))

cmds.group([i[1][1:] for i in fol_crea], name=msh[0].replace(':', '_') + '_GRP')

for fol in fol_crea:
    fol = fol[1][1:]
    cmds.rename(fol, msh[0].replace(':', '_') + '_fol')

