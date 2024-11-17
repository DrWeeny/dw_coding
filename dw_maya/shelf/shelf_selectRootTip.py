import maya.cmds as cmds
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_feathers_utils as dwfeathers

try:
    counter += 1
    index = counter % 2
    new_m_sel = [i.split('.')[0] for i in cmds.ls(sl=True)]
    new_sel = dwu.lsTr(new_m_sel, dag=True, type='nurbsCurve', ni=True)
    if new_m_sel:
        if sorted(new_m_sel) == sorted(m_sel):
            sel = new_sel
        else:
            counter = 0
            index = 0
            m_sel = [i.split('.')[0] for i in cmds.ls(sl=True)]
            sel = dwu.lsTr(m_sel, dag=True, type='nurbsCurve', ni=True)
except:
    counter = 0
    index = 0
    m_sel = [i.split('.')[0] for i in cmds.ls(sl=True)]
    sel = dwu.lsTr(m_sel, dag=True, type='nurbsCurve', ni=True)

selcp = dwfeathers.list_cv_index(sel, -index)
cmds.select(selcp)


