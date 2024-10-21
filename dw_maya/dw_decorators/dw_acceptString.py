import maya.mel as mel
from functools import wraps
import inspect

def acceptString(*list_args):
    """
    Convert given parameter to a list if it is provided as a string.

    Args:
        *list_args (str): The argument names to convert to a list if they are strings.

    Returns:
        A decorator that ensures the specified arguments are converted to a list.
    """

    def convert_params_to_list(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Get the signature of the function and bind the arguments
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            # Iterate over the specified list_args
            for list_arg in list_args:
                if list_arg in bound_args.arguments:
                    value = bound_args.arguments[list_arg]

                    # Convert the argument to a list if it's a string
                    if isinstance(value, str):
                        bound_args.arguments[list_arg] = [value]

            # Call the original function with modified arguments
            return func(*bound_args.args, **bound_args.kwargs)

        return wrapper

    return convert_params_to_list