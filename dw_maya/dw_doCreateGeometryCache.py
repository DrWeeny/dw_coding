__author__ = 'dw'
__mel_source__= ['getGeometriesToCache.mel',
                 'doCreateGeometryCache.mel',
                 'getCacheFileCmd.mel',
                 'objectLayer.mel',
                 'findExistingCaches.mel',
                 'getCacheDirectory.mel',
                 'getObjectsByCacheGroup.mel',
                 'getNameForCacheSubDir.mel',
                 'basename.mel']

import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
import maya.mel as mel
import os.path
import re

import dw_maya.dw_decorators as dwdeco

# Try to convert this command to a more pythonic command
# doCreateGeometryCache 6 { "2", "1010", "1039", "OneFile", "1", "/user_data/test","0","pSphereShape1_blba","0", "export", "0", "1", "1","0","1","mcx","1" } ;
# doCreateGeometryCache("", "", [1017,1018])

@dwdeco.acceptString("input")
def convertListToMelStr(input_list=[]):
    """
    Converts a Python list into a MEL-compatible string representation.
    This is useful for passing complex data structures to MEL commands.

    Args:
        input_list (list): A list of items to be converted into a MEL string.

    Returns:
        str: A string formatted for MEL.
    """
    output = []
    for item in input_list:
        if isinstance(item, (int, float)):
            output.append(str(item))
        elif isinstance(item, list):
            # Recursively convert inner lists to MEL format.
            output.append('{' + ','.join([f'"{sub_item}"' for sub_item in item]) + '}')
        else:
            output.append(f'"{item}"')

    return '{' + ','.join(output) + '}'


def objectLayer(object: str) -> str:
    """
    Determines which display layer an object belongs to.

    Args:
        object (str): The name of the object to check.

    Returns:
        str: The name of the display layer the object belongs to, or "defaultLayer" if none is found.
    """
    # Check if the object has a drawOverride attribute (only valid layer members do).
    draw_override_attr = f"{object}.drawOverride"
    if not cmds.objExists(draw_override_attr):
        return "defaultLayer"

    # Find the display layer the object is connected to, if any.
    connected_layers = cmds.listConnections(draw_override_attr, type='displayLayer', destination=False)

    # If exactly one connection is found, return the connected display layer.
    if connected_layers and len(connected_layers) == 1:
        return connected_layers[0]

    # If no connection or multiple connections are found, return "defaultLayer".
    return "defaultLayer"

def findExistingCaches(shape: str) -> list:
    """
    Finds existing geometry caches or nCaches attached to the given shape node.

    Args:
        shape (str): The name of the shape node to check.

    Returns:
        list: A list of cacheFile nodes or cacheBlend nodes attached to the shape.
    """
    # Initialize an empty result list to store found caches.
    result = []

    # Retrieve history nodes, with pruning based on node type.
    if cmds.nodeType(shape) != "nCloth":
        history = cmds.listHistory(shape, pruneDagObjects=True) or []
    else:
        history = cmds.listHistory(shape, level=1) or []

    # Search through the history for cacheFile or cacheBlend nodes.
    for historyNode in history:
        if cmds.nodeType(historyNode) == "cacheFile":
            result.append(historyNode)
        elif cmds.nodeType(shape) == "nCloth" and cmds.nodeType(historyNode) == "cacheBlend":
            blendHistory = cmds.listHistory(historyNode, level=1) or []
            result.extend([node for node in blendHistory if cmds.nodeType(node) == "cacheFile"])

    # If no caches were found and the shape is not an nCloth or nParticle, look upstream for more caches.
    if not result and cmds.nodeType(shape) not in ["nCloth", "nParticle"]:
        allHistory = cmds.listHistory(shape) or []
        for historyNode in allHistory:
            if cmds.nodeType(historyNode) == "nCloth":
                result = findExistingCaches(historyNode)  # Recursively find caches for nCloth nodes.
                break

            isDagNode = cmds.ls(historyNode, type='dagNode')
            if isDagNode:
                break

    return result


def objIsDrawn(shape: str) -> bool:
    """
    Check if the given shape is drawn (visible in the scene). Returns False if:
    - The shape's visibility is off.
    - The shape belongs to a hidden layer.

    Args:
        shape (str): The shape node to check.

    Returns:
        bool: True if the shape is drawn (visible), otherwise False.
    """
    # Check if the shape itself is visible
    if not cmds.getAttr(f"{shape}.visibility"):
        return False

    # Check the layer the shape belongs to
    layer = objectLayer(shape)
    if layer != "defaultLayer":  # Only check layer visibility if it's not the default layer
        layer_visibility = cmds.getAttr(f"{layer}.visibility")
        layer_enabled = cmds.getAttr(f"{layer}.enabled")
        if not layer_visibility and layer_enabled:
            return False

    return True


