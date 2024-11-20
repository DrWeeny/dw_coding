"""Package providing object-oriented wrappers for Maya nodes with Pythonic interfaces.

A comprehensive package providing object-oriented access to Maya nodes, attributes,
and connections. Implements a Pythonic interface similar to PyMel but with better
performance characteristics.

Classes:
    MayaNode: Main class for interacting with Maya nodes
    MAttr: Class for handling Maya attributes
    ObjPointer: Low-level Maya API object wrapper

Main Features:
    - Pythonic interface for Maya nodes and attributes
    - Dynamic attribute access and manipulation
    - Automatic node type detection and handling
    - Preset loading and saving support
    - Comprehensive attribute management
    - Connection handling

Version: 1.0.0

Author:
    DrWeeny
"""

# Import order matters here - import base classes first
from .obj_pointer import ObjPointer
from .attr import MAttr
from .maya_node import MayaNode

__all__ = ['ObjPointer', 'MAttr', 'MayaNode']