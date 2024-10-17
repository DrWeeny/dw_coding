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
from typing import List

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools\\maya'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

# internal
from maya import cmds, mel
import maya.OpenMaya as om
# external

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

'''
 Maya Version Mapping History:
 ====================================
 Release         -version    -api     python    -qt       prefs      -d    extra info
 -----------------------------------------------------------------------------------------
  2008          .  2008  .  ??????  .  2.5.1     na    .  2008    . 2007-09-01
  2009          .  2009  .  ??????  .  2.5.1     na    .  2009    . 2008-10-01
  2010          .  2010  .  201000  .  2.6.1     na    .  2010    . 2009-08-01
  2011 Hotfix2  .  2011  .  201102  .  2.6.4    4.5.3  .  2011    .
  2011 SAP      .  2011  .  201104  .  2.6.4    4.5.3  .  2011.5  . 2010-09-29
  2012          .  2012  .  201200  .  2.6.4    4.7.1  .  2012    . 2011-04-01
  2012 SP1      .  2012  .  ??????  .  2.6.4    4.7.1  .  2012    .
  2012 SAP1     .  2012  .  ??????  .  2.6.4    4.7.1  .  2012    . 2012-01-26
  2012 SP2      .  2012  .  201217  .  2.6.4    4.7.1  .  2012    .
  2013 SP1      .  2013  .  201301  .  2.6.4    4.7.1  .  2013    . 2012-07-00
  2013 SP2      .  2013  .  201303  .  2.6.4    4.7.1  .  2013    . 2013-01-00
  2013 EXT      .  2013  .  201350? .  2.6.4    4.7.1  .  2013.5  . 2012-09-25  . 2013 binary incompatible
  2013 EXT2     .  2013  .  201355  .  2.6.4    4.7.1  .  2013.5  . 2013-01-22  . 2013 binary incompatible
  2014          .  2014  .  201400  .  2.6.4    4.8.2  .  2014-x64   . 2013-03-01
  2015          .  2015  .  201500  .  2.7      4.8.5  .  2015-x64   . 2014-04-15
  2015 SP6      .  2015  .  201516  .  2.7      4.8.5  .  2015-x64   . 2015-03-26
  2016          .  2016  .  201600  .  2.7      4.8.6  .  2016    . 2015-04-15
  2016 EXT1 SP6 .  2016  .  201614  .  2.7      4.8.6  .  2016    . 2016-03-18
  2016 EXT2     .  2016  .  201650  .  2.7      4.8.6  .  2016.5  . 2016-03-02 . 2016 binary incompatible
  2017          .  2017  .  201700  .  2.7      5.6.1  .  2017    . 2016-05-15
  2018          .  2018  .  201800  .  2.7      5.6.1  .  2018    . 2017-06-26
  2019          .  2019  .  201900  .  2.7      5.6.1  .  2019    . 2019-01-15
------------------------------------------------------------------------------------------
'''
MAYA_INTERNAL_DATA = {}  # cached Maya internal vars for speed


def cache_maya_internal_data() -> None:
    """
    Populate or update the internal data cache for Maya.

    This function is used to cache various internal Maya data for performance improvements.
    """
    global MAYA_INTERNAL_DATA
    MAYA_INTERNAL_DATA = {
        'version': maya_version(),
        'api_version': maya_version_release(),
        'qt_version': maya_version_qt(),
        'prefs_folder': maya_prefs(),
        'os_build': os_build()
    }


def os_build():
    """
    Get information about the operating system build.

    Returns:
        str: Operating system information (e.g., 'Windows', 'macOS').
    """
    build = cmds.about(os=True)
    if build == 'win64':
        return 64
    elif build == 'win32':
        return 32


def maya_version():
    """
    get the application version back,
    this doesn't track service packs or extensions

    TODO: need to manage this better and use the API version,
          eg: 2013.5 returns 2013
    """
    if 'version' in MAYA_INTERNAL_DATA and MAYA_INTERNAL_DATA['version']:
        return MAYA_INTERNAL_DATA['version']
    else:
        MAYA_INTERNAL_DATA['version'] = cmds.about(version=True)
        return MAYA_INTERNAL_DATA['version']


def maya_version_release():
    """
    get the api version back so we can track service packs etc
    """
    if 'api' in MAYA_INTERNAL_DATA and MAYA_INTERNAL_DATA['api']:
        return MAYA_INTERNAL_DATA['api']
    else:
        MAYA_INTERNAL_DATA['api'] = cmds.about(api=True)
        return MAYA_INTERNAL_DATA['api']


def maya_release():
    """
    wrap over the version and api to return EXT builds that modify the
    codebase significantly, prefs being set to 20XX.5 is a general clue
    but we use the api build id to be specific
    """
    return str(cmds.about(api=True))


def maya_version_qt():
    try:
        if 'qt' in MAYA_INTERNAL_DATA and MAYA_INTERNAL_DATA['qt']:
            return MAYA_INTERNAL_DATA['qt']
        else:
            MAYA_INTERNAL_DATA['qt'] = cmds.about(qt=True)
            return MAYA_INTERNAL_DATA['qt']
    except:
        pass


