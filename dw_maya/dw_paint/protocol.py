"""WeightSource protocol and WeightList type alias.

Defines the minimal interface every paintable Maya node must satisfy so the
operations layer (dw_paint) and the UI remain completely backend-agnostic.

This module has ZERO Maya dependencies — safe to import in any context,
including unit tests running outside Maya.

Classes:
    WeightSource: Minimal protocol for paintable, weight-bearing nodes.

Types:
    WeightList: Type alias for List[float].

Example:
    from dw_maya.dw_paint.protocol import WeightSource, WeightList

    class MyNode(WeightSource):
        @property
        def node_name(self) -> str: ...
        @property
        def mesh_name(self) -> str: ...
        @property
        def vtx_count(self) -> int: ...
        def get_weights(self) -> WeightList: ...
        def set_weights(self, weights: WeightList) -> None: ...
        def paint(self) -> None: ...

Author: DrWeeny
"""

from __future__ import annotations

from typing import List


WeightList = List[float]


class WeightSource:
    """Minimal protocol every paintable node must satisfy.

    Both Deformer subclasses (dw_deformers) and NClothMap (dw_nucleus_utils)
    implement this interface so the UI and dw_paint operations never branch
    on backend type.

    All properties and methods raise NotImplementedError — implementors must
    override them all.
    """

    @property
    def node_name(self) -> str:
        """Unique Maya node name."""
        raise NotImplementedError

    @property
    def mesh_name(self) -> str:
        """Transform name of the affected mesh."""
        raise NotImplementedError

    @property
    def vtx_count(self) -> int:
        """Vertex count of the affected mesh."""
        raise NotImplementedError

    def get_weights(self) -> WeightList:
        """Read current per-vertex weights as a full-length list."""
        raise NotImplementedError

    def set_weights(self, weights: WeightList) -> None:
        """Write per-vertex weights (must equal vtx_count in length)."""
        raise NotImplementedError

    def paint(self) -> None:
        """Open Maya's artisan paint tool for this source."""
        raise NotImplementedError

