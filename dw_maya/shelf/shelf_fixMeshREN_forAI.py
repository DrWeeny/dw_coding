
from maya import cmds
for item in cmds.ls( "*_REN" ):
    try:
        cmds.setAttr( "%s.aiSubdivType" % item, 1 )
        cmds.setAttr( "%s.aiSubdivIterations" % item, 2 )
        cmds.setAttr( "%s.aiOpaque" % item, 1 )
        cmds.setAttr( "%s.aiSelfShadows" % item, 1 )
    except: pass