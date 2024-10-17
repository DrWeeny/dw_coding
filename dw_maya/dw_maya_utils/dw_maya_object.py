#!/usr/bin/env python
#----------------------------------------------------------------------------#
#------------------------------------------------------------------ HEADER --#

"""
@author:
    abtidona

@description:
    this is a description

@applications:
    - groom
    - cfx
    - fur
"""

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#

# built-in
import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools\\maya'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

import re
from typing import List, Optional
# internal
from maya import cmds, mel
# external
from .dw_maya_data import Flags
from dw_maya.dw_decorators import acceptString

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

@acceptString('curves')
def change_curve_pivot(curves: Optional[List[str]] = None,
                       index: int = 0):
    """
    Change the scale and rotate pivots of the given curves to the specified CV (control vertex) position.

    Args:
        curves (list of str, optional): A list of curve names whose pivots should be changed.
        index (int): The CV index to use as the pivot position.

    Raises:
        ValueError: If no curves are provided or if the CV index cannot be found.
    """
    if curves is None:
        raise ValueError("No curves provided. Please provide a list of curve names.")

    for c in curves:
        try:
            # Try to get the world space position of the control vertex at the specified index
            coord = cmds.pointPosition(f"{c}.cv[{index}]")
        except Exception as e:
            # Handle intermediate objects
            sh = cmds.listRelatives(c, ni=True, f=True) or cmds.listRelatives(c, f=True)

            if sh:
                cmds.setAttr(f"{sh}.intermediateObject", 0)
                coord = cmds.pointPosition(f"{c}.cv[{index}]")
                cmds.setAttr(f"{sh}.intermediateObject", 1)
            else:
                raise e
        if coord:
            cmds.xform(c, scalePivot=coord, ws=True)
            cmds.xform(c, rotatePivot=coord, ws=True)


def get_common_roots(sel: List[str]) -> List[str]:
    """
    Get the common hierarchy root nodes from the selected objects.

    Args:
        sel (list of str): A list of selected objects.

    Returns:
        list of str: A list of the common root nodes, with full paths.

    Example:
        get_common_roots(['pCube1|pCubeShape1', 'pSphere1|pSphereShape1'])
        ['/pCube1', '/pSphere1']
    """
    # Get the full paths of the selected objects
    test = cmds.ls(sel, long=True)
    # Extract the root node (the first node after '|')
    roots = list(set([i.split('|')[1] for i in test]))
    return cmds.ls(roots, long=True)

def lsTr(*args, **kwargs) -> List[str]:
    """
    A combination of cmds.ls and cmds.listRelatives
    flags derived from cmds.ls, This function is used for user interaction because maya
    process type node which are hidden behind a transform name

    Custom flags:
        - parent, p (bool): If True, return transforms by default.
        - unique, u (bool): Remove duplicate names from the result.

    Args:
        *args: Arguments to pass to cmds.ls.
        **kwargs: Keyword arguments, including custom flags.

    Returns:
        List[str]: A list of object names that match the criteria.
    """

    parent = Flags(kwargs, None, 'parent', 'p')
    long_name = Flags(kwargs, None, 'long', 'l')
    unique = Flags(kwargs, True, 'unique', 'u')

    if not parent:
        flags = {'parent': parent}
    else:
        flags = {'parent': True}
    if 'parent' in kwargs:
        del kwargs['parent']
    if 'p' in kwargs:
        del kwargs['p']
    if long_name:
        # this is only for the corresponding flag of listRelatives
        flags['f'] = True
    if 'unique' in kwargs:
        del kwargs['unique']
    if 'u' in kwargs:
        del kwargs['u']
    if 'ni' not in kwargs or 'noIntermediate' not in kwargs:
        kwargs['ni'] = True

    # If we have a result, process it
    r = cmds.ls(*args, **kwargs)
    if r:
        _type = [cmds.nodeType(i) for i in r]
        is_tr = list(set(_type))
        if len(is_tr) == 1 and is_tr[0] == 'transform':
            if 'parent' in flags:
                flags['parent'] = False
    if flags['parent']:
        if r:
            try:
                r = cmds.listRelatives(r, **flags)
            except:
                pass
    if unique:
        if r:
            o = list(set(r))
            return o
    return r
