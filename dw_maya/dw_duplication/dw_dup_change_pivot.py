from maya import cmds

def dupWithPivotAdjustment(sel=[], pivotType='boundingBoxCenter'):
    """
    Duplicate objects and adjust their pivot position.

    Args:
        sel (list): List of objects to duplicate.
        pivotType (str): Type of pivot adjustment ('boundingBoxCenter', 'origin', or custom position).

    Returns:
        list: List of duplicated objects with adjusted pivots.
    """
    if not sel:
        sel = cmds.ls(sl=True)

    duplicates = cmds.duplicate(sel, rr=True)

    for dup in duplicates:
        if pivotType == 'boundingBoxCenter':
            bbox = cmds.xform(dup, q=True, bb=True, ws=True)
            center = [(bbox[0] + bbox[3]) / 2, (bbox[1] + bbox[4]) / 2, (bbox[2] + bbox[5]) / 2]
            cmds.xform(dup, piv=center, ws=True)
        elif pivotType == 'origin':
            cmds.xform(dup, piv=[0, 0, 0], ws=True)
        # Add more custom pivot positioning options as needed

    return duplicates