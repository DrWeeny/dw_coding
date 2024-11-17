import maya.cmds as cmds
import dw_maya.dw_duplication as dwdup
sel = cmds.ls(sl=True)
dwdup.dupWCache(sel)

