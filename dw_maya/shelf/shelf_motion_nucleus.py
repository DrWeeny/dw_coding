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
import dw_maya_utils as dwu
import dw_nucleus_utils as dwnx
import dw_decorators as dwdeco

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#


#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#
@dwdeco.viewportOff
@dwnx.tmp_disable_solver
def motion_nucleus():
    range_ = dwu.current_timerange(range_=True)
    vtx_track = cmds.filterExpand(sm=31)[0]
    nucleus = cmds.ls(sl=True, type='nucleus')[0]
    for frm in range_:
        cmds.currentTime(frm, e=True)
        pos = cmds.pointPosition(vtx_track)
        cmds.setAttr(nucleus + '.t', *pos)
        cmds.setKeyframe(nucleus, attribute=['tx', 'ty', 'tz'])
motion_nucleus()
