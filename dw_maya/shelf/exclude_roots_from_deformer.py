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
import sys, os

# ----- Edit sysPath -----#
rdPath = '/home/abtidona/private/PycharmProjects/RND/dw_tools/maya/RFX'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
import dw_maya_utils as dwu
import dw_presets_io as dwpresets

sel = cmds.ls(sl=True)
crv = dwu.lsTr(sel, dag=True, type='nurbsCurve')
deformers = []
for s in sel:
    if dwpresets.isDeformer(s):
        if 'tweak' in s:
            break
        else:
            deformers.append(s)
components = [i + '.cv[0:1]' for i in sel]
if components:
    dwpresets.editDeformer(deformers, components, remove=True)