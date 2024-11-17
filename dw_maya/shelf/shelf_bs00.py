import maya.cmds as cmds
import maya.OpenMaya as om

def bs_transfer_weight(bs_node, weight_list, *args):
    nb = len(weight_list)
    cmds.setAttr(bs_node + '.inputTarget[0].baseWeights[0:' + str(nb-1) + ']', *weight_list, size=nb)

import dw_maya.dw_decorators as dwdeco

mySel = cmds.ls(sl=True)

@dwdeco.vtxAnimDetection(mySel[-1])
def doIt(bnode, targ):

    bs_name = cmds.blendShape(bnode,targ, en=1, tc=1, o='world', w=(0,1))
    return bs_name

mySel = cmds.ls(sl=True)
bs_name = doIt(mySel[0:-1], mySel[-1])
    
nbVtx = cmds.polyEvaluate(mySel[-1], v=True)
weight0 = [0] * nbVtx
    
bs_transfer_weight(bs_name[0], weight0)
    
msg = bs_name[0] + ' has been created\nTargets :\n' + str(',\n'.join(mySel[0:-1])) + '\nto :\n' + mySel[-1]
om.MGlobal.displayInfo(msg)

