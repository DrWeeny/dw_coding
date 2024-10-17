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
from maya import cmds

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

def set_template_layer(name: str):
    """
    Create a display layer for the given object name if it doesn't exist, and set its display type to 'template'.

    Args:
        name (str): The name of the object or node in Maya.

    Returns:
        Optional[str]: The name of the created or modified display layer, or None if no layer was created.
    """
    # Check if the object exists
    if not cmds.objExists(name):
        l_name = '{}Layer'.format(name)
        layer = cmds.createDisplayLayer(name=l_name, number=1, e=True)

    # Set the layer display type to 'template' (1)
    cmds.setAttr(f'{l_name}.displayType', 1)
    return l_name