def getGeometriesToCache() -> list:
    """
    Retrieves the geometries that are eligible for caching based on the current selection in Maya.
    This function will return deformable shapes that are drawn and ensure no more than one cachable child per transform.

    Returns:
        list: A list of shape nodes that are eligible for caching.
    """
    shapes = cmds.ls(sl=True, type='shape')

    # If no shapes are selected, check for transforms and find their cachable child shapes
    if not shapes:
        selected_transforms = cmds.ls(sl=True, type='transform')
        for sel_obj in selected_transforms:
            cachable_child_count = 0
            child_shapes = cmds.listRelatives(sel_obj, pa=True, ni=True, shapes=True, type='shape')

            if child_shapes:
                for shape in child_shapes:
                    if cmds.ls(shape, type='deformableShape') and objIsDrawn(shape):
                        shapes.append(shape)
                        cachable_child_count += 1

            if cachable_child_count > 1:
                cmds.error(f'MoreThanOneCandidate: {sel_obj}')

    # Include geometries that are in cache groups with the specified geometries
    for shape in shapes[:]:  # Copy list to avoid modifying while iterating
        caches = findExistingCaches(shape)
        for cache in caches:
            cached_geometries = cmds.cacheFile(cache, q=True, geometry=True)
            for geom in cached_geometries:
                if cmds.ls(geom, type='controlPoint') and geom not in shapes:
                    shapes.append(geom)

    return shapes


def objSharesCache(obj: str, otherCaches: list) -> bool:
    """
    Checks if the given object shares any caches with the provided list of caches.

    Args:
        obj (str): The name of the object to check.
        otherCaches (list): A list of cache nodes to compare against.

    Returns:
        bool: True if the object shares at least one cache with `otherCaches`, False otherwise.
    """
    caches = findExistingCaches(obj)
    # Return True if there is an intersection between the object's caches and otherCaches
    return any(cache in otherCaches for cache in caches)


def getObjectsByCacheGroup(objs: list) -> list:
    """
    Groups objects by their shared cache and appends a separator between different cache groups.
    Objects without caches are grouped separately at the end.

    Args:
        objs (list): A list of objects to group by shared caches.

    Returns:
        list: A list of objects grouped by their shared cache, separated by '*'.
    """
    result = []
    separator = '*'
    cacheless = []  # Will store objects that have no associated cache

    if len(objs) <= 1:
        return objs

    for obj in objs:
        if obj in result:  # Skip objects already added to the result
            continue

        caches = findExistingCaches(obj)
        if not caches:  # No cache found, add to cacheless list
            cacheless.append(obj)
            continue

        # Add object and objects sharing the same cache to result
        result.append(obj)
        for other_obj in objs:
            if other_obj not in result and objSharesCache(other_obj, caches):
                result.append(other_obj)

        result.append(separator)  # Add separator after each cache group

    # If all objects are cacheless, return the cacheless list
    if len(cacheless) == len(objs):
        return cacheless

    # Clean up trailing separator and add cacheless objects to the result
    if result and result[-1] == separator:
        result.pop()  # Remove trailing separator if present

    # Append cacheless objects after the last separator
    if cacheless:
        result.append(separator)
        result.extend(cacheless)

    return result


def clashesWithInSceneCacheFile(descriptionFileNames=[], cachesToBeDeleted=[]) -> bool:
    """
    Checks if any of the given cache description files already exist in the scene.

    Args:
        descriptionFileNames (list): A list of cache description file names to check for conflicts.
        cachesToBeDeleted (list): A list of cache files that are planned to be deleted and should be excluded from the check.

    Returns:
        bool: True if any of the description file names clash with existing cache files, False otherwise.
    """
    allCacheFiles = cmds.ls(type='cacheFile')

    for cacheFile in allCacheFiles:
        if cacheFile in cachesToBeDeleted:
            continue

        cachePath = cmds.getAttr(f"{cacheFile}.cachePath")
        cacheName = cmds.getAttr(f"{cacheFile}.cacheName")
        cacheFileName = f"{cachePath}{cacheName}.xml"

        if cacheFileName in descriptionFileNames:
            return True

    return False


