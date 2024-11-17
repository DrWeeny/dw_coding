import maya.cmds as cmds
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_nucleus_utils as dwnx
import dw_maya.dw_duplication as dwdup

msh = dwu.lsTr(sl=True, dag=True, type='mesh')
crvs = dwu.lsTr(sl=True, dag=True, type='nurbsCurve')
dups = dwdup.dupMesh(crvs)

fol_crea = dwnx.create_surface_fol_driver(msh,
                                          fols=dups,
                                          optimise=.005,
                                          cv_sel=0)
for crv, fol in zip(crvs, fol_crea):
    cmds.parent(crv, fol[1])