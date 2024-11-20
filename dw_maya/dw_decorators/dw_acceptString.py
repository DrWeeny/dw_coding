from functools import wraps
import inspect

def acceptString(*list_args):
    """
    Decorator that converts string parameters to single-item lists.

    This decorator checks if specified parameters are strings and converts them
    to single-item lists. Useful for Maya functions that expect lists but are
    often called with single strings.

    Args:
        *param_names: Names of parameters to check and potentially convert

    Returns:
        Callable: Decorated function that handles string to list conversion

    Example:
        @acceptString('node_name', 'attribute')
        def process_nodes(node_name: str | list[str], attribute: str | list[str]) -> None:
            # node_name and attribute will always be lists
            pass

        # These calls are now equivalent:
        process_node("pSphere1")  # Converts to ["pSphere1"]
        process_node(["pSphere1", "pSphere2"])  # Left as is
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