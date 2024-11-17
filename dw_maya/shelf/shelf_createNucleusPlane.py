import maya.cmds as cmds

def create_nucleus_driver_plane():

    nucleus = cmds.ls(sl=True, type='nucleus')[0]
    node_name = cmds.polyPlane(n='nucleusPlane_driver',sh=0,sw=0,h=2, w=2)[0]
    cmds.delete(node_name, ch=True)
    attr0 = f'{node_name}.ty'
    attr1 = f'{nucleus}.planeOriginY'
    cmds.connectAttr(attr0, attr1, f=True)

    hide_attr = ['rx','ry','rz','v', 'sy']

    for a in hide_attr:
        attr2 = f'{node_name}.{a}'
        cmds.setAttr(attr2, keyable=False, channelBox=False)

    attr_set = {}
    attr_set['backfaceCulling'] = 3
    attr_set['template'] = 1
    attr_set['displayTriangles'] = 1

    for attr, value in attr_set.items():
        attr3 = f'{node_name}.{attr}'
        cmds.setAttr(attr3, value)

create_nucleus_driver_plane()