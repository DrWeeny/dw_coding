import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from maya import cmds,mel
from dw_maya.dw_decorators import acceptString


@acceptString('selection')
def delete_entire_hairsys(selection):
    """ mel command evaled to delete system

    Args:
        selection (list): nodes
    Notes:
        TODO convert mel
    """
    for i in selection:
        cmds.select(i)
        mel.eval('deleteEntireHairSystem;')
