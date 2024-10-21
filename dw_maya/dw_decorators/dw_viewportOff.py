import maya.mel as mel
from functools import wraps

def viewportOff(func):
    """
    Decorator to turn off Maya's viewport while the decorated function runs.
    If the function raises an error, the error is propagated, but the viewport
    will always be turned back on at the end, ensuring Maya's display is not left off.

    Args:
        func (function): The function to wrap.

    Returns:
        function: The wrapped function with the viewport off during its execution.
    """

    @wraps(func)
    def wrap(*args, **kwargs):
        try:
            # Turn the viewport (gMainPane) off
            mel.eval("paneLayout -e -manage false $gMainPane")

            # Execute the wrapped function
            return func(*args, **kwargs)

        except Exception as e:
            # Optionally log the error here if needed
            print(f"Error during execution of {func.__name__}: {e}")
            raise  # Re-raise the original error

        finally:
            # Turn the viewport back on
            mel.eval("paneLayout -e -manage true $gMainPane")

    return wrap