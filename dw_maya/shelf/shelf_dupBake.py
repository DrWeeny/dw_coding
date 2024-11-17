import maya.cmds as cmds
import dw_maya.dw_duplication as dwdup # reload(dwdup)
sel = cmds.ls(sl=True)
objs = dwdup.dupAnim(sel)