def maya_prefs():
    """
    Root of Maya prefs folder
    """
    if 'prefs' in MAYA_INTERNAL_DATA and MAYA_INTERNAL_DATA['prefs']:
        return MAYA_INTERNAL_DATA['prefs']
    else:
        MAYA_INTERNAL_DATA['prefs'] = os.path.dirname(cmds.about(env=True))
        return MAYA_INTERNAL_DATA['prefs']


def get_current_fps(return_full_map=False):
    """
    returns the current frames per second as a number,
    rather than a useless string

    Args:
        return_full_map (bool): if True we return a dictionary of timeUnit:fps
        rather than the current actual fps - useful for debugging

    Returns:
        dict :
    """
    fps_dict = {"game": 15.0,
                "film": 24.0,
                "pal": 25.0,
                "ntsc": 30.0,
                "show": 48.0,
                "palf": 50.0,
                "ntscf": 60.0}
    if maya_version() >= 2017:
        new_2017fps = {"2fps": 2.0,
                       "3fps": 3.0,
                       "4fps": 4.0,
                       "5fps": 5.0,
                       "6fps": 6.0,
                       "8fps": 8.0,
                       "10fps": 10.0,
                       "12fps": 12.0,
                       "16fps": 16.0,
                       "20fps": 20.0,
                       "29.97fps": 29.97,
                       "40fps": 40.0,
                       "75fps": 70.0,
                       "80fps": 80.0,
                       "100fps": 100.0,
                       "120fps": 120.0,
                       "125fps": 125.0,
                       "150fps": 150.0,
                       "200fps": 200.0,
                       "240fps": 240.0,
                       "250fps": 250.0,
                       "300fps": 300.0,
                       "375fps": 375.0,
                       "400fps": 400.0,
                       "500fps": 500.0,
                       "600fps": 600.0,
                       "750fps": 750.0,
                       "1200fps": 1200.0,
                       "1500fps": 1500.0,
                       "2000fps": 2000.0,
                       "3000fps": 3000.0,
                       "6000fps": 6000.0}
        fps_dict.update(new_2017fps)
    if maya_version() >= 2018:
        new_2018fps = {"23.976fps": 23.976,
                       "29.97df": 29.97,
                       "47.952fps": 47.952,
                       "59.94fps": 59.94,
                       "44100fps": 44100.0,
                       "48000fps": 48000.0}
        fps_dict.update(new_2018fps)
    if not return_full_map:
        return fps_dict[cmds.currentUnit(q=True, fullName=True, time=True)]
    else:
        return fps_dict


def maya_install_dir():
    """
    This is more for future reference, we read the key from the win registry
    and return the MAYA_INSTALL_LOCATION
    """
    return os.environ['MAYA_LOCATION']


def make_project_dir(path: str) -> List[str]:
    """
    Create a standard project directory structure at the specified path.

    Args:
        path (str): The root project directory where subdirectories will be created.

    Returns:
        List[str]: A list of directories that were created.
    """
    # List of subdirectories to create within the project directory
    subdirs = ['images', 'sourceimages', 'scenes', 'cache', 'data']

    # List to store directories that were created
    created_dirs = []

    # Ensure the main project directory exists
    if not os.path.isdir(path):
        os.makedirs(path)
        created_dirs.append(path)

    # Create each required subdirectory if it doesn't already exist
    for subdir in subdirs:
        dir_path = os.path.join(path, subdir)
        if not os.path.isdir(dir_path):
            os.makedirs(dir_path)
            created_dirs.append(dir_path)

    return created_dirs


def set_project(path: str):
    """

    Args:
        path (str): /path

    Returns:

    """

    # to many proc inside this one, just let use mel.eval
    mel.eval(f'setProject "{path}"')
    # Define the necessary subdirectories
    sub_dirs = {'images': 'images',
                'scene': 'scenes',
                'particles': 'particles',
                'diskCache': 'data',
                'mel': 'mel',
                'audio': 'sound',
                'sourceImages': 'sourceimages',
                'movie': 'data',
                'textures': 'textures',
                'clips': 'clips',
                'templates': 'assets'}

    # Set workspace file rules for each directory
    for k, v in sub_dirs.items():
        cmds.workspace(fileRule=(k, v))

    # make sure that the dirs are created
    make_project_dir(path)


def scene_name(short: bool = False) -> str:
    """
    Return the name of the currently loaded scene in Maya. Handles cases where
    the scene is loaded with errors and the standard `cmds.file()` returns nothing.

    Args:
        short (bool): If True, return only the file name without the extension.
                      If False, return the full file path.

    Returns:
        Optional[str]: The scene name or path. If the scene hasn't been saved, it returns "untitled".
    """
    # Get the current file path using MFileIO
    cur_file = om.MFileIO.currentFile()

    # If no scene is loaded or the scene is untitled, return a placeholder
    if not cur_file:
        return "untitled"

    # Return the short version (file name without path and extension)
    if short:
        return os.path.splitext(os.path.basename(cur_file))[0]

    # Return the full file path
    return cur_file
