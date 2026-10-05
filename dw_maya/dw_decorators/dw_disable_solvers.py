from functools import wraps
import maya.cmds as cmds


def tmp_disable_solver(func):
    """
    Temporarily disable all nucleus solvers while the wrapped function is executed.

    Args:
        func (function): The function to be wrapped.

    Returns:
        function: The wrapped function with solver disabled during execution.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Each nucleus's own state, so the restore puts back what was there:
        # a solver the user had switched off stays off afterwards. Nucleus
        # nodes created by func are not in this dict and are left as made.
        original_states = {}
        try:
            nucleus_list = cmds.ls(type='nucleus')
            if not nucleus_list:
                raise RuntimeError("No nucleus nodes found to disable.")

            for n in nucleus_list:
                original_states[n] = cmds.getAttr(n + '.nodeState')
                cmds.setAttr(n + '.nodeState', 1)

            return func(*args, **kwargs)

        finally:
            for n, state in original_states.items():
                if not cmds.objExists(n):
                    continue
                try:
                    cmds.setAttr(n + '.nodeState', state)
                except Exception as restore_err:
                    cmds.warning(f"Failed to restore solver for nucleus {n}: {restore_err}")

    return wrapper