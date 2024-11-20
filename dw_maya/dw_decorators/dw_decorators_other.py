import maya.cmds as cmds
from functools import wraps
from typing import Callable, Any, Optional


def _maya_version() -> int:
    """Get current Maya version."""
    from dw_maya.dw_maya_utils import maya_version
    return maya_version()


def evalManagerState(mode: str = 'off') -> None:
    """
    Switch Maya's evaluation manager state with undo support.

    Source: Based on Red9 Studio Pack's implementation
    Uses evalManager_switch plugin to record switching in undo stack.

    Args:
        mode: Evaluation mode ('off', 'parallel', etc.)
    """
    if _maya_version() >= 2016:
        # Try to load the plugin if needed
        if not cmds.pluginInfo('evalManager_switch', q=True, loaded=True):
            try:
                cmds.loadPlugin('evalManager_switch')
            except Exception as e:
                cmds.warning(f'Plugin Failed to load: evalManager_switch ({e})')

        # Switch evaluation mode
        try:
            cmds.evalManager_switch(mode=mode)  # Plugin version for undo support
        except:
            print('Using native evalManager (no undo support)')
            cmds.evaluationManager(mode=mode)

        print(f'EvalManager - switching state: {mode}')
    else:
        print("evalManager skipped (Maya version < 2016)")


def evalManager_DG(func: Callable) -> Callable:
    """
    Decorator to temporarily switch to DG evaluation mode.

    Source: Based on Red9 Studio Pack's implementation
    Ensures function runs in DG mode for better timeline evaluation performance.
    Restores original mode after execution.

    Example:
        @evalManager_DG
        def process_animation():
            # Runs in DG mode for faster timeline evaluation
            pass
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if _maya_version() < 2016:
            return func(*args, **kwargs)

        # Store original mode
        try:
            orig_mode = cmds.evaluationManager(q=True, mode=True)[0]
        except:
            orig_mode = None

        try:
            # Switch to DG if needed
            if orig_mode == 'parallel':
                evalManagerState(mode='off')

            return func(*args, **kwargs)

        except Exception as e:
            print(f'Error in {func.__name__}: {e}')
            raise

        finally:
            # Restore original mode
            if orig_mode and orig_mode != 'off':
                evalManagerState(mode=orig_mode)

    return wrapper