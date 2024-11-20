import maya.cmds as cmds
from functools import wraps
from typing import Callable, Any, Optional
from dw_logger import get_logger


def load_plugin(plugin_name: str) -> Callable:
    """
    Decorator to ensure a Maya plugin is loaded before function execution.

    Args:
        plugin_name: Name of the Maya plugin to load

    Returns:
        Decorated function that ensures plugin availability

    Example:
        @load_plugin('ziva')
        def create_tissue():
            # Plugin is guaranteed to be loaded here
            pass
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger = get_logger()
            # Check if plugin is loaded
            if not cmds.pluginInfo(plugin_name, query=True, loaded=True):
                try:
                    cmds.loadPlugin(plugin_name, quiet=True)
                    logger.info(f"Loaded plugin: {plugin_name}")

                    # Verify plugin loaded successfully
                    if not cmds.pluginInfo(plugin_name, query=True, loaded=True):
                        raise RuntimeError(f"Failed to load plugin: {plugin_name}")

                except Exception as e:
                    logger.error(f"Error loading plugin '{plugin_name}': {str(e)}")
                    raise RuntimeError(f"Could not load required plugin: {plugin_name}")

            return func(*args, **kwargs)

        return wrapper

    return decorator