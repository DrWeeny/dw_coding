# internal
import maya.cmds as cmds

sel = cmds.ls(sl=1)[0]
assignement = {}
hist = cmds.listHistory(sel, f=1)
shaders = cmds.listConnections(hist)
for shd in shaders:
    sg = cmds.listConnections(shd, type='shadingEngine')
    if sg and 'initialShadingGroup' not in sg:
        faces = cmds.sets(sg[0], q=True)
        if '.' in faces[0]:
            assignement[sg[0]] = [f.split('.')[-1] for f in faces]
        else:
            assignement[sg[0]] = faces[0]

orig, targ = cmds.ls(sl=1)
for sg in assignement:
    if isinstance(assignement[sg], list):
        ass = [targ + '.' + f for f in assignement[sg]]
    else:
        ass = targ
    cmds.sets(ass, e=True, fe=sg)

cvs = cmds.polyColorSet(orig, q=True, currentColorSet=True)
if cvs:
    cmds.transferAttributes(orig, targ, transferPositions=0,
                            transferNormals=0, transferUVs=2,
                             transferColors=1, sourceColorSet=cvs[0],
                             targetColorSet=cvs[0], sampleSpace=4,
                             sourceUvSpace="map1", targetUvSpace="map1",
                             searchMethod=3, flipUVs=0, colorBorders=0)

