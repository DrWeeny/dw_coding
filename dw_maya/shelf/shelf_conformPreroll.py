#!/usr/bin/env python
#----------------------------------------------------------------------------#
#------------------------------------------------------------------ HEADER --#

"""
@author:
    abtidona

@description:
    this is a description

@applications:
    - groom
    - cfx
    - fur
"""

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#

# built-in
import sys, os

# ----- Edit sysPath -----#
rdPath = '/home/abtidona/private/PycharmProjects/RND/dw_tools/maya/RFX'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

# internal
import maya.cmds as cmds

# external
import dw_channelBox_utils as dw_chbox

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#


#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

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