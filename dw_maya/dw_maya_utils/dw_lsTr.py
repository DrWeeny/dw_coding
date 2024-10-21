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
