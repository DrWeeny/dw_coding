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

import maya.mel as mel
import maya.cmds as cmds

# external
import dw_maya_utils as dwu
import dw_decorators as dwdeco

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#

mySel = dwu.lsTr(sl=True, o=True)

#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

@dwdeco.vtxAnimDetection(mySel)
def createMush():
    mel.eval('DeltaMush')

createMush()