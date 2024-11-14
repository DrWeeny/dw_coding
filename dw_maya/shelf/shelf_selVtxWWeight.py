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
import dw_presets_io as dwpresets

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#


#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

def getDeformerInfo(deformerNode, *args):
    # Query Vertex
    Mesh = [i for i in cmds.listHistory(deformerNode, f=True) if cmds.nodeType(i) == "mesh"][0]
    if Mesh:
        Mesh = cmds.listRelatives(Mesh, p=1)[0]
        VertexNb = cmds.polyEvaluate(Mesh, v=1)
        myRange = "0:" + str(VertexNb - 1)
    else:
        myRange = ":"

    print("range is : {0}".format(myRange))

    Weight_values = cmds.getAttr(deformerNode + '.weightList[0].weights[{0}]'.format(myRange))

    dic = {'mainWeight': Weight_values}

    return dic


def getBSinfo(BS01, *args):
    """return 'mainWeight' : weight of the env map,
              'targetName' : targets name and number,
               targetsWeight': weight of each target map,"""

    # Query Vertex
    Mesh = [i for i in cmds.listHistory(BS01, f=True) if cmds.nodeType(i) == "mesh"][0]
    Mesh = cmds.listRelatives(Mesh, p=1)[0]
    VertexNb = cmds.polyEvaluate(Mesh, v=1)
    myRange = "0:" + str(VertexNb - 1)

    # BS INFO :
    # number of target shapes
    BS01_targetWeightsNb = len(cmds.blendShape(BS01, q=True, t=1))
    # name of target shapes
    BS01_targetWeightsName = cmds.blendShape(BS01, q=True, t=1)
    # zip both as ([number, name], [...])
    BS01_targets = zip(list(range(BS01_targetWeightsNb)), BS01_targetWeightsName)

    # Store Base Weight and Target Weight
    baseWeight_values = cmds.getAttr(BS01 + '.inputTarget[0].baseWeights[' + myRange + ']')
    # [:] is important, it will force to get every points
    # (not only the one with value) BUGS happening

    # target proc [[tw1],[tw2]], note you should add [:]
    targetWeight_values = []
    for target in range(BS01_targetWeightsNb):
        try:
            targetWeight_values.append(
                cmds.getAttr(BS01 + '.inputTarget[' + str(0) + '].inputTargetGroup[0].tw[' + myRange + ']'))
        except:
            targetWeight_values.append('error')

    dic = {'mainWeight': baseWeight_values,
           'targetName': BS01_targets,
           'targetsWeight': targetWeight_values}

    return dic

def selIndexFromValue(myBSMap=[], *args):
    indexToSel = []
    if args:
        if len(args) == 2:
            for i, t in enumerate(myBSMap):
                # print i, t
                if t > args[0] and t < args[1]:
                    indexToSel.append(i)
            return indexToSel


        elif len(args) == 1:
            for i, t in enumerate(myBSMap):
                # print i, t
                if t > args[0]:
                    indexToSel.append(i)
            return indexToSel

    else:
        for i, t in enumerate(myBSMap):
            # print i, t
            if t > 0:
                indexToSel.append(i)
        return indexToSel

def selectWeightedVertices(mesh=str, index=[]):
    cmds.select(clear=1)
    sel = [mesh + '.vtx[{0}]'.format(i) for i in dwu.create_maya_ranges(index)]
    cmds.select(sel)


sel = cmds.ls(sl=True, fl=True)
mesh = dwu.lsTr(sel, dag=True, type='shape')[0]
deformer = [i for i in sel if dwpresets.isDeformer(i)][0]
_type = cmds.nodeType(deformer)
if 'blendShape' == _type:
    myDic01 = getBSinfo(deformer)
else:
    myDic01 = getDeformerInfo(deformer)

cont = selIndexFromValue(myDic01['mainWeight'])
selectWeightedVertices(mesh, cont)