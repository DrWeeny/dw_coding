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

import dw_decorators as dwdeco

mySel = cmds.ls(sl=True)

@dwdeco.vtxAnimDetection(mySel[-1])
def doIt(bnode, targ):

    bs_Name = cmds.blendShape(bnode,targ, en=1, tc=1, o='world', w=(0,1))
    return bs_Name

bs_Name = doIt(mySel[0:-1], mySel[-1])
msg = bs_Name[0] + ' has been created\nTargets :\n' + str(',\n'.join(mySel[0:-1])) + '\nto :\n' + mySel[-1]
om.MGlobal.displayInfo(msg)
#api.MGlobal.displayWarning / displayError
#OpenMaya.MGlobal.displayInfo(msg) / OpenMaya.MGlobal.displayWarning(msg) / OpenMaya.MGlobal.displayError(msg)

