"""
DataHub Keys for DynEval Widget Communication

This module defines all the publish/subscribe keys used by DynEval widgets
to communicate through the DataHubPub singleton.

Usage:
    from dw_utils.data_hub import DataHubPub
    from dw_maya.DynEval.hub_keys import HubKeys

    # Publishing (from TreeView)
    hub = DataHubPub.Get()
    hub.publish(HubKeys.SELECTED_ITEM, item, overwrite=True)

    # Subscribing (from MapTreeWidget)
    hub.subscribe(HubKeys.SELECTED_ITEM, self._on_selection_changed)
"""

from dataclasses import dataclass
from typing import Optional, List, Any
from enum import Enum, auto


class HubKeys:
    """
    Central registry of all DataHub keys.

    Naming convention: CATEGORY_SPECIFIC_NAME
    """

    # =========================================================================
    # SELECTION CONTEXT
    # =========================================================================
    # Primary selection from the simulation tree
    SELECTED_ITEM = "dyneval.selection.item"              # BaseSimulationItem or None
    SELECTED_ITEMS = "dyneval.selection.items"            # List[BaseSimulationItem]
    SELECTED_MESH = "dyneval.selection.mesh"              # str - mesh transform path
    SELECTED_NODE = "dyneval.selection.node"              # str - simulation node name

    # =========================================================================
    # SOLVER CONTEXT
    # =========================================================================
    SOLVER_CURRENT = "dyneval.solver.current"             # str - nucleus/zSolver node
    SOLVER_TYPE = "dyneval.solver.type"                   # str - 'nucleus', 'ziva', 'deformer'
    SOLVER_NAMESPACE = "dyneval.solver.namespace"         # str - namespace

    # =========================================================================
    # CACHE CONTEXT
    # =========================================================================
    CACHE_SELECTED = "dyneval.cache.selected"             # CacheInfo or None
    CACHE_ATTACHED = "dyneval.cache.attached"             # bool
    CACHE_DIRECTORY = "dyneval.cache.directory"           # str - cache directory path
    CACHE_VERSION = "dyneval.cache.version"               # int - current version

    # =========================================================================
    # MAP/PAINT CONTEXT
    # =========================================================================
    MAP_SELECTED = "dyneval.map.selected"                 # MapInfo or None
    MAP_LIST = "dyneval.map.list"                         # List[MapInfo]
    MAP_WEIGHTS = "dyneval.map.weights"                   # List[float] - current weights
    MAP_TYPE = "dyneval.map.type"                         # MapType enum

    PAINT_ACTIVE = "dyneval.paint.active"                 # bool - paint tool active
    PAINT_CONTEXT = "dyneval.paint.context"               # tuple(node, attr, mesh)
    PAINT_VALUE = "dyneval.paint.value"                   # float - current paint value

    # =========================================================================
    # PRESET CONTEXT
    # =========================================================================
    PRESET_SELECTED = "dyneval.preset.selected"           # PresetInfo or None
    PRESET_LOADED = "dyneval.preset.loaded"               # PresetInfo - currently applied

    # =========================================================================
    # UI STATE
    # =========================================================================
    UI_MODE = "dyneval.ui.mode"                           # str - 'cache', 'maps', 'presets'
    UI_LOADING = "dyneval.ui.loading"                     # bool - loading state
    UI_STATUS = "dyneval.ui.status"                       # str - status message

    # =========================================================================
    # COMMENTS
    # =========================================================================
    COMMENT_CURRENT = "dyneval.comment.current"           # str - current comment text
    COMMENT_TARGET = "dyneval.comment.target"             # str - what the comment is for


class UIMode(Enum):
    """UI display modes for the middle panel"""
    CACHE = auto()
    MAPS = auto()
    PRESETS = auto()


@dataclass
class SelectionContext:
    """
    Data container for current selection state.
    Published as a single object to reduce multiple updates.
    """
    item: Any = None                    # BaseSimulationItem
    items: List[Any] = None             # Multiple selection
    mesh: Optional[str] = None          # Mesh transform
    node: Optional[str] = None          # Simulation node
    solver: Optional[str] = None        # Solver node
    namespace: Optional[str] = None     # Namespace

    def __post_init__(self):
        if self.items is None:
            self.items = []

    @classmethod
    def from_item(cls, item) -> 'SelectionContext':
        """Create context from a BaseSimulationItem"""
        if item is None:
            return cls()

        return cls(
            item=item,
            items=[item],
            mesh=getattr(item, 'mesh_transform', None),
            node=getattr(item, 'node', None),
            solver=getattr(item, 'solver_name', None) or item.data(item.CUSTOM_ROLES.get('SOLVER', 0)),
            namespace=getattr(item, 'namespace', None)
        )

    @classmethod
    def from_items(cls, items: list) -> 'SelectionContext':
        """Create context from multiple items"""
        if not items:
            return cls()

        primary = items[0]
        return cls(
            item=primary,
            items=items,
            mesh=getattr(primary, 'mesh_transform', None),
            node=getattr(primary, 'node', None),
            solver=getattr(primary, 'solver_name', None),
            namespace=getattr(primary, 'namespace', None)
        )


@dataclass
class PaintContext:
    """
    Data container for paint tool state.
    """
    node: Optional[str] = None          # nCloth/nRigid node
    attribute: Optional[str] = None     # Map attribute name
    mesh: Optional[str] = None          # Mesh being painted
    is_active: bool = False             # Paint tool is active
    solver: Optional[str] = None        # Associated solver

    @property
    def full_attribute(self) -> Optional[str]:
        """Get full attribute path (node.attribute)"""
        if self.node and self.attribute:
            return f"{self.node}.{self.attribute}"
        return None
