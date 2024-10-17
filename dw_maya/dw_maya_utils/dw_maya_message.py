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

# internal
from maya import cmds, mel
import maya.OpenMaya as om

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

def m_warning(text=str, api=False):
    if api:
        om.MGlobal.displayWarning(text)
    else:
        cmds.warning(text)


# noinspection PyCallByClass
def m_error(text=str, api=False):
    if api:
        om.MGlobal.displayError(text)
    else:
        cmds.error(text)

# noinspection PyCallByClass
def m_message(text=str, api=False):
    if api:
        om.MGlobal.displayInfo(text)
    else:
        sys.stdout.write(text + '\n')