__author__ = 'abaudoin'

import maya.cmds as cmds

def find_ncloth_setup(sel=None, ncloth=None):

    ncloths, imesh, omesh = None, None, None
    hist_past = cmds.listHistory(sel, f=0, bf=1, af=1)
    hist_future = cmds.listHistory(sel, f=1, af=1)

    # sel = selection[0]
    for hp in hist_past[1:]:
        if cmds.nodeType(hp) == 'nCloth' and not ncloths:
            ncloths = hp
            continue
        if cmds.nodeType(hp) == 'mesh':
            if ncloths:
                imesh = hp
                omesh = hist_past[0]
            break

    if not ncloths:
        for hf in hist_future[1:]:
            if cmds.nodeType(hf) == 'nCloth' and not ncloths:
                ncloths = hf
                continue
            if cmds.nodeType(hf) == 'mesh':
                if ncloths:
                    imesh = hist_future[0]
                    omesh = hf
                break

    return [ncloths, imesh, omesh]

def show_inp_curr():

    # Show Current MEsh
    error = True
    selection = cmds.ls(sl=True, dag=True, ni=True, type='mesh')
    if len(selection) > 1:
        error = False
    for sel in selection:
        ncloths, imesh, omesh = find_ncloth_setup(sel)

        if not ncloths:
            ncloths = cmds.listConnections(sel, sh=1, type='nCloth')
            if not ncloths:
                if error:
                    cmds.error(
                        'skipping {} because no ncloth found'.format(sel))
                else:
                    cmds.warning(
                        'skipping {} because no ncloth found'.format(sel))
                    continue

            imesh = [i for i in cmds.listHistory(ncloths, f=0, bf=1, af=1) if
                     cmds.nodeType(i) == 'mesh'][0]
            omesh = [i for i in cmds.listHistory(ncloths, f=1, bf=1, af=1) if
                     cmds.nodeType(i) == 'mesh'][0]

        if sel not in [imesh, omesh]:
            omesh = cmds.listConnections('{}.{}'.format(ncloths, 'outputMesh'),
                                         sh=1, type='mesh') or []
            cmds.warning(
                'warning: {} might be badly setup for output'.format(sel))
            if not omesh:
                if error:
                    cmds.error(
                        'skipping {} because no output found'.format(sel))
                else:
                    cmds.warning(
                        'skipping {} because no output found'.format(sel))
                    continue

        if imesh != sel:
            cmds.setAttr('{}.{}'.format(sel, 'intermediateObject'), 1)
            cmds.setAttr('{}.{}'.format(imesh, 'intermediateObject'), 0)
        elif imesh == sel:
            cmds.setAttr('{}.{}'.format(omesh, 'intermediateObject'), 0)
            cmds.setAttr('{}.{}'.format(imesh, 'intermediateObject'), 1)

    # refresh any outliner editors
    eds = cmds.lsUI(editors=True)
    for ed in eds:
        if cmds.outlinerEditor(ed, exists=True):
            cmds.outlinerEditor(ed, e=True, refresh=True)

show_inp_curr()
