"""Provides utilities for handling Maya preferences, versions, and project settings.

A module to manage Maya version information, preferences paths, project settings,
and other Maya environment configuration details.

Functions:
    get_maya_version(): Get Maya version information
    get_maya_prefs(): Get Maya preferences directory
    get_current_fps(): Get current scene's FPS setting
    make_project_dir(): Create Maya project directory structure
    set_project(): Set Maya project with proper workspace settings
    get_project_from_scene(): Derive the project root from a scene path
    set_project_from_scene(): Set the project from the scene location
    get_current_project(): Project Maya currently points at
    get_project_history(): Projects active before this one, newest first
    restore_previous_project(): Undo the last project switch
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
    >>> set_project_from_scene()   # project derived from the open scene

Version: 1.0.0

Author:
    DrWeeny
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Union
from dataclasses import dataclass

from maya import cmds, mel
import maya.OpenMaya as om
from dw_logger import get_logger

logger = get_logger()

#: optionVar holding the projects set before the current one, newest first.
#: An optionVar rather than a module global so a tool reload, or a second
#: tool in the same session, still sees the history.
PROJECT_HISTORY_OPTVAR = 'dw_maya_project_history'

#: How many previous projects are remembered.
PROJECT_HISTORY_SIZE = 10


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


def get_current_project() -> Optional[str]:
    """Project Maya is currently pointing at, or None."""
    try:
        return cmds.workspace(query=True, rootDirectory=True) or None
    except Exception as e:
        logger.warning(f"Could not query the current project: {e}")
        return None


def get_project_history() -> List[str]:
    """Projects that were active before the current one, newest first."""
    if not cmds.optionVar(exists=PROJECT_HISTORY_OPTVAR):
        return []
    try:
        history = json.loads(cmds.optionVar(query=PROJECT_HISTORY_OPTVAR))
        return [entry for entry in history if isinstance(entry, str)]
    except (ValueError, TypeError):
        logger.warning("Unreadable project history, starting a new one")
        return []


def _push_project_history(project: Optional[str]) -> None:
    """Remember a project before it is replaced.

    Switching project is global state other tools read for their default
    paths, so every switch is recorded and can be walked back.
    """
    if not project:
        return

    project = Path(project).as_posix().rstrip('/')
    history = get_project_history()
    if history and history[0] == project:
        return

    history = [project] + [entry for entry in history if entry != project]
    cmds.optionVar(stringValue=(PROJECT_HISTORY_OPTVAR,
                                json.dumps(history[:PROJECT_HISTORY_SIZE])))


def restore_previous_project() -> Optional[Path]:
    """Go back to the project that was active before the last switch.

    The project being left is pushed on the history in turn, so calling
    this twice returns where you started.

    Returns:
        Path to the restored project, or None when nothing is remembered.
    """
    history = get_project_history()
    if not history:
        logger.warning("No previous project recorded")
        return None

    previous = history[0]
    cmds.optionVar(stringValue=(PROJECT_HISTORY_OPTVAR,
                                json.dumps(history[1:])))

    if not Path(previous).is_dir():
        logger.error(f"Previous project no longer exists: {previous}")
        return None

    set_project(previous)
    return Path(previous)


def clear_project_history() -> None:
    """Forget every remembered project."""
    if cmds.optionVar(exists=PROJECT_HISTORY_OPTVAR):
        cmds.optionVar(remove=PROJECT_HISTORY_OPTVAR)


def set_project(path: Union[str, Path]) -> None:
    """Set Maya project and configure workspace.

    A folder with no workspace.mel is not a project as far as Maya is
    concerned - setProject on it warns and leaves the rules half applied.
    So the file rules are written out (saveWorkspace) when the marker is
    missing, which turns a plain folder into a real project.

    Args:
        path: Project root directory path
    """
    project_path = str(Path(path))
    is_new = not (Path(path) / 'workspace.mel').is_file()

    # Record what we are leaving, so the switch can be walked back
    current = get_current_project()
    if current and Path(current).as_posix().rstrip('/') != Path(project_path).as_posix():
        _push_project_history(current)

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

    # Ensure directories exist before the workspace points at them
    make_project_dir(project_path)

    # Set project using MEL (required for some internal Maya operations).
    # Forward slashes: MEL reads a backslash as an escape character.
    mel.eval(f'setProject "{Path(project_path).as_posix()}"')

    # Configure workspace rules
    for rule, directory in workspace_rules.items():
        cmds.workspace(fileRule=(rule, directory))

    if is_new:
        cmds.workspace(saveWorkspace=True)
        logger.info(f"workspace.mel created in: {project_path}")

    logger.info(f"Project set to: {project_path}")


def get_project_from_scene(path: Union[str, Path, None] = None) -> Optional[Path]:
    """Work out which folder should be the project for a scene.

    Two rules, no guessing beyond them:

    - the scene sits in a ``scenes`` folder  -> its parent is the project
      (the standard Maya layout, the project already exists around it).
    - anything else -> the scene's own folder is the project, and the
      project structure gets created inside it.

    Args:
        path: Scene file. Defaults to the current scene.

    Returns:
        Path to the project root, or None when the scene was never saved.
    """
    scene = str(path) if path else get_scene_name()
    if not scene or scene == "untitled":
        logger.warning("Scene has never been saved, no project can be derived")
        return None

    scene_dir = Path(scene).parent
    if scene_dir.name.lower() == 'scenes':
        return scene_dir.parent
    return scene_dir


def set_project_from_scene(path: Union[str, Path, None] = None) -> Optional[Path]:
    """Set the Maya project from the scene location.

    Resolution is get_project_from_scene(); the project structure and its
    workspace.mel are created when missing, so this is safe on a scene
    saved in a plain folder.

    Args:
        path: Scene file. Defaults to the current scene.

    Returns:
        Path to the project that was set, or None when the scene was never
        saved (nothing is changed in that case).
    """
    project_path = get_project_from_scene(path)
    if not project_path:
        return None

    set_project(project_path)
    return project_path


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
