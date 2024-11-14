#!/usr/bin/env python
#----------------------------------------------------------------------------#
#------------------------------------------------------------------ HEADER --#

"""
@author:
    ptrovillas

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
import sys

# internal

# external
# ----- Edit sysPath -----#
rdPath = "/people/ptorrevillas/public/py_scripts"
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)
import utils as pj_utils

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#


pj_utils.grow_vertex_selection()