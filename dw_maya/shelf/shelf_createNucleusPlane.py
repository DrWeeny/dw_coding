__author__ = 'abaudoin'

import maya.cmds as cmds

def createDriverPlane():

    nucleus = cmds.ls(sl=True, type='nucleus')[0]
    nodeName = cmds.polyPlane(n='nucleusPlane_driver',sh=0,sw=0,h=2, w=2)[0]
    cmds.delete(nodeName, ch=True)
    attr0 = '{}.{}'.format(nodeName, 'ty')
    attr1 = '{}.{}'.format(nucleus, 'planeOriginY')
    cmds.connectAttr(attr0, attr1, f=True)

    hideAttr = ['rx','ry','rz','v', 'sy']

    for i in hideAttr:
        attr2 = '{}.{}'.format(nodeName, i)
        cmds.setAttr(attr2, keyable=False, channelBox=False)

    shape = cmds.listRelatives(nodeName, s=True)[0]

    attrSet = {}
    attrSet['backfaceCulling'] = 3
    attrSet['template'] = 1
    attrSet['displayTriangles'] = 1

    for i in attrSet.keys():
        attr3 = '{}.{}'.format(nodeName, i)
        cmds.setAttr(attr3, attrSet[i])

    shape = cmds.listRelatives(nodeName, s=True)[0]

createDriverPlane()