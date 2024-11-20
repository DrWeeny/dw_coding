import maya.cmds as cmds, mel
import os
from dw_maya.dw_decorators import acceptString
from pathlib import Path
from . import dupMesh
import dw_maya.dw_doCreateGeometryCache as dcgc
import dw_maya.dw_maya_utils as dwu


def make_dir(path):
    """
    Create all the directories in the specified path if they do not exist.

    :param path: The directory path to create.
    :return: The path string.
    """
    if not os.path.exists(path):
        os.makedirs(path)
    return path


@acceptString('sel')
def dupAnim(sel=[]):
    """
    Duplicates the selected objects, bakes them, and creates a geometry cache for them.

    Args:
        sel: List of selected Maya objects (meshes or curves).

    Returns:
        msh_output: List of new baked mesh names.
    """
    # If no selection provided, take the current Maya selection
    if not sel:
        sel = cmds.ls(sl=True)

    restore_panels = []

    # Define temporary cache directory
    base_path = Path(cmds.workspace(q=True, rd=True))
    directory = str(base_path / cmds.workspace(fileRuleEntry='fileCache') / 'tmp_bake')
    # Ensure directory exists
    if not os.path.isdir(directory):
        make_dir(directory)

    # Retrieve names of existing files in the directory to avoid duplicates
    filesName = [f.split('.')[0] for f in os.listdir(directory) if f.endswith('.xml')]

    # Duplicate and clean the mesh with unique names
    duplicates = dupMesh(sel, forbiddenName=filesName)

    # Isolate view to improve performance
    evaluation = cmds.evaluationManager(q=True, mode=True)
    if 'off' not in evaluation:
        cmds.warning('You may want to switch to DG evaluation mode: cmds.evaluationManager(mode="off")')
    else:
        restore_panels = isolate_viewport_for_bake()

    # Create cache for the duplicated objects
    fileXml = dcgc.doCreateGeometryCache(sel, cacheDirectory=directory)

    # Use MEL to import the cache file
    objListMel = dwu.convert_list_to_mel_str(duplicates)
    # as_posix to have linux path style for MEL
    cmd_format = f'doImportCacheFile("{Path(fileXml[0]).as_posix()}", "xmlcache", {objListMel}, {{}});'
    print(cmd_format)
    mel.eval(cmd_format)

    # Restore the original viewport settings if changed
    if restore_panels:
        for panel in restore_panels:
            cmds.isolateSelect(panel, state=0)

    # Rename duplicated meshes with a 'bake_' prefix
    msh_output = []
    for obj in duplicates:
        if not obj.startswith('bake_'):
            new_name = cmds.rename(obj, 'bake_' + obj)
            msh_output.append(new_name)
        else:
            msh_output.append(obj)

    return msh_output


def isolate_viewport_for_bake():
    """
    Isolates the viewport for performance improvements during cache bake.

    Returns:
        restore_panels: List of model panels to restore later.
    """
    restore_panels = []
    modelPanels = [i for i in cmds.lsUI(p=True) if 'modelPanel' in i]
    for panel in modelPanels:
        if not cmds.isolateSelect(panel, q=True, state=True):
            cmds.isolateSelect(panel, state=True)
            restore_panels.append(panel)
    return restore_panels