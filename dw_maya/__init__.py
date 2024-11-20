import importlib
import sys
from typing import List


def reload_dw_toolkit():
    """
    Reload all DW toolkit modules in the correct order.
    Handles package hierarchy and dependencies.
    """
    # Get all loaded DW modules
    dw_modules = sorted([
        name for name in sys.modules
        if name.startswith('dw_') and sys.modules[name]
    ], key=lambda x: len(x.split('.')))  # Sort by depth

    reloaded = set()

    def reload_module(module_name: str) -> None:
        """Recursively reload a module and its dependencies."""
        if module_name in reloaded:
            return

        # Reload dependencies first
        module = sys.modules.get(module_name)
        if module:
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if hasattr(attr, '__module__') and \
                        attr.__module__ and \
                        attr.__module__.startswith('dw_') and \
                        attr.__module__ != module_name:
                    reload_module(attr.__module__)

        # Reload the module
        print(f"Reloading {module_name}")
        importlib.reload(sys.modules[module_name])
        reloaded.add(module_name)

    # Reload all modules
    for module_name in dw_modules:
        reload_module(module_name)

    print(f"\nReloaded {len(reloaded)} modules")
    return list(reloaded)
