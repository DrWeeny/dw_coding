import maya.cmds as cmds

nucx = cmds.ls(type='nucleus')
for n in nucx:
    vis = n + '.visibility'
    ena = n + '.enable'
    cmds.setAttr(vis, 0)
    con = cmds.listConnections(ena, type='nucleus')
    if not con:
        cmds.connectAttr(vis, ena)

start_value = None
fsr = cmds.ls('*:furSimRig')
fsr += cmds.ls('*:clothRig')
for i in fsr:
    enable_attr = i + '.stretchAlembicCacheEnable'
    cmds.setAttr(enable_attr, 1)
    scale_attr = i + '.stretchAlembicCacheTimeScale'
    cmds.setAttr(scale_attr, 1.5)
    scale_attr = i + '.stretchAlembicCacheFrameHold'
    cmds.setAttr(scale_attr, 5)

    ns = i.split(':')[0]
    twarp = cmds.ls(ns + ':*', type='rfxTimeWarp')
    if twarp:
        for t in twarp:
            v = cmds.getAttr(t + '.newStartTime')
            nucx = cmds.ls(ns + ':*', type='nucleus')
            if nucx:
                for nx in nucx:
                    cmds.setAttr(nx + '.startFrame', v)
            if v < start_value or start_value is None:
                start_value = v

if start_value:
    cmds.playbackOptions(edit=True, min=start_value)
    cmds.currentTime(start_value, edit=True)
