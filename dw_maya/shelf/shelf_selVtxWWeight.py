
import maya.cmds as cmds
# external
import dw_maya_utils as dwu
import dw_presets_io as dwpresets

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

    Weight_values = cmds.getAttr(f'{deformerNode}.weightList[0].weights[{myRange}]')

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
    baseWeight_values = cmds.getAttr(f'{BS01}.inputTarget[0].baseWeights[{myRange}]')
    # [:] is important, it will force to get every points
    # (not only the one with value) BUGS happening

    # target proc [[tw1],[tw2]], note you should add [:]
    targetWeight_values = []
    for target in range(BS01_targetWeightsNb):
        try:
            targetWeight_values.append(
                cmds.getAttr(BS01 + f'{BS01}.inputTarget[0)].inputTargetGroup[0].tw[{myRange}]'))
        except:
            targetWeight_values.append('error')

    dic = {'mainWeight': baseWeight_values,
           'targetName': BS01_targets,
           'targetsWeight': targetWeight_values}

    return dic

def sel_index_from_value(my_bs_map=None, *args):
    """
    Select indices from the given blend shape map based on specified thresholds.

    Args:
        my_bs_map (list): A list of blend shape values.
        *args: Threshold values to filter indices:
            - If 2 arguments are provided, selects indices where value is between args[0] and args[1].
            - If 1 argument is provided, selects indices where value is greater than args[0].
            - If no arguments are provided, selects indices where value is greater than 0.

    Returns:
        list: A list of indices that meet the specified condition.
    """
    if my_bs_map is None:
        my_bs_map = []

    index_to_sel = []

    # Two thresholds: range-based selection
    if len(args) == 2:
        lower, upper = args
        index_to_sel = [i for i, t in enumerate(my_bs_map) if lower < t < upper]

    # One threshold: greater than selection
    elif len(args) == 1:
        threshold = args[0]
        index_to_sel = [i for i, t in enumerate(my_bs_map) if t > threshold]

    # Default: values greater than 0
    else:
        index_to_sel = [i for i, t in enumerate(my_bs_map) if t > 0]

    return index_to_sel


def select_weighted_vertices(mesh=str, index=[]):
    cmds.select(clear=1)
    sel = [f'{mesh}.vtx[{i}]' for i in dwu.create_maya_ranges(index)]
    cmds.select(sel)


sel = cmds.ls(sl=True, fl=True)
mesh = dwu.lsTr(sel, dag=True, type='shape')[0]
deformer = [i for i in sel if dwpresets.is_deformer(i)][0]
_type = cmds.nodeType(deformer)
if 'blendShape' == _type:
    myDic01 = getBSinfo(deformer)
else:
    myDic01 = getDeformerInfo(deformer)

cont = sel_index_from_value(myDic01['mainWeight'])
select_weighted_vertices(mesh, cont)