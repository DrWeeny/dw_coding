import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import maya.cmds as cmds
from functools import wraps

# THIS IS FEW DECORATORS
def _maya_version():
    from dw_maya.dw_maya_utils import maya_version
    return maya_version()


def evalManagerState(mode='off'):
    '''
    wrapper function for the evalManager so that it's switching is recorded in
    the undo stack via the Red9.evalManager_switch plugin
    '''

    if _maya_version() >= 2016:
        if not cmds.pluginInfo('evalManager_switch', q=True, loaded=True):
            try:
                cmds.loadPlugin('evalManager_switch')
            except:
                cmds.warning('Plugin Failed to load : evalManager_switch')
        try:
            # via the plug-in to register the switch to the undoStack
            cmds.evalManager_switch(mode=mode)
        except:
            print('evalManager_switch plugin not found, running native Maya evalManager command')
            cmds.evaluationManager(mode=mode)  # run the default maya call instead
        print('EvalManager - switching state : %s' % mode)
    else:
        print("evalManager skipped as you're in an older version of Maya")

def evalManager_DG(func):
    '''
    DECORATOR : simple decorator to call the evalManager_switch plugin
    and run the enclosed function in DG eval mode NOT parallel.
    .. note::
        Parallel EM mode is slow at evaluating time, DG is up to 3 times faster!
        The plugin call is registered back in the undoStack, cmds.evalmanager call is not
    '''
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            evalmode = None
            if _maya_version() >= 2016:
                evalmode = cmds.evaluationManager(mode=True, q=True)[0]
                if evalmode == 'parallel':
                    evalManagerState(mode='off')
            res = func(*args, **kwargs)
        except:
            print('Failed on evalManager_DG decorator')
        finally:
            if evalmode:
                evalManagerState(mode=evalmode)
        return res
    return wrapper