import maya.cmds as cmds
import maya.OpenMaya as om

import dw_maya.dw_decorators as dwdeco

mySel = cmds.ls(sl=True)

@dwdeco.vtxAnimDetection(mySel[-1])
def doIt(bnode, targ):

    bs_name = cmds.blendShape(bnode,targ, en=1, tc=1, o='world', w=(0,1))
    return bs_name

bs_name = doIt(mySel[0:-1], mySel[-1])
msg = bs_name[0] + ' has been created\nTargets :\n' + str(',\n'.join(mySel[0:-1])) + '\nto :\n' + mySel[-1]
om.MGlobal.displayInfo(msg)
