import dw_maya.dw_maya_utils as dwu
from dw_maya.dw_deformers import listDeformers, editDeformer
from maya import cmds

def is_deformable(i):
    meshes = dwu.lsTr(i, dag=True, type='mesh')
    nurbs = dwu.lsTr(i, dag=True, type='nurbsCurve')
    if meshes:
        meshes = [m for m in meshes if cmds.ls(m+'.vtx[*]')]
    if nurbs:
        nurbs = [n for n in nurbs if cmds.ls(m+'.cv[*]')]
    return meshes + nurbs

sel = cmds.ls(sl=True, fl=True)
deformer = listDeformers(sel)[0]
components = [i for i in sel if '.' in sel]
if not components:
    objs = [is_deformable(i)[0] for i in sel if is_deformable(i)]
if components:
    editDeformer(deformer, components, add=True)
else:
    editDeformer(deformer, objs, add=True)


