import maya.cmds as cmds
sel = cmds.ls(sl=True)
_set = sel[-1]
cmds.sets(clear=_set)
