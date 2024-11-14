import maya.mel as mel
import maya.cmds as cmds

import sys, os

# ----- Edit sysPath -----#
rdPath = '/home/abtidona/private/PycharmProjects/RND/dw_tools/maya/RFX'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

import dw_maya_utils as dwu
import dw_decorators as dwdeco

mySel = dwu.lsTr(sl=True, o=True)

@dwdeco.vtxAnimDetection(mySel)
def createCluster():
    mel.eval('CreateCluster')

createCluster()