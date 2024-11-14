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
import dw_maya_utils as dwu
import re


geom = cmds.ls('*:geometry', r=True)
msh_sh = cmds.ls(geom,
                 dag=True,
                 type=['mesh', 'nurbsCurve'],
                 ni=True,
                 long=True)
patt = re.compile('Shape(Deformed){1,}')
for sh in msh_sh:
    slice = cmds.ls(sh + '.sliceName')
    if slice:
        value = cmds.getAttr(slice[0])
        name = patt.sub('Shape', value)
    else:
        value = sh
        name = patt.sub('Shape', value)

    dwu.add_attr(sh, 'sliceName', name)
