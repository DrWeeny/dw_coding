import sys, os

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
