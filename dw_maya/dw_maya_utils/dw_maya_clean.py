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

# internal

# external


#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#


def clean_unused_nodes():
    """
    Delete unused nodes in the Maya scene (equivalent to 'Delete Unused Nodes' in Hypershade).
    """
    try:
        mel.eval('MLdeleteUnused;')
        print("Unused nodes deleted successfully.")
    except RuntimeError as e:
        print(f"Failed to delete unused nodes: {e}")


def delete_unknown_nodes():
    """
    Delete unknown nodes in the Maya scene and log the deleted nodes.
    Types targeted: 'unknown', 'unknownDag', 'unknownTransform'.
    """
    nodeList = cmds.ls(type=["unknown", "unknownDag", "unknownTransform"])
    try:
        if nodeList:
            cmds.delete(nodeList)
            text = '\n{}'.format(' ' * 32).join(nodeList)
            print('delete_unknown_nodes has deleted :\n{}'.format(text))
    except:
        for n in nodeList:
            try:
                cmds.delete(n)
            except RuntimeError as e:
                print(f"Error deleting unknown nodes: {n}")


def del_phantom_rl():
    """
    Delete phantom render layers that match the pattern 'defaultRenderLayer*'.
    """
    deleted_count = 0
    render_layers = cmds.ls("defaultRenderLayer*", r=True, type='renderLayer')

    if render_layers:
        for render_layer in render_layers:
            try:
                cmds.delete(render_layer)
                deleted_count += 1
            except RuntimeError as e:
                print(f"Failed to delete render layer {render_layer}: {e}")

    if deleted_count > 0:
        print(f"Deleted {deleted_count} phantom render layer(s).")
    else:
        print("No phantom render layers found.")