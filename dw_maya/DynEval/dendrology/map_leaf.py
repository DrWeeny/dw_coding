"""
MapInfo — data container for a paintable vertex map on a nucleus node.

Published on the hub as MAP_SELECTED / PAINT_REQUESTED (see hub_keys.py).
Built by MapListPanel from a tree item's get_maps() names; consumed by
DynEvalUI._on_paint_requested, which hands it to Slimfast.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class MapInfo:
    """One paintable vertex map on an nCloth / nRigid node.

    Attributes:
        node: Shape node carrying the map attributes (e.g. nCloth shape).
        name: Map base name, e.g. "inputAttract" (attribute minus "MapType").
        mesh: Simulated mesh transform to paint on, None if unresolved.
    """
    node: str
    name: str
    mesh: Optional[str] = None