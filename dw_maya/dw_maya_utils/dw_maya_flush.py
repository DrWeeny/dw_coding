from maya import cmds

def wait_idle():
    """
    I never had success with this command, but it is used in Mash commands
    Returns:

    """
    cmds.flushIdleQueue()