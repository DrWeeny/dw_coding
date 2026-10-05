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
        # Only the call that actually turned the viewport off turns it back
        # on. A nested call finds it already unmanaged and leaves it alone,
        # so the outer call's remaining work stays viewport-free.
        was_managed = bool(mel.eval("paneLayout -q -manage $gMainPane"))
        try:
            if was_managed:
                mel.eval("paneLayout -e -manage false $gMainPane")

            # Execute the wrapped function
            return func(*args, **kwargs)

        except Exception as e:
            # Optionally log the error here if needed
            print(f"Error during execution of {func.__name__}: {e}")
            raise  # Re-raise the original error

        finally:
            if was_managed:
                mel.eval("paneLayout -e -manage true $gMainPane")

    return wrapper