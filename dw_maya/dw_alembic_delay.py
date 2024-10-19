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
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

# internal
from maya import cmds, mel
import re

# internal

# external
import dw_maya.dw_alembic_utils as dwabc
import dw_maya.dw_maya_nodes as dwnn
from dw_maya.dw_lsNode import lsNode
import dw_maya.dw_duplication as dwdup

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

def get_nb() -> int:
    """
    Returns the next available number for a delayed namespace (e.g., delayed01, delayed02).

    Returns:
        int: The next available number for the delayed namespace.
    """
    p = re.compile(r'delayed(\d+)')
    lsns = cmds.namespaceInfo(ls=True, lon=True)

    # Find all delayed namespaces
    delayed = [p.search(d).group(1) for d in lsns if p.search(d)]

    # Return the next available number
    return int(sorted(delayed)[-1]) + 1 if delayed else 1


def connectDelay(path: str, delay: int = 2):
    """
    Imports an Alembic file and applies a time delay to the animation using the 'addDoubleLinear' node.

    Args:
        path (str): The path to the Alembic file.
        delay (int): The delay to apply (positive or negative).

    Returns:
        dict: The imported Alembic nodes as a dictionary, with the delay applied to the time attribute.
    """
    # Get the next available number for the delayed namespace
    nb = get_nb()

    # Access the time1 node
    time = dwnn.MayaNode('time1')

    # Import Alembic and create a delayed namespace
    abc_minus = dwabc.importAbc(path, namespace=f'delayed{nb:02d}')

    # Get the Alembic node
    abc_node = dwnn.MayaNode(list(abc_minus.keys())[0])

    # Set pre_time and create an 'addDoubleLinear' node for time delay
    pre_time = -2  # Default pre-time setting
    name = 'plus' if delay > 0 else 'minus'
    minus = dwnn.MayaNode(f'delay_{name}', 'addDoubleLinear')
    minus.input2 = pre_time

    # Connect the time attributes
    time.outTime > minus.input1
    minus.output > abc_node.time

    return abc_minus


def createDelay(path: str, delay: int = 2):
    """
    Creates a delay effect by importing and blending Alembic files with offsets.

    Args:
        path (str): The file path of the Alembic file to import.
        delay (int): The amount of delay to apply (positive or negative).

    Returns:
        None
    """
    # Get the next available delayed namespace number
    nb = get_nb()

    # Create Alembic imports with time offsets (delays)
    abc_plus = connectDelay(path, -delay + 1)
    abc_minus = connectDelay(path, -delay)

    # Import the Alembic file with a mixed delay namespace
    abc_norm = dwabc.importAbc(path, namespace=f'delayed{nb:02d}')

    # Collect the Alembic node sources (from abc_plus and abc_minus)
    sources = list(abc_plus.values())[0] + list(abc_minus.values())[0]
    target = list(abc_norm.values())[0][0]  # Take the first target node

    # Create a blendShape node for blending the sources onto the target
    bsnode = cmds.blendShape(sources, target)

    # Set blendShape weights
    cmds.blendShape(bsnode, e=True, w=[(0, 0.3)])  # Set the weight for the first source
    cmds.blendShape(bsnode, e=True, w=[(1, 0.1)])  # Set the weight for the second source

    # Set visibility to off for the source nodes
    for s in sources:
        cmds.setAttr(f'{s}.visibility', 0)

    # Group the sources and target for organizational purposes
    cmds.group(sources + [target])


def geoCacheDelay():
    """
    Create a delayed geometry cache setup by duplicating selected node, applying cache offsets, and blending them.
    """
    # Get the current selection
    sel = cmds.ls(sl=True)
    if not sel:
        cmds.error("No selection found!")

    # Duplicate and bake the animation
    node_bake = dwdup.dupAnim(sel)

    # Rename the baked node
    new_name = f"{node_bake[0].rsplit('_', 3)[0]}_delayed_v#"
    delay_main = lsNode(node_bake)[0]
    delay_main.rename(new_name)

    # Duplicate with cache and apply new names
    dup = dwdup.dupWCache(delay_main.tr)
    lag_01_name = f"{dup.rsplit('_', 4)[0]}_lag_001_v#"
    lag_01 = lsNode(dup)[0]
    lag_01.rename(lag_01_name)

    dup = dwdup.dupWCache(delay_main.tr)
    lag_02_name = f"{dup.rsplit('_', 4)[0]}_lag_002_v#"
    lag_02 = lsNode(dup)[0]
    lag_02.rename(lag_02_name)

    # Get cache file nodes from the duplicated nodes
    lag_01_cache = lsNode(lag_01.list_history(type='cacheFile'))[0]
    lag_02_cache = lsNode(lag_02.list_history(type='cacheFile'))[0]

    # Create blendShape between lag nodes and main node
    sources = [lag_01.tr, lag_02.tr]
    bs_node = cmds.blendShape(sources, delay_main.tr, en=1, tc=1, o='world', w=(0, 1), before=True)
    bs = lsNode(bs_node)[0]
    bs.rename('bs_delay_#')

    # Hide animatable attributes in delay_main
    attrs = delay_main[0].listAttr()
    for a in attrs:
        mattr = delay_main.get(a.split('.')[0])
        if mattr.get(k=True):
            mattr.chb_hide()

    # Create offset attributes
    off1 = delay_main.addAttr("offset1", -1)
    off2 = delay_main.addAttr("offset2", -2)

    # Offset the cache start times using addDoubleLinear nodes
    source_start = lag_01_cache.sourceStart.get()
    offset_adl_01 = dwnn.MayaNode(f"{lag_01.tr}_adl", 'addDoubleLinear')
    offset_adl_02 = dwnn.MayaNode(f"{lag_02.tr}_adl", 'addDoubleLinear')

    # Connect offsets to the cache files
    off1 > offset_adl_01.input1
    off2 > offset_adl_02.input1

    offset_adl_01.input2 = source_start
    offset_adl_02.input2 = source_start

    offset_adl_01.output > lag_01_cache.sourceStart
    offset_adl_02.output > lag_02_cache.sourceStart

    # Parent lag nodes to delay_main and hide them
    lag_01.parentTo(delay_main)
    lag_02.parentTo(delay_main)
    lag_01[0].v = 0
    lag_02[0].v = 0
