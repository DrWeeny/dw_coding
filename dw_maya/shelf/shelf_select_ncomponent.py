
import maya.cmds as cmds
# external
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_lsNode as dwls


try:
    counter += 1
    index = counter % modulo
    new_sel = dwu.lsTr(sl=True, dag=True, type='dynamicConstraint')
    if new_sel:
        if new_sel[0] != sel:
            counter = 0
            index = 1
            sel = new_sel[0]
except:
    counter = 0
    index = 1
    sel = dwu.lsTr(sl=True, dag=True, type='dynamicConstraint')[0]
    m_sel = None
#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

def selectComponent(sel, counter):
    sel = dwls.lsNode(sel, dag=True, type='dynamicConstraint')[0]
    ncomponents = sel.nComponents
    modulo = len(ncomponents)
    m_sel = [nc.component for nc in ncomponents]
    cmds.select(m_sel[counter])
    return m_sel


if counter == 0:
    m_sel = selectComponent(sel, index)
    modulo = len(m_sel)
else:
    cmds.select(m_sel[index])
