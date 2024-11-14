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
from maya import cmds, mel

# internal

# external

def bs_addNextTarget():
    bsNode = cmds.ls(sl=True)[0]
    myMeshBlendshaped = cmds.ls(sl=True)[-1]
    meshToAdd = cmds.ls(sl=True)[1]

    insIndex = len(cmds.blendShape(bsNode, q=1, t=1))

    cmds.blendShape(bsNode, edit=True, t=(myMeshBlendshaped, insIndex, meshToAdd, 1))

bs_addNextTarget()