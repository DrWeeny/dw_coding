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
import dw_presets_io as dwpresets

def isDeformable(i):
    meshes = dwu.lsTr(i, dag=True, type='mesh')
    nurbs = dwu.lsTr(i, dag=True, type='nurbsCurve')
    if meshes:
        meshes = [m for m in meshes if cmds.ls(m+'.vtx[*]')]
    if nurbs:
        nurbs = [n for n in nurbs if cmds.ls(m+'.cv[*]')]
    return meshes + nurbs

sel = cmds.ls(sl=True, fl=True)
deformer = [i for i in sel if dwpresets.isDeformer(i)][0]
components = [i for i in sel if '.' in sel]
if not components:
    objs = [isDeformable(i)[0] for i in sel if isDeformable(i)]
if components:
    dwpresets.editDeformer(deformer, components, rm=True)
else:
    dwpresets.editDeformer(deformer, objs, rm=True)


