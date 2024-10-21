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
        try:
            # Disable all nucleus solvers
            nucleus_list = cmds.ls(type='nucleus')
            if not nucleus_list:
                raise RuntimeError("No nucleus nodes found to disable.")

            for n in nucleus_list:
                cmds.setAttr(n + '.nodeState', 1)

            result = func(*args, **kwargs)
            return result

        except Exception as e:
            raise e

        finally:
            # Re-enable all nucleus solvers
            nucleus_list = cmds.ls(type='nucleus')
            for n in nucleus_list:
                try:
                    cmds.setAttr(n + '.nodeState', 0)
                except Exception as restore_err:
                    cmds.warning(f"Failed to restore solver for nucleus {n}: {restore_err}")

    return wrapper