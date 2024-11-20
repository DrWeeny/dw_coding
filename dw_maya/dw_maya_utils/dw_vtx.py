from typing import List, Optional
from maya import cmds, mel
from dw_maya.dw_decorators import acceptString

@acceptString('curves')
def change_curve_pivot(curves: Optional[List[str]] = None,
                       index: int = 0):
    """
    Change the scale and rotate pivots of the given curves to the specified CV (control vertex) position.

    Args:
        curves (list of str, optional): A list of curve names whose pivots should be changed.
        index (int): The CV index to use as the pivot position.

    Raises:
        ValueError: If no curves are provided or if the CV index cannot be found.
    """
    if curves is None:
        raise ValueError("No curves provided. Please provide a list of curve names.")

    for c in curves:
        try:
            # Try to get the world space position of the control vertex at the specified index
            coord = cmds.pointPosition(f"{c}.cv[{index}]")
        except Exception as e:
            # Handle intermediate objects
            sh = cmds.listRelatives(c, ni=True, f=True) or cmds.listRelatives(c, f=True)

            if sh:
                cmds.setAttr(f"{sh}.intermediateObject", 0)
                coord = cmds.pointPosition(f"{c}.cv[{index}]")
                cmds.setAttr(f"{sh}.intermediateObject", 1)
            else:
                raise e
        if coord:
            cmds.xform(c, scalePivot=coord, ws=True)
            cmds.xform(c, rotatePivot=coord, ws=True)


def get_common_roots(sel: List[str]) -> List[str]:
    """
    Get the common hierarchy root nodes from the selected objects.

    Args:
        sel (list of str): A list of selected objects.

    Returns:
        list of str: A list of the common root nodes, with full paths.

    Example:
        get_common_roots(['pCube1|pCubeShape1', 'pSphere1|pSphereShape1'])
        ['/pCube1', '/pSphere1']
    """
    # Get the full paths of the selected objects
    test = cmds.ls(sel, long=True)
    # Extract the root node (the first node after '|')
    roots = list(set([i.split('|')[1] for i in test]))
    return cmds.ls(roots, long=True)