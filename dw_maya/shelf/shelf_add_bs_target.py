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

# internal

# external


#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#


#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#


import maya.cmds as cmds

def bs_addNexTarget():
    bsNode = cmds.ls(sl=True)[0]
    myMeshBlendshaped = cmds.ls(sl=True)[-1]
    meshToAdd = cmds.ls(sl=True)[1]

    insIndex = len(cmds.blendShape(bsNode, q=1, t=1))

    cmds.blendShape(bsNode, edit=True,
                    t=(myMeshBlendshaped, insIndex, meshToAdd, 1))

bs_addNexTarget()
