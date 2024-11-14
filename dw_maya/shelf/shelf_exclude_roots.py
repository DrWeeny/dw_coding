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
from __future__ import division

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
import dw_presets_io as dwpresets
import dw_decorators as dwdeco

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#
@dwdeco.viewportOff
def excludeRoots(curves = '*:animWires', excludeLast = True):
    crvs = dwu.lsTr(curves, dag=True, type='nurbsCurve', ni=True)
    nb = len(crvs)
    deformers = []

    for x, c in enumerate(crvs):
        hist = [d for d in cmds.listHistory(c)]

        for h in hist:
            if dwpresets.isDeformer(h):
                if 'tweak' in h:
                    break
                else:
                    deformers.append(h)

        components = c + '.cv[0:1]'
        if deformers:
            if excludeLast:
                deformers = deformers[:-2]
            for d in deformers:
                dwpresets.editDeformer(d, components, remove=True)

        print('progress : {0:.0%}'.format(float(x) / float(nb)))
    print('progress : completed')