def uniqueName(baseName, nameToExclude=list):
    """
    Generates a unique name by appending a 3-digit suffix to the base name.

    If the baseName does not end with _xxx (where xxx is a 3-digit number), it appends _001. If names that match the pattern
    already exist in nameToExclude, the function generates the next available number in the sequence.

    Args:
        baseName (str): The base name to which the suffix will be appended.
        nameToExclude (list): A list of names to exclude, usually the names already existing in the scene.

    Returns:
        str: A unique name with a 3-digit suffix.
    """

    # Check if baseName already ends with '_xxx'
    if not re.search(r'_\d{3}$', baseName):
        # Generate a pattern to match similar names that end with _xxx
        pattern = baseName + r'_\d{3}$'
        invalidNames = [name for name in nameToExclude if re.search(pattern, name)]

        if not invalidNames:
            return f"{baseName}_001"
        else:
            # Extract the highest existing number and increment it
            latest_suffix = sorted([int(re.findall(r'_(\d{3})$', name)[0]) for name in invalidNames])[-1] + 1
            return f"{baseName}_{latest_suffix:03d}"

    else:
        # If baseName already ends with _xxx, extract the base part without the suffix
        base_pattern = baseName[:-4] + r'_\d{3}$'
        invalidNames = [name for name in nameToExclude if re.search(base_pattern, name)]

        if invalidNames:
            # Extract the highest existing number and increment it
            latest_suffix = sorted([int(re.findall(r'_(\d{3})$', name)[0]) for name in invalidNames])[-1] + 1
            return f"{baseName[:-4]}_{latest_suffix:03d}"
        else:
            return baseName


def getNameForCacheSubDir(unique=False, mainDir="", subDirName=""):
    """
    Returns a name to use as the cache subdirectory name.

    If `unique` is True, the function ensures the subdirectory name does not overlap with an existing directory name.
    If `subDirName` is not provided, it uses the current scene name as the subdirectory name.
    If the scene is unnamed, a default name (e.g., "UntitledScene") is used.

    Args:
        unique (bool): If True, ensures the directory name is unique.
        mainDir (str): The base directory where the subdirectory will be created.
        subDirName (str): The desired subdirectory name. If not provided, the scene name is used.

    Returns:
        str: The subdirectory name, ensuring uniqueness if requested.
    """

    baseDirName = mainDir

    # Use the scene name if subDirName is not provided
    if not subDirName:
        sceneName = cmds.file(shortName=True, q=True, sceneName=True)
        if sceneName:
            subDirName = os.path.splitext(sceneName)[0]  # Get the scene name without the extension
            baseDirName = os.path.join(mainDir, subDirName)
        else:
            # If the scene has no name, use a default name
            subDirName = mel.eval('uiRes("m_getNameForCacheSubDir.kUntitledScene")')
            baseDirName = os.path.join(mainDir, subDirName)
    else:
        baseDirName = os.path.join(mainDir, subDirName)

    if unique:
        # Ensure the directory name is unique
        dirPath = baseDirName
        parentDir = os.path.dirname(dirPath)

        if os.path.exists(parentDir):
            # Get the list of existing directories in the parent directory
            existingDirs = os.listdir(parentDir)
            # Use the uniqueName function to generate a unique directory name
            subDirName = uniqueName(subDirName, existingDirs)
            return os.path.join(mainDir, subDirName)

    return os.path.join(mainDir, subDirName)


