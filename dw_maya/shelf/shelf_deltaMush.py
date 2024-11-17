import maya.mel as mel

# external
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_decorators as dwdeco

mySel = dwu.lsTr(sl=True, o=True)

@dwdeco.vtxAnimDetection(mySel)
def create_deltamush():
    mel.eval('DeltaMush')

create_deltamush()