import sys, os

# ----- Edit sysPath -----#
rdPath = '/home/abtidona/private/PycharmProjects/RND/dw_tools/maya/RFX'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
import dw_channelBox_utils as dwchbox

def conformPreroll(frameSpacing=int(1), *args):
    mySel = dwchbox.getChannels()

    myMinTime = int(cmds.playbackOptions(min=1))  # currentFrame
    prerollEnd = myMinTime + 30
    value = cmds.getAttr(mySel)

    for i in mySel:
        cmds.setKeyframe(i.split('.')[0], attribute=i.split('.')[-1], t=[myMinTime, myMinTime + 10], v=0)
        cmds.setKeyframe(i.split('.')[0], attribute=i.split('.')[-1], t=prerollEnd, v=value)

conformPreroll()