import maya.cmds as cmds
import dw_maya.dw_nucleus_utils as dwnx
# on selectionne les curves puis le mesh en dernier
sel = cmds.ls(selection=True, long=True)
dwnx.snapCurves(sel[-1], sel[:-1])