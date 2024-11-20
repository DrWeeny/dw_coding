from maya import cmds

def instanceObjects(sel=[]):
    """
    Create instances of selected objects instead of full duplicates.

    Args:
        sel (list): List of objects to instance.

    Returns:
        list: List of created instances.
    """
    if not sel:
        sel = cmds.ls(sl=True)

    instances = []
    for obj in sel:
        instance = cmds.instance(obj)
        instances.append(instance[0])

    return instances