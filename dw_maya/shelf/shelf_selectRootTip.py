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
import dw_feathers_utils as dwfeathers

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#

try:
    counter += 1
    index = counter % 2
    new_m_sel = [i.split('.')[0] for i in cmds.ls(sl=True)]
    new_sel = dwu.lsTr(new_m_sel, dag=True, type='nurbsCurve', ni=True)
    if new_m_sel:
        if sorted(new_m_sel) == sorted(m_sel):
            sel = new_sel
        else:
            counter = 0
            index = 0
            m_sel = [i.split('.')[0] for i in cmds.ls(sl=True)]
            sel = dwu.lsTr(m_sel, dag=True, type='nurbsCurve', ni=True)
except:
    counter = 0
    index = 0
    m_sel = [i.split('.')[0] for i in cmds.ls(sl=True)]
    sel = dwu.lsTr(m_sel, dag=True, type='nurbsCurve', ni=True)

selcp = dwfeathers.list_cv_index(sel, -index)
cmds.select(selcp)


