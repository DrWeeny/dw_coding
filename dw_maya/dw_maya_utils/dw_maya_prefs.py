"""Provides utilities for handling Maya preferences, versions, and project settings.

A module to manage Maya version information, preferences paths, project settings,
and other Maya environment configuration details.

Functions:
    get_maya_version(): Get Maya version information
    get_maya_prefs(): Get Maya preferences directory
    get_current_fps(): Get current scene's FPS setting
    make_project_dir(): Create Maya project directory structure
    set_project(): Set Maya project with proper workspace settings
    get_scene_name(): Get current scene name/path

Main Features:
    - Comprehensive Maya version tracking (main version, API, Qt)
    - FPS handling with support for all Maya framerates
    - Project directory management and workspace configuration
    - Scene name resolution using both cmds and API methods
    - Performance optimized with internal caching

Common Usage:
    >>> from dw_maya_utils import get_maya_version, set_project
    >>> version = get_maya_version()
    >>> set_project("/path/to/project")

Version: 1.0.0

Author:
    DrWeeny
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Union
from dataclasses import dataclass

from maya import cmds, mel
import maya.OpenMaya as om
from dw_logger import get_logger

logger = get_logger()


@dataclass
class MayaVersionInfo:
    """Container for Maya version information."""
    version: str
    api_version: str
    qt_version: Optional[str]
    os_bits: int


# Global cache for Maya internal data
_MAYA_CACHE: Dict[str, Union[str, int]] = {}

def _get_cached_data(key: str, fetch_func: callable) -> Union[str, int]:
    """Get data from cache or fetch and cache it if not present."""
    if key not in _MAYA_CACHE:
        _MAYA_CACHE[key] = fetch_func()
    return _MAYA_CACHE[key]


def get_maya_version() -> MayaVersionInfo:
    """Get comprehensive Maya version information.

    Returns:
        MayaVersionInfo: Dataclass containing version details
    """
    os_bits = _get_cached_data('os_bits',
                               lambda: 64 if cmds.about(os=True) == 'win64' else 32)

    return MayaVersionInfo(
        version=_get_cached_data('version',
                                 lambda: cmds.about(version=True)),
        api_version=_get_cached_data('api_version',
                                     lambda: cmds.about(api=True)),
        qt_version=_get_cached_data('qt_version',
                                    lambda: cmds.about(qt=True)),
        os_bits=os_bits
    )


def maya_release():
    """
    wrap over the version and api to return EXT builds that modify the
    codebase significantly, prefs being set to 20XX.5 is a general clue
    but we use the api build id to be specific
    """
    return str(cmds.about(api=True))


def get_current_fps(return_map: bool = False) -> Union[float, Dict[str, float]]:
    """Get current frames per second setting or complete FPS mapping.

    Args:
        return_map: If True, returns complete mapping of time unit names to FPS values

    Returns:
        Union[float, Dict[str, float]]: Current FPS or complete FPS mapping
    """
    fps_map = {
        # Standard rates
        "game": 15.0, "film": 24.0, "pal": 25.0, "ntsc": 30.0,
        "show": 48.0, "palf": 50.0, "ntscf": 60.0,

        # Extended rates (Maya 2017+)
        "23.976fps": 23.976, "29.97df": 29.97, "47.952fps": 47.952,
        "59.94fps": 59.94, "44100fps": 44100.0, "48000fps": 48000.0,

        # Additional rates
        "2fps": 2.0, "3fps": 3.0, "4fps": 4.0, "5fps": 5.0,
        "6fps": 6.0, "8fps": 8.0, "10fps": 10.0, "12fps": 12.0,
        "16fps": 16.0, "20fps": 20.0, "40fps": 40.0, "75fps": 75.0,
        "80fps": 80.0, "100fps": 100.0, "120fps": 120.0,
        "125fps": 125.0, "150fps": 150.0, "200fps": 200.0,
        "240fps": 240.0, "250fps": 250.0, "300fps": 300.0,
        "375fps": 375.0, "400fps": 400.0, "500fps": 500.0,
        "600fps": 600.0, "750fps": 750.0, "1200fps": 1200.0,
        "1500fps": 1500.0, "2000fps": 2000.0, "3000fps": 3000.0,
        "6000fps": 6000.0
    }

    if return_map:
        return fps_map

    current_unit = cmds.currentUnit(q=True, fullName=True, time=True)
    return fps_map.get(current_unit, 24.0)  # Default to film (24fps) if not found

def maya_install_dir():
    """
    This is more for future reference, we read the key from the win registry
    and return the MAYA_INSTALL_LOCATION
    """
    return os.environ['MAYA_LOCATION']


def make_project_dir(path: Union[str, Path]) -> List[Path]:
    """Create standard Maya project directory structure.

    Args:
        path: Root project directory path

    Returns:
        List[Path]: List of created directory paths
    """
    project_path = Path(path)
    subdirs = [
        'images', 'sourceimages', 'scenes', 'cache', 'data',
        'particles', 'mel', 'sound', 'textures', 'clips', 'assets'
    ]

    created_dirs = []

    # Create root directory if needed
    if not project_path.exists():
        project_path.mkdir(parents=True)
        created_dirs.append(project_path)

    # Create subdirectories
    for subdir in subdirs:
        dir_path = project_path / subdir
        if not dir_path.exists():
            dir_path.mkdir(parents=True)
            created_dirs.append(dir_path)

    return created_dirs


def set_project(path: Union[str, Path]) -> None:
    """Set Maya project and configure workspace.

    Args:
        path: Project root directory path
    """
    project_path = str(Path(path))

    # Define workspace rules
    workspace_rules = {
        'images': 'images',
        'scene': 'scenes',
        'particles': 'particles',
        'diskCache': 'data',
        'mel': 'mel',
        'audio': 'sound',
        'sourceImages': 'sourceimages',
        'movie': 'data',
        'textures': 'textures',
        'clips': 'clips',
        'templates': 'assets'
    }

    # Set project using MEL (required for some internal Maya operations)
    mel.eval(f'setProject "{project_path}"')

    # Configure workspace rules
    for rule, directory in workspace_rules.items():
        cmds.workspace(fileRule=(rule, directory))

    # Ensure directories exist
    make_project_dir(project_path)

    logger.info(f"Project set to: {project_path}")


def get_scene_name(short: bool = False) -> str:
    """Get current scene name/path using OpenMaya for reliability.

    Args:
        short: If True, returns only filename without extension

    Returns:
        str: Scene name/path or "untitled" if scene not saved
    """
    current_file = om.MFileIO.currentFile()

    if not current_file:
        return "untitled"

    if short:
        return Path(current_file).stem

    return current_file
