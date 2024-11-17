# internal
import maya.cmds as cmds
# external
import dw_maya.dw_maya_nodes as dwnn
from dw_maya.dw_lsNode import lsNode

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

nucleus = lsNode(sl=True, type='nucleus')
if not nucleus:
    nucleus = lsNode(type='nucleus')

spot = dwnn.MayaNode('wind_ctrl_nx', 'spotLight')
vec = dwnn.MayaNode('wind_vector_nx', 'vectorProduct')
speed = dwnn.MayaNode('wind_speed_nx', 'plusMinusAverage')

# spot is directed to -1 in Z at creation
vec.input1Z = -1
vec.operation = 3
vec.normalizeOutput = 1# specify world matrix from shape
spot[1].worldMatrix[0] > vec.matrix
spot.scale > speed.input3D[0]
# set operattion to average
speed.operation = 3

attrs = spot[1].listAttr()
for a in attrs:
    mattr = spot.get(a.split('.')[0])
    if mattr.get(k=True):
        mattr.chb_hide()

for nuc in nucleus:
    vec.output > nuc.windDirection
    speed.output3Dx > nuc.windSpeed
    spot[0].addAttr('windNoise', 0) > nuc.windNoise

cmds.select(spot.tr)
