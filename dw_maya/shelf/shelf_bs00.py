import maya.cmds as cmds
import maya.OpenMaya as om

import sys, os

# ----- Edit sysPath -----#
rdPath = '/home/abtidona/private/PycharmProjects/RND/dw_tools/maya/RFX'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)


#base weight to base weight only ---> BS_transfer_baseWeight(BS02, baseWeight_values)
def BS_transfer_baseWeight(bs_node, baseWeight_list, *args):
    nb = len(baseWeight_list)
    cmds.setAttr(bs_node + '.inputTarget[0].baseWeights[0:' + str(nb-1) + ']', *baseWeight_list, size=nb)

import dw_decorators as dwdeco

mySel = cmds.ls(sl=True)

@dwdeco.vtxAnimDetection(mySel[-1])
def doIt(bnode, targ):

    bs_Name = cmds.blendShape(bnode,targ, en=1, tc=1, o='world', w=(0,1))
    return bs_Name

mySel = cmds.ls(sl=True)
bs_Name = doIt(mySel[0:-1], mySel[-1])
    
nbVtx = cmds.polyEvaluate(mySel[-1], v=True)
weight0 = [0] * nbVtx
    
BS_transfer_baseWeight(bs_Name[0], weight0)
    
msg = bs_Name[0] + ' has been created\nTargets :\n' + str(',\n'.join(mySel[0:-1])) + '\nto :\n' + mySel[-1]
om.MGlobal.displayInfo(msg)

