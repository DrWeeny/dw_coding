"""
backends/__init__.py

Importing this package registers every available DynForge guide backend.
Add a line here when a new backend module is created.

Import order matters only if two backends ever claim the same type_name
(last registered wins). Chain joints is the first / default backend.
"""

from dw_maya.DynForge.backends import chain_joint_guide  # noqa: F401  registers chain_joint

# future backends - uncomment when ready:
# from dw_maya.DynForge.backends import nhair_guide       # noqa: F401
# from dw_maya.DynForge.backends import constraint_guide  # noqa: F401