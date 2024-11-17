import maya.cmds as cmds
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_alembic_utils as dwabc
import dw_maya.dw_nucleus_utils as dwnx
from dw_maya.dw_nucleus_utils.dw_create_hierarchy import create_curve_ctrl


CHARACTER = 'charName'

nodes = dwu.lsTr('*:cache:cache_GRP', dag=True, type=['nurbsCurve', 'mesh'])

pipe_nodes = cmds.ls(type='AlembicNode')
pipe_abc = [i for i in pipe_nodes if 'animCache' in i][-1]
pipe_wrp_time = [c for c in cmds.listConnections(pipe_abc + '.time') if 'TimeWarp' in c][0]

filepath = cmds.getAttr(pipe_abc+'.filename')
abc = dwabc.importAbc(filepath)
body_con = cmds.ls('body_CON', long=True)[0]
grp_del = '|' + body_con.split('|')[1]
grp_abc = list(abc.values())[0]
if grp_del in grp_abc:
    grp_abc.remove(grp_del)
    cmds.delete(grp_abc)

cmds.connectAttr(pipe_wrp_time + '.outTime', list(abc.keys())[0] + '.time', force=True)

ctrl = create_curve_ctrl(CHARACTER)

out_geo = dwu.lsTr('*:geometry_GRP', dag=True, type=['nurbsCurve', 'mesh'])
out_wires = dwu.lsTr('*:animWires', dag=True, type=['nurbsCurve', 'mesh'])
out = [n for n in out_geo+out_wires if not n.endswith('_SIM')]
out = [n for n in out if not n.endswith('_GRO')]


gneh = dwnx.create_loca_cluster(_in=nodes,
                    _out=out,
                    matrix_node='body_CON',
                    cam='shotCamera:master',
                    prefix=CHARACTER,
                    ctrl=ctrl)
