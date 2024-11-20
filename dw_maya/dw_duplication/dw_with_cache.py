from maya import cmds, mel
from . import dupMesh
import re


def dupWCache(sel=[], cache_path=None):
    """
    Duplicates the selected object and applies the associated cache.

    Args:
        sel: List of selected Maya objects (meshes or other nodes).
        cache_path: Optional file path to a cache XML file for applying to the duplicated object.

    Returns:
        The name of the newly duplicated and cached object.
    """
    # If no selection provided, take the first object in the current selection
    if not sel:
        sel = cmds.ls(sl=True)[0]

    # Duplicate the selected mesh
    feed = dupMesh(sel)

    # Case 1: Cache path provided directly (manual mode)
    if cache_path:
        # Format the MEL command to import the cache from the provided path
        importCacheCmd = 'doImportCacheFile("{0}", "xmlcache", {{"{1}"}}, {{}});'.format(cache_path, feed[0])
        mel.eval(importCacheCmd)

        # Extract version information (vXXX) from cache path if available
        version_match = re.search(r'v\d{3}', cache_path)
        version_str = version_match.group(0) if version_match else ''

        # Rename the duplicated object with a meaningful name based on version and selection
        name = 'sim_{}_{}'.format(version_str, sel).replace('__', '_')
        renamed_obj = cmds.rename(feed[0], name)

        return renamed_obj

    # Case 2: Cache path not provided, infer from existing cache node
    else:
        # Find any existing cache node attached to the selected object
        myCacheNode = cmds.ls(cmds.listHistory(sel), type='cacheFile')

        if myCacheNode:
            # Get the cache path and name from the cache node attributes
            cache_path = cmds.getAttr(myCacheNode[0] + '.cachePath')
            cache_name = cmds.getAttr(myCacheNode[0] + '.cacheName')
            myCachePath = cache_path + cache_name + '.xml'

            # Import the cache file using MEL
            importCacheCmd = 'doImportCacheFile("{0}", "xmlcache", {{"{1}"}}, {{}});'.format(myCachePath, feed[0])
            mel.eval(importCacheCmd)

            # Rename the duplicated object if it doesn't start with 'bake_'
            if not feed[0].startswith('bake_'):
                renamed_obj = cmds.rename(feed[0], 'bake_' + feed[0])
            else:
                renamed_obj = feed[0]

            return renamed_obj
        else:
            cmds.error("No cache node found for the selected object.")
