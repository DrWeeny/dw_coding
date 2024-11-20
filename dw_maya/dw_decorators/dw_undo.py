import maya.cmds as cmds
from functools import wraps
from typing import Callable, Any


def singleUndoChunk(func: Callable) -> Callable:
    """
    Group operations into a single Maya undo chunk.

    Ensures all operations can be undone in a single step.

    Example:
        @singleUndoChunk
        def create_complex_setup():
            cmds.polySphere()
            cmds.polyCube()
            # All created objects undo in one step
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            # start an undo chunk
            cmds.undoInfo(openChunk=True)
            return func(*args, **kwargs)
        finally:
            # after calling the func, end the undo chunk and undo
            cmds.undoInfo(closeChunk=True)

    return wrapper


def repeatable(func: Callable) -> Callable:
    """
    Make Maya commands repeatable with 'G' key.

    Source: http://blog.3dkris.com/2011/08/python-in-maya-how-to-make-commands.html

    Example:
        @repeatable
        def create_sphere(radius=1):
            return cmds.polySphere(r=radius)[0]

        # Can now press 'G' to repeat with same args
    """

    @wraps(func)
    def decoratorCode(*args, **kwargs):
        # Generate the argument string for the repeatable command
        arg_list = [repr(arg) for arg in args]
        kwarg_list = [f'{key}={repr(value)}' for key, value in kwargs.items()]
        argString = ', '.join(arg_list + kwarg_list)

        # Construct the command string for repeatLast
        commandToRepeat = f'python("{__name__}.{func.__name__}({argString})")'

        # Execute the original function
        functionReturn = func(*args, **kwargs)

        try:
            # Register the repeatable command in Maya's repeatLast
            cmds.repeatLast(ac=commandToRepeat, acl=func.__name__)
        except Exception as e:
            print(f"Warning: Could not make {func.__name__} repeatable: {e}")

        return functionReturn

    return decoratorCode