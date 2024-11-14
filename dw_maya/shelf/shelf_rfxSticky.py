import maya.cmds as cmds

import sys, os

# ----- Edit sysPath -----#
rdPath = '/home/abtidona/private/PycharmProjects/RND/dw_tools/maya/RFX'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

import dw_decorators as dwdeco
import dw_maya_utils as dwu
import cloth_artist_tools.rmaya.cloth_tweak as makeaTweak

mySel = dwu.lsTr(sl=True, o=True)

@dwdeco.vtxAnimDetection(mySel)
def createSticky():
    sticky = makeaTweak.CfxTweak()

    attr = dwu.add_attr(sticky.handle, "falloffMode", attributeType="enum", en="Volume:Surface:")
    cmds.connectAttr(attr, sticky.name + '.falloffMode', f=True)

createSticky()



