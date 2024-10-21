import maya.cmds as cmds
from functools import wraps

def load_plugin(argument=str):
    """
    Decorator to ensure that a specific Maya plugin is loaded before executing the function.

    Args:
        argument (str): The name of the Maya plugin to check and load if necessary.

    Returns:
        function: The wrapped function that ensures the plugin is loaded.
    """

    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            # Check if the plugin is already loaded
            is_loaded = cmds.pluginInfo(argument, query=True, loaded=True)

            # If not loaded, try to load the plugin
            if not is_loaded:
                try:
                    cmds.loadPlugin(argument, quiet=True)
                    is_loaded = cmds.pluginInfo(argument, query=True, loaded=True)

                    # Provide feedback if the plugin failed to load
                    if not is_loaded:
                        raise RuntimeError(f"Failed to load plugin: {argument}")

                except RuntimeError as e:
                    print(f"Error loading plugin '{argument}': {e}")
                    cmds.error(f"Could not load required plugin: {argument}")
                    return None

            # If the plugin is loaded, proceed with the function
            return function(*args, **kwargs)

        return wrapper

    return decorator
