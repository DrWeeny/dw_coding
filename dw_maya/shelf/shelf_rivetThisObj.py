__author__ = 'abaudoin'

import maya.cmds as cmds

sel = cmds.ls(sl=True)
rivet = sel[-1]
mesh = sel[0]

coord01 = cmds.xform(rivet, query=True, t=True)
cmds.xform(mesh, rotatePivot=coord01)
cmds.xform(mesh, scalePivot=coord01)

cmds.parentConstraint(rivet, mesh, mo=True, skipRotate=('x', 'y', 'z'), weight=1)
