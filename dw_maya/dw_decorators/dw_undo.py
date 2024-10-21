import maya.cmds as cmds
from functools import wraps


def singleUndoChunk(func):
    """
    Decorator to group the wrapped function's operations into a single Maya Undo chunk.
    This ensures that all operations performed by the function can be undone in a single
    step in Maya's undo queue.

    Args:
        func (function): The function to wrap.

    Returns:
        function: The wrapped function that executes within a single undo chunk.
    """
    @wraps(func)
    def _undofunc(*args, **kwargs):
        try:
            # start an undo chunk
            cmds.undoInfo(openChunk=True)
            return func(*args, **kwargs)
        finally:
            # after calling the func, end the undo chunk and undo
            cmds.undoInfo(closeChunk=True)

    return _undofunc
    # return lambda *args, **kwargs: executeDeferred(wrap, *args, **kwargs)


def repeatable(function):
    """
    A decorator that makes commands repeatable in Maya.

    Source: http://blog.3dkris.com/2011/08/python-in-maya-how-to-make-commands.html

    Args:
        function (function): The function to wrap and make repeatable.

    Returns:
        function: The wrapped function.
    """

    @wraps(function)
    def decoratorCode(*args, **kwargs):
        # Generate the argument string for the repeatable command
        arg_list = [repr(arg) for arg in args]
        kwarg_list = [f'{key}={repr(value)}' for key, value in kwargs.items()]
        argString = ', '.join(arg_list + kwarg_list)

        # Construct the command string for repeatLast
        commandToRepeat = f'python("{__name__}.{function.__name__}({argString})")'

        # Execute the original function
        functionReturn = function(*args, **kwargs)

        try:
            # Register the repeatable command in Maya's repeatLast
            cmds.repeatLast(ac=commandToRepeat, acl=function.__name__)
        except Exception as e:
            print(f"Error registering command to repeatLast: {e}")

        return functionReturn

    return decoratorCode