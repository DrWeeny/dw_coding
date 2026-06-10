"""
systems/__init__.py

Importing this package registers all available simulation backends.
Add a new line here when a new system module is created.

Import order matters if systems share node types (first registered wins).
Nucleus goes first as the primary/default backend.
"""

from dw_maya.DynEval.systems import nucleus_system  # noqa: F401  registers nucleus on import

# future backends — uncomment when ready:
# from . import ziva_system      # noqa: F401
# from . import qualoth_system   # noqa: F401
# from . import carbon_system    # noqa: F401
