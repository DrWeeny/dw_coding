import maya.cmds as cmds
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_deformers as dwdef

sel = cmds.ls(sl=True)
crv = dwu.lsTr(sel, dag=True, type='nurbsCurve')
deformers = []
for s in sel:
    if dwdef.is_deformer(s):
        if 'tweak' in s:
            break
        else:
            deformers.append(s)
components = [i + '.cv[0:1]' for i in sel]
if components:
    dwdef.editDeformer(deformers, components, remove=True)