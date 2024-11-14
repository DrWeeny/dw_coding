import sys, os

# ----- Edit sysPath -----#
rdPath = '/home/abtidona/private/PycharmProjects/RND/dw_tools/maya/RFX'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
import dw_maya_utils as dwu
import dw_alembic_utils as dwabc
import dw_nucleus_utils as dwnx

CHARACTER = 'winnie'

nodes = dwu.lsTr('*:cache:cache_GRP', dag=True, type=['nurbsCurve', 'mesh'])

rfx_nodes = cmds.ls(type='rfxAlembicCacheDeformer')
rfx_abc = [i for i in rfx_nodes if 'animCache' in i][-1]
rfx_wrp_time = [c for c in cmds.listConnections(rfx_abc + '.time') if 'TimeWarp' in c][0]

filepath = cmds.getAttr(rfx_abc+'.filename')
abc = dwabc.importAbc(filepath)
body_con = cmds.ls('body_CON', long=True)[0]
grp_del = '|' + body_con.split('|')[1]
grp_abc = abc.values()[0]
if grp_del in grp_abc:
    grp_abc.remove(grp_del)
    cmds.delete(grp_abc)

cmds.connectAttr(rfx_wrp_time + '.outTime', abc.keys()[0] + '.time', force=True)

ctrl = dwnx.create_curve_ctrl(CHARACTER)

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
