import sys, os
from math import sqrt

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from maya import cmds, mel
from dw_maya.dw_nx_mel import *
from dw_maya.dw_nucleus_utils import create_nucleus
import dw_maya.dw_deformers as dwdef



def oldExampleSofaWorkflow():
    mySel = cmds.ls(sl=True)[0]

    # 1- Duplicate and create the recipe mesh : mesh_recipe_cfx
    outputClothMesh = cmds.duplicate(mySel, n=mySel + "_cfxOutput",
                                     rc=1)  # will be wrapped to the combined
    cmds.blendShape(outputClothMesh, mySel)

    grpCfxName = cmds.group(em=1, n=mySel + "_cfxRig")
    cmds.parent(outputClothMesh, grpCfxName)

    # 2- Duplicate again and blendshape to recipe - mesh_parts_cfx
    grpCombinedName = cmds.group(em=1, n=mySel + "_combinedParts")
    toPartsMesh = cmds.duplicate(mySel, n=mySel + "_toCut", rc=1)
    cmds.parent(toPartsMesh, grpCombinedName)

    # --------  Sofa_parts_pied04_noneCfx
    # --------  Sofa_parts_accoudoir01_activeCfx
    # --------  Sofa_parts_body01_rigidCfx

    # 4- Duplicate this group and blendshape mesh_parts_cfx to transfer ones
    toTransferMesh = cmds.duplicate(toPartsMesh[0],
                                    n=toPartsMesh[0].replace("_toCut",
                                                             "_toTransfer"),
                                    rc=1)
    myTransferNodes = [cmds.listRelatives(i, p=1)[0] for i in
                       cmds.ls(toTransferMesh[1:], dag=True, type='mesh')]
    for i in myTransferNodes:
        cmds.rename(i, i + "_transfer")

    parts_cfx = cmds.ls(sl=1, dag=1, type='transform')[1:]
    for i in parts_cfx:
        cmds.rename(i, i + "_parts")
    parts_transfer = cmds.ls(sl=1, dag=1, type='transform')[1:]

    for i in range(len(parts_cfx)):
        bs_Name = cmds.blendShape(parts_cfx[i], parts_transfer[i], w=(0, 1))

    # 5- combine transfer mesh
    myMeshResult = cmds.polyUnite(parts_transfer, ch=1, mergeUVSets=1,
                                  name="sofa_transfer")

    # 6-wrap the sofa_parts_recipe to the transfer mesh
    dwdef.createWrap(myMeshResult[0], outputClothMesh[0])

    # 7- display layer to make them unselectable
    cmds.parent(grpCombinedName, grpCfxName)
    cmds.setAttr(grpCombinedName + ".visibility", 0)
    cmds.setAttr(outputClothMesh[0] + ".visibility", 0)
    cmds.createDisplayLayer(n="sofaRigHiddenElements", e=1)
    cmds.editDisplayLayerMembers('sofaRigHiddenElements', grpCombinedName, nr=1)

    # 8 create one group per cloth object
    mySimGroup = cmds.group(n="Sofa_Sim_GRP", em=1, p=grpCfxName)
    nucleusNode = create_nucleus("Sofa_nucleus")
    cmds.parent(nucleusNode, mySimGroup)
    for i in parts_cfx:
        if i.endswith("_activeCfx"):
            myNode = cmds.duplicate(i, n=i.replace("_activeCfx", "_cloth"))
            cmds.parent(myNode, mySimGroup)
