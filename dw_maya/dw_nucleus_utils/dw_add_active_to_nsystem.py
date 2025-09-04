import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
from .dw_nx_mel import *


def add_active_to_nsystem(active: str, nucleus: str) -> int:
    """
    Connects an nObject (active) to a nucleus system in Maya by wiring necessary attributes.

    Args:
        active (str): Name of the nObject (e.g., nCloth, nParticle).
        nucleus (str): Name of the nucleus system to connect the object to.

    Returns:
        int: Index used for connecting the active object to the nucleus system.

    Notes:
        - This function connects the `currentState` and `startState` of the active object
          to the `inputActive` and `inputActiveStart` attributes of the nucleus.
        - It also connects the `outputObjects` of the nucleus to the `nextState` of the active object.
    """

    attr = f"{nucleus}.inputActive[{{}}]"
    start_attr = f"{nucleus}.inputActiveStart[{{}}]"

    # Get the next available index for multi-attribute connections
    nindex = get_next_free_multi_index(f"{nucleus}.inputActive")

    try:
        # Connect the current state and start state of the active object
        cmds.connectAttr(f"{active}.currentState", attr.format(nindex), force=True)
        cmds.connectAttr(f"{active}.startState", start_attr.format(nindex), force=True)
    except Exception as e:
        cmds.warning(f"Failed to connect currentState/startState for {active}: {e}")

    # Connect the output of the nucleus to the active object's next state
    n_output_attr = f"{nucleus}.outputObjects[{nindex}]"
    try:
        cmds.connectAttr(n_output_attr, f"{active}.nextState", force=True)
    except Exception as e:
        cmds.warning(f"Failed to connect outputObjects to nextState for {active}: {e}")

    # Set the active state to true
    try:
        cmds.setAttr(f"{active}.active", 1)
    except Exception as e:
        cmds.warning(f"Failed to set {active} to active: {e}")

    return nindex

