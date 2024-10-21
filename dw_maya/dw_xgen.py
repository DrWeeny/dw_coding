import xgenm.xgGlobal as xgg
import xgenm.xmaya.xgmExternalAPI as xmayaExt
import maya.cmds as cmds

nb = 925

# Loop through all xgmSplineGuide nodes
for x in cmds.ls(type='xgmSplineGuide'):
    # Safely retrieve the parent node of the spline guide
    parent_relatives = cmds.listRelatives(x, p=True)
    if parent_relatives:
        p = parent_relatives[0]
        xid = xmayaExt.guideIndex(p)  # Get the guide index
        if xid == nb:
            break  # If the index matches, exit the loop