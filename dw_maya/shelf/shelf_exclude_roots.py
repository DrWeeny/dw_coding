import maya.cmds as cmds

# external
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_deformers as dwdef
import dw_maya.dw_decorators as dwdeco

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#
@dwdeco.viewportOff
def excludeRoots(curves = '*:animWires', excludeLast = True):
    crvs = dwu.lsTr(curves, dag=True, type='nurbsCurve', ni=True)
    nb = len(crvs)
    deformers = []

    for x, c in enumerate(crvs):
        hist = [d for d in cmds.listHistory(c)]

        for h in hist:
            if dwdef.is_deformer(h):
                if 'tweak' in h:
                    break
                else:
                    deformers.append(h)

        components = c + '.cv[0:1]'
        if deformers:
            if excludeLast:
                deformers = deformers[:-2]
            for d in deformers:
                dwdef.editDeformer(d, components, remove=True)

        print(f'progress : {float(x) / float(nb):.0%}')
    print('progress : completed')