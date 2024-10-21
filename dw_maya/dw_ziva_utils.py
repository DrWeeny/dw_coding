# built-in
import sys
import os
import re

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if rdPath not in sys.path:
    print(f"Adding {rdPath} to sys.path")
    sys.path.insert(0, rdPath)

# internal Maya imports
from maya import cmds, mel

# external imports
import dw_maya.dw_maya_nodes as dwnn
import dw_maya.dw_presets_io as dwpreset

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

def is_ziva_loaded():
    """Check if the Ziva Dynamics plugin is loaded by searching for zSolver nodes."""
    if cmds.pluginInfo('ziva', query=True, loaded=True):
        if cmds.ls(type='zSolver'):
            return True
    return False

def get_ziva_types():
    """Return a list of Ziva node types used in Maya scenes."""
    ZNODES = [
        'zSolverTransform', 'zTet', 'zTissue', 'zBone', 'zCloth', 'zSolver',
        'zEmbedder', 'zAttachment', 'zMaterial', 'zFiber'
    ]
    return ZNODES

#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#
class ZSolver(dwnn.MayaNode):

    ZNODES = [
        'zSolverTransform', 'zTet', 'zTissue', 'zBone', 'zCloth', 'zSolver',
        'zEmbedder', 'zAttachment', 'zMaterial', 'zFiber']

    ZTOP = ['zSolver', 'zBone', 'zTissue', 'zTet', 'zMaterial', 'zAttachment']

    def __init__(self, name, preset={}, blendValue=1):
        super(ZSolver, self).__init__(name, preset, blendValue)

    @property
    def network(self):

        hist = cmds.listHistory(self.sh)

        znodes = [i for i in hist if cmds.nodeType(i) in self.ZTOP]

        return znodes

    def attrPreset(self, node=None):
        preset={}
        for zn in self.network:
            nn = dwnn.MayaNode(zn)
            preset.update(nn.attrPreset(node))
        return preset

    def loadPreset(self, preset=dict, blend=1, targ_ns=':'):

        for node in preset:
            if targ_ns not in [':', '']:
                nodename = targ_ns + ':' + node
            else:
                nodename = node
            if cmds.objExists(nodename):
                if cmds.nodeType(nodename) in self.ZTOP:
                    dwpreset.blendAttrDic(node,
                                          nodename,
                                          preset,
                                          blend)

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#


def conform_exponential():
    """Conform the values of Ziva-related attributes that use exponential components.

    This function searches for attributes in Ziva nodes that have an exponential component (e.g., 'Exp')
    and adjusts their values if they are outside a certain range. The new values and their exponent
    components are updated in the scene.
    """
    ztypes = get_ziva_types()
    znodes = cmds.ls(type=ztypes)

    if not znodes:
        cmds.warning("No Ziva nodes found in the scene.")
        return

    attrs = []
    for znode in znodes:
        attrs.extend(cmds.listAttr(znode))

    p = re.compile(r'^(\w+)(Exp)$')

    exp_attrs = []
    for a in attrs:
        if p.search(a):
            sa = p.search(a).group(1)
            if sa in attrs:
                exp_attrs.append(a)
                exp_attrs.append(sa)

    to_conform = cmds.ls(['{}.{}'.format(n, ea) for ea in exp_attrs for n in znodes])

    if not to_conform:
        cmds.warning("No attributes with exponential components found.")
        return

    for tc in to_conform:
        if not tc.endswith('Exp'):
            try:
                old_value = cmds.getAttr(tc)
                old_exp = cmds.getAttr(tc + 'Exp')
            except:
                cmds.warning(f"Unable to get attribute values for {tc}")
                continue

            if old_value > 10 or old_value < -10:
                exp_not = "{:.2e}".format(old_value)
                v, e = exp_not.split('e')
                new_value = float(v)
                new_exp = int(e)
                e_v = old_exp + new_exp

                if (1 <= e_v <= 12) or (-12 <= e_v <= 1):
                    cmds.setAttr(tc, new_value)
                    cmds.setAttr(tc + 'Exp', e_v)
                    print(f'{tc}\n    Old: {old_value} (value) - {old_exp} (exp)')
                    print(f'    New: {new_value} (value) - {e_v} (exp)')
                else:
                    cmds.warning(f"Exponential value out of range for {tc}: {e_v}")
