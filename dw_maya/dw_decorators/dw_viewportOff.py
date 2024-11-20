import maya.mel as mel
from functools import wraps
from typing import Callable, Any


def viewportOff(func: Callable) -> Callable:
    """
    Decorator to temporarily disable Maya's viewport during function execution.
    Ensures viewport is re-enabled even if the function raises an error.

    Args:
        func: The function to wrap

    Example:
        @viewportOff
        def create_many_objects():
            # Viewport updates disabled here
            for i in range(1000):
                cmds.polySphere()
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
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

    return wrapper