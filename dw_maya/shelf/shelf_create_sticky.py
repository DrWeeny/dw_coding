from maya import cmds
import dw_maya.dw_decorators as dwdeco
import dw_maya.dw_maya_utils as dwu
from dw_maya.dw_deformers import createSticky

mySel = dwu.lsTr(sl=True, o=True)

@dwdeco.vtxAnimDetection(mySel)
def createSticky():
    sel=cmds.ls(sl=True, fl=True)
    sticky = createSticky(sel)
    return sticky

createSticky()



