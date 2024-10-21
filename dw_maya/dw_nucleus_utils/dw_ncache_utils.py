import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
import maya.mel as mel
from .dw_nx_mel import *
from typing import Optional, List
import re


@acceptString('geometries')
def attach_ncache(fileName=None, geometries=None):

    if not fileName:
        cmds.error("m_doImportCacheFile.kNoFileSpecified")

    channels = cmds.cacheFile(q=1, channelName=1, fileName=fileName)

    if len(geometries) <= 0:
        sel = get_geometries_to_cache()
    else:
        sel = geometries

    if len(geometries) > len(channels):
        msg = "m_doImportCacheFile.kTooFewChannels"
        cmds.error(msg)

    currObj = sel[0]
    nBase = find_type_in_history(currObj, "nBase", 0, 1)
    hsys = find_type_in_history(currObj, "hairSystem", 0, 1)
    attachAttrs = []
    multiChannel = 0


    if len(channels) > 1:
        multiChannel = len(channels)


    if not multiChannel:

        channelToUse = find_channel_for_object(0, channels, currObj)

        inputPointsAttr = ""
        inputRangeAttr = ""
        # first decide if it is an ncloth or a geometry cache
        #
        nBase = find_type_in_history(currObj, "nBase", 0, 1)
        if nBase:
            inputPointsAttr = nBase + ".positions"
            inputRangeAttr = nBase + ".playFromCache"

        cacheFile = cmds.cacheFile(attachFile=True, fileName=fileName,
                       ia=inputPointsAttr, channelName=channelToUse)
        cmds.connectAttr((cacheFile + ".inRange"),
                         inputRangeAttr)
        if len(nBase):
            if cmds.nodeType(nBase) == "nParticle":
                cmds.connectAttr((cacheFile + ".outCacheArrayData"),
                                 (nBase + ".cacheArrayData"),
                                 f=1)

    else:
        # we assume we're just dealing with one object with multiple connections
        # currently hair system, or nCloth with velocity/internalState
        inputRangeAttr = currObj + ".playFromCache"

        attachAttrs = [convert_channelname_to_inattr(channel)
                   for channel in channels]

        cacheFile = cmds.cacheFile(attachFile=True, fileName=fileName,
                       channelName=channels, ia=attachAttrs)

        cmds.connectAttr(cacheFile + ".inRange",
                         inputRangeAttr)


def find_existing_caches(shape: str) -> list:
    """
    Check whether there are caches attached to the given shape.

    Args:
        shape (str): The name of the shape node.

    Returns:
        list: A list of cache nodes attached to the shape.
    """
    result = []

    # Fetch history based on node type
    if cmds.nodeType(shape) == "nCloth":
        history = cmds.listHistory(shape, lv=1) or []
    else:
        history = cmds.listHistory(shape, pdo=1) or []

    # Iterate over history nodes to find cacheFile or cacheBlend nodes
    for node in history:
        if cmds.nodeType(node) == "cacheFile":
            result.append(node)
        elif cmds.nodeType(shape) == "nCloth" and cmds.nodeType(node) == "cacheBlend":
            blend_history = cmds.listHistory(node, lv=1) or []
            for blend_node in blend_history:
                if cmds.nodeType(blend_node) == "cacheFile":
                    result.append(blend_node)

    # If no cache found, handle upstream nodes for special cases
    if not result and cmds.nodeType(shape) not in {"nCloth", "nParticle"}:
        all_history = cmds.listHistory(shape) or []
        for history_node in all_history:
            if cmds.nodeType(history_node) == "nCloth":
                result = find_existing_caches(history_node)
                break

            # Stop if we reach a dagNode
            if cmds.ls(history_node, type='dagNode'):
                break

    return result


def get_geometries_to_cache() -> list:
    """
    Retrieves geometries (shapes) that are eligible for caching from the current selection.
    It checks for deformable shapes and makes sure they are visible and not part of multiple
    cache candidates.

    Returns:
        list: A list of shapes that are valid for caching.
    """
    # Get selected shapes, or look for child shapes of selected transforms
    shapes = cmds.ls(sl=True, type='shape')

    if not shapes:
        # If no shapes were selected, look for transforms with child shapes
        selected_transforms = cmds.ls(sl=True, type='transform')
        for transform in selected_transforms:
            cachable_child_count = 0
            child_shapes = cmds.listRelatives(transform, pa=True, ni=True, shapes=True, type='shape') or []

            for shape in child_shapes:
                if cmds.nodeType(shape) == 'deformableShape' and obj_is_drawn(shape):
                    shapes.append(shape)
                    cachable_child_count += 1

            if cachable_child_count > 1:
                cmds.error(f"MoreThanOneCandidate : {transform}")

    # Ensure any additional geometries from cache groups are also considered
    shape_count = len(shapes)
    for i in range(shape_count):
        caches = find_existing_caches(shapes[i])

        for cache in caches:
            geoms = cmds.cacheFile(cache, q=True, geometry=True) or []

            for geom in geoms:
                # If geom is a control point but not yet included in the shapes list, append it
                if cmds.nodeType(geom) == 'controlPoint' and geom not in shapes:
                    shapes.append(geom)

    return shapes

