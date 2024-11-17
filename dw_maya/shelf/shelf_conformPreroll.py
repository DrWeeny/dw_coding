import maya.cmds as cmds

import dw_maya.dw_channelbox_utils as dw_chbox

def conform_preroll(frameSpacing=int(1), preroll=12, *args):
    mySel = dw_chbox.get_channels()

    myMinTime = int(cmds.playbackOptions(q=True, min=1))  # currentFrame
    prerollEnd = myMinTime + preroll
    value = cmds.getAttr(mySel)

    for i in mySel:
        cmds.setKeyframe(i.split('.')[0], attribute=i.split('.')[-1],
                         t=[myMinTime, myMinTime + 10], v=0)
        cmds.setKeyframe(i.split('.')[0], attribute=i.split('.')[-1],
                         t=prerollEnd, v=value)


conform_preroll()