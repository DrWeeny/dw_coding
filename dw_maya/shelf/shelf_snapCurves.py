import sys, os

# ----- Edit sysPath -----#
rdPath = '/home/abtidona/private/PycharmProjects/RND/dw_tools/maya/RFX'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
import dw_nucleus_utils as dwnx
# on selectionne les curves puis le mesh en dernier
sel = cmds.ls(selection=True, long=True)
dwnx.snapCurves(sel[-1], sel[:-1])