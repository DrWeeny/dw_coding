
from maya import cmds, mel
import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from dw_maya.dw_decorators import acceptString

@acceptString('node')
def apply_maya_preset(node=list, preset_name=str, _type=None):
    """ use to
    Args:
        node (list): your maya nodes
        preset_name (str): the name of the preset
        _type (list): list of nodes where you try to apply maya preset
    """

    if not _type:
        _type = ['nCloth', 'hairSystem']

    # TODO support maya preset ?
    for s in cmds.ls(node, dag=True, type=_type, long=True):
        mel.eval('applyPresetToNode "{}" "" "" "{}" 1;'.format(s, preset_name))