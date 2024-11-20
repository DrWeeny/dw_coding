"""
DW Maya Decorators Package

A collection of decorators for Maya operations, providing functionality for:
- Performance optimization (viewport, solver management)
- Undo management
- Animation and deformation safety checks
- Function timing and debugging
- Sound feedback
- Plugin management

Example:
    from dw_decorators import timeIt, singleUndoChunk, viewportOff

    @timeIt
    @singleUndoChunk
    @viewportOff
    def create_complex_setup():
        # Function executes with:
        # - Performance timing
        # - Single undo chunk
        # - Viewport disabled
        pass
"""

from pathlib import Path
from typing import List

# Version identifier
__version__ = "1.0.0"

# Module Exports - these will be available when using 'from dw_decorators import *'
__all__: List[str] = [
    # Performance decorators
    "timeIt",
    "viewportOff",
    "tmp_disable_solver",
    "evalManager_DG",

    # Undo management
    "singleUndoChunk",
    "repeatable",

    # Safety and validation
    "vtxAnimDetection",
    "acceptString",
    "load_plugin",

    # Utility decorators
    "returnNodeDiff",
    "printDate",
    "complete_sound",

    # Additional utilities
    "evalManagerState"
]

# Explicit imports for frequently used decorators
from .dw_acceptString import acceptString
from .dw_benchmark import timeIt, printDate
from .dw_complete_sound import complete_sound
from .dw_disable_solvers import tmp_disable_solver
from .dw_load_plugin import load_plugin
from .dw_returnNodeDiff import returnNodeDiff
from .dw_undo import singleUndoChunk, repeatable
from .dw_viewportOff import viewportOff
from .dw_decorators_other import evalManager_DG, evalManagerState
from .dw_vtxAnimDetection import vtxAnimDetection
from .dw_is_maya_node import is_maya_node

# Decorator categories for documentation and IDE support
performance_decorators = [timeIt, viewportOff, tmp_disable_solver, evalManager_DG]
undo_decorators = [singleUndoChunk, repeatable]
safety_decorators = [vtxAnimDetection, acceptString, load_plugin, is_maya_node]
utility_decorators = [returnNodeDiff, printDate, complete_sound]