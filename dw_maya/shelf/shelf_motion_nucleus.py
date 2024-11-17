import maya.cmds as cmds
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_nucleus_utils as dwnx
import dw_maya.dw_decorators as dwdeco

@dwdeco.viewportOff
@dwnx.tmp_disable_solver
def motion_nucleus():
    range_ = dwu.current_timerange(range_=True)
    vtx_track = cmds.filterExpand(sm=31)[0]
    nucleus = cmds.ls(sl=True, type='nucleus')[0]
    for frm in range_:
        cmds.currentTime(frm, e=True)
        pos = cmds.pointPosition(vtx_track)
        cmds.setAttr(nucleus + '.t', *pos)
        cmds.setKeyframe(nucleus, attribute=['tx', 'ty', 'tz'])
motion_nucleus()
