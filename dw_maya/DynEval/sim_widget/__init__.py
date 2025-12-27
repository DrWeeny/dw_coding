"""
DynEval Simulation Widgets

All widgets use DynEvalWidget base class for automatic DataHub integration.

Usage:
    from dw_maya.DynEval.sim_widget import (
        DynEvalWidget,
        CacheTreeWidget,
        MapTreeWidget,
        CommentEditor,
        VertexMapEditor,
    )
"""

# Base class - use this for new widgets
from .wgt_base import (
    DynEvalWidget,
    DynEvalMainWindow,
    DynEvalDockWidget,
    DynEvalDialog,
    HubMixin,
    HubPublisher,
    publishes,
    on_hub_change,
)

# Widgets
from .wgt_cache_tree import CacheTreeWidget, CacheInfo, CacheType
from .wgt_maps_tree import MapTreeWidget, MapInfo, MapType
from .wgt_commentary import CommentEditor
from .wgt_paint_map import VertexMapEditor, EditorConfig

__all__ = [
    # Base
    'DynEvalWidget',
    'DynEvalMainWindow', 
    'DynEvalDockWidget',
    'DynEvalDialog',
    'HubMixin',
    'HubPublisher',
    'publishes',
    'on_hub_change',
    # Widgets
    'CacheTreeWidget',
    'CacheInfo',
    'CacheType',
    'MapTreeWidget',
    'MapInfo',
    'MapType',
    'CommentEditor',
    'VertexMapEditor',
    'EditorConfig',
]