def getCacheDirectory(directory="", filerule="", objsToCache=[], fileName="", useAsPrefix=0,
                      perGeometry=0, replaceMode="", force=0, points=1):
    """
    Determine and return the cache directory, handling unique naming, file conflicts, and user choices.

    Args:
        directory (str): Base directory for the cache.
        filerule (str): Maya workspace rule for cache location.
        objsToCache (list): Objects that will be cached.
        fileName (str): Name of the cache file.
        useAsPrefix (int): Whether to use the fileName as a prefix.
        perGeometry (int): Whether to cache per geometry.
        replaceMode (str): Replace mode ("replace" to overwrite existing caches).
        force (int): Force overwriting without user prompt.
        points (int): Option to handle point caches.

    Returns:
        str: The cache directory path or "" if the operation is cancelled.
    """

    # Set the base directory
    if not directory:
        directory = cmds.workspace(filerule, q=True, fileRuleEntry=True)
        directory = cmds.workspace(en=directory) + "/"
        subDir = getNameForCacheSubDir(unique=False, mainDir=directory, subDirName="")
        baseDirectory = directory
        directory += subDir
    else:
        if not directory.endswith('/'):
            directory += '/'
        subDir = os.path.basename(os.path.normpath(directory))
        baseDirectory = directory[:-len(subDir) - 1]

    cacheDirectory = directory

    # Check if the directory exists
    if cmds.file(cacheDirectory, q=True, exists=True):
        descriptionFileNames = []

        # Handle point caches
        if points:
            if not fileName or perGeometry == 1:
                descriptionFileNames = ['{0}/{1}.xml'.format(cacheDirectory, obj) for obj in objsToCache if
                                        os.path.exists('{0}/{1}.xml'.format(cacheDirectory, obj))]
            else:
                path = '{0}/{1}.xml'.format(cacheDirectory, fileName)
                if os.path.exists(path):
                    descriptionFileNames.append(path)

        # Check if description files exist
        dfExists = any(cmds.file(df, q=True, exists=True) for df in descriptionFileNames)

        # Handle existing caches
        existingCaches = []
        if replaceMode == "replace":
            for obj in objsToCache:
                existingCaches.extend(findExistingCaches(obj))

        if dfExists and clashesWithInSceneCacheFile(descriptionFileNames, existingCaches):
            # Create a unique subdirectory if a cache file exists and force isn't set
            subDir = getNameForCacheSubDir(unique=True, mainDir=baseDirectory, subDirName=subDir)
            cacheDirectory = os.path.join(baseDirectory, subDir)
            dfExists = False

        # If files exist and force is not enabled, ask the user for action
        if dfExists and not force:
            replace = mel.eval('uiRes("m_getCacheDirectory.kReplace");')
            rename = mel.eval('uiRes("m_getCacheDirectory.kRename");')
            noReplace = mel.eval('uiRes("m_getCacheDirectory.kDoNotReplace");')
            cancel = mel.eval('uiRes("m_getCacheDirectory.kCancel");')
            format_msg = mel.eval('uiRes("m_getCacheDirectory.kReplaceExistingFmt");')
            msg = format_msg.replace('^1s', descriptionFileNames[0])

            userChoice = cmds.confirmDialog(
                title=mel.eval('uiRes("m_getCacheDirectory.kCreateCacheWarning")'),
                message=msg, messageAlign="left",
                button=[rename, noReplace, cancel, replace],
                defaultButton=rename, cancelButton=cancel, dismissString=cancel
            )

            if userChoice == cancel:
                return ""
            elif userChoice == rename:
                return "rename"
            elif userChoice == noReplace:
                cacheDirectory = getNameForCacheSubDir(unique=True, mainDir=baseDirectory, subDirName=subDir)

    if not subDir:
        return ""

    return cacheDirectory


