import maya.cmds as cmds
sel = cmds.ls(sl=True)
obj = sel[:-1]
_set = sel[-1]
cmds.sets(*obj, rm=_set)
