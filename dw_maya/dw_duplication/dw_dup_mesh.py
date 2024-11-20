from dw_maya.dw_decorators import acceptString
import maya.cmds as cmds
from . import cleanDuplication
import dw_maya.dw_maya_utils as dwu

@acceptString('sel')
def dupMesh(sel=[], **kwargs):
    """
    Duplicates mesh objects, assigns them unique names, and cleans them up by removing history, layers, shaders, and extra attributes.

    :param sel: List of selected objects to duplicate. Defaults to current selection.
    :param kwargs: Optional keyword arguments such as 'forbiddenName' to avoid specific names during duplication.
    :return: List of duplicated and cleaned mesh objects.
    """
    pairingNames = {}

    # Use the current selection if no objects are provided
    if not sel:
        sel = cmds.ls(sl=1)

    # Generate unique names for the selected objects
    zipNames = dwu.unique_name(sel, **kwargs)

    # Create a dictionary pairing original names with the new unique names
    for x in range(len(zipNames)):
        pairingNames[zipNames[x][0]] = [zipNames[x][1]]

    # Duplicate the objects and rename them to the generated unique names
    dopple = cmds.duplicate(list(pairingNames.keys()), n='dw_tmp_name001', rc=True)
    for d, n in zip(dopple, pairingNames.values()):
        cmds.rename(d, n[0])

    # Reorder duplicates using the new names from the zipNames list
    dup = [i[1] for i in zipNames]

    # Clean up the duplicated objects (history, transformations, layers, shaders, extra attributes)
    cleanDuplication(dup, cTransformations=True, cLayer=True, cSet=True, cShader=False, cExtraAttribute=True)

    return dup