def doCreateGeometryCache(selection=[], fileName='', cacheDirectory='', timeRange=None,
                          action='export', worldSpace=1, dataType=1, format='mcx',
                          distribution="OneFile", refresh=1, perGeometry=1,
                          useAsPrefix=0, force=0, simulationRate=1, sampleMultiplier=1,
                          inherit=0, **kwargs):
    """
    Create cache files for the selected geometry shapes.

    Args:
        fileName (str): Name of the cache file.
        cacheDirectory (str): Directory to store the cache.
        timeRange (list): Start and end time for the cache.
        action (str): Cache action ('add', 'replace', 'merge', 'export').
        worldSpace (int): Whether to export in world space (1) or local space (0).
        dataType (int): Data type to store (0 for float, 1 for double).
        format (str): Cache format (default is 'mcx').
        distribution (str): Cache distribution type ('OneFile' or 'OneFilePerFrame').
        refresh (int): Whether to refresh during caching (1 = refresh, 0 = no refresh).
        perGeometry (int): Create a cache per geometry (1 = yes, 0 = no).
        useAsPrefix (int): Use the specified fileName as a prefix (1 = yes, 0 = no).
        force (int): Force overwrite existing files (1 = yes, 0 = no).
        simulationRate (int): Rate at which simulation is run.
        sampleMultiplier (int): Multiplier for sample rate.
        inherit (int): Inherit cache modifications (1 = yes, 0 = no).
        **kwargs: Additional parameters.

    Returns:
        list: List of cache files created.
    """
    cacheFiles = []
    debug = kwargs.get('debug', 0)

    # Set start and end time based on timeRange or current playback range
    if timeRange is None:
        startTime = cmds.playbackOptions(q=True, min=True)
        endTime = cmds.playbackOptions(q=True, max=True)
    else:
        startTime, endTime = timeRange

    # Handle unimplemented actions (like merge)
    if action in ("merge", "mergeDelete"):
        # TODO : check the proc doMergeCache
        # return doMergeCache(1, startTime, endTime, distribution, cacheDirectory,
        #                   fileName, useAsPrefix, force, simulationRate, sampleMultiplier, action, "geom", format)
        print(f'Action "{action}" is not implemented yet.')
        return None

    if selection:
        cmds.select(cmds.ls(selection), deselect=True)
    else:
        cmds.select(cmds.ls(sl=True, type='cacheFile'), deselect=True)
    objsToCache = getGeometriesToCache()

    if not objsToCache:
        raise ValueError("You must select valid geometry to create a cache.")

    if action == "add":
        # Handle cache replacement
        if mel.eval('getCacheCanBeReplaced({})'.format(convertListToMelStr(objsToCache))):
            if mel.eval('cacheReplaceNotAdd({})'.format(convertListToMelStr(objsToCache))):
                action = "replace"

    if action == "replace" and not mel.eval('getCacheCanBeReplaced({})'.format(convertListToMelStr(objsToCache))):
        return cacheFiles

    # Handle directory creation and cache conflict checking
    cacheDirectory = getCacheDirectory(cacheDirectory, "fileCache", objsToCache, fileName, useAsPrefix,
                                       perGeometry, action, force, 1)
    if debug:
        print(f'Cache directory: {cacheDirectory}')

    if not cacheDirectory:
        return cacheFiles

    # Delete existing caches if replacing
    if action == "replace":
        for obj in objsToCache:
            existingCaches = mel.eval('findExistingCaches("{}")'.format(obj))
            for cache in existingCaches:
                if cmds.getAttr(f"{cache}.enable"):
                    mel.eval(f'deleteCacheFile(2, {{"keep",{cache}}});')

    # Prepare to write the cache
    cacheFiles = generateCacheFiles(objsToCache, cacheDirectory, fileName, startTime, endTime, dataType, worldSpace,
                                    distribution, perGeometry, simulationRate, sampleMultiplier, refresh, useAsPrefix,
                                    action, format)

    if action == "export":
        return [f"{cacheDirectory}/{cf}.xml" for cf in cacheFiles]

    # Attach the caches to the geometry
    attachCaches(objsToCache, cacheFiles, cacheDirectory, action, format, perGeometry)

    cmds.select(objsToCache, r=True)
    return cacheFiles


# ---------------- Helper Functions ---------------- #

def generateCacheFiles(objsToCache, cacheDirectory, fileName, startTime, endTime, dataType, worldSpace, distribution,
                       perGeometry, simulationRate, sampleMultiplier, refresh, useAsPrefix, action, format):
    """
    Generate cache files for the selected objects.

    Returns:
        list: The cache file names.
    """
    if fileName:
        cacheFiles = cmds.cacheFile(doubleToFloat=dataType, directory=cacheDirectory, cacheFormat=format,
                                    format=distribution, refresh=refresh, singleCache=perGeometry, prefix=useAsPrefix,
                                    smr=simulationRate, spm=sampleMultiplier, fileName=fileName, st=startTime,
                                    et=endTime, worldSpace=worldSpace, points=objsToCache)
    else:
        cacheFiles = cmds.cacheFile(doubleToFloat=dataType, directory=cacheDirectory, cacheFormat=format,
                                    format=distribution, refresh=refresh, singleCache=perGeometry, prefix=useAsPrefix,
                                    smr=simulationRate, spm=sampleMultiplier, st=startTime, et=endTime,
                                    worldSpace=worldSpace, points=objsToCache)
    return cacheFiles


def attachCaches(objsToCache, cacheFiles, cacheDirectory, action, format, perGeometry):
    """
    Attach the generated caches to the history switch.
    """
    if perGeometry == 1 or len(objsToCache) == 1:
        attachListArg = [cacheFiles, objsToCache, cacheDirectory, action, format]
        melList = convertListToMelStr(attachListArg)
        mel.eval(f'attachOneCachePerGeometry({melList});')
    else:
        if len(cacheFiles) != 1:
            raise ValueError("Invalid Cache Options")
        attachListArg = [cacheFiles, objsToCache, cacheDirectory, action, format]
        melList = convertListToMelStr(attachListArg)
        mel.eval(f'attachCacheGroups({melList});')

