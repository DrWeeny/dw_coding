"""WeightSource ABC and WeightList type alias for dw_paint.

Defines the single abstract contract every paintable Maya node must satisfy.
Replaces the former thin ``WeightSource`` protocol with a concrete ABC that
handles all weight I/O through a *current map* selected via :meth:`use_map`.

Design rationale
----------------
Three kinds of paintable nodes exist in the pipeline:

1. **Standard deformers** (cluster, blendShape, skinCluster, …)
   One implicit map per geometry index: ``weightList[i].weights``.

2. **Nucleus nodes** (nCloth, nRigid)
   Several named per-vertex maps: ``thicknessPerVertex``,
   ``stretchMapPerVertex``, etc.

3. **Custom multi-map nodes** (future / undisclosed third case)
   Arbitrary named maps on a single node.

All three share exactly the same weight I/O need:
  - discover which maps are available  →  :meth:`available_maps`
  - activate one map                   →  :meth:`use_map`
  - read / write the active map        →  :meth:`get_weights` / :meth:`set_weights`
  - open artisan for it                →  :meth:`paint`

``WeightSource`` provides ``get_weights`` / ``set_weights`` in terms of two
abstract primitives — :meth:`available_maps` and :meth:`_resolve_attr` —
so subclasses stay minimal.

This module has **zero Maya dependencies** and is safe to import in any
context including unit tests running outside a Maya session.

Classes:
    WeightSource: Abstract base for all paintable, weight-bearing nodes.

Types:
    WeightList: ``List[float]`` — one value per mesh vertex.

Backward compatibility:
    ``WeightSource`` is kept as a pure alias so existing imports do not break::

        from dw_maya.dw_paint.protocol import WeightSource  # still works

Example::

    from dw_maya.dw_paint.protocol import WeightSource

    class MyNode(WeightSource):
        def available_maps(self):
            return ['densityMap', 'rigidnessMap']

        def _resolve_attr(self, map_name: str) -> str:
            return f'{self.node_name}.{map_name}PerVertex'

        @property
        def vtx_count(self) -> int:
            from maya import cmds
            return cmds.polyEvaluate(self.mesh_name, vertex=True)

        def paint(self) -> None:
            ...  # open artisan for current map

Author: DrWeeny
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------
WeightList = List[float]


class WeightSource(ABC):
    """Abstract base for any Maya node that exposes per-vertex weight maps.

    All weight I/O is mediated through a *current map* activated via
    :meth:`use_map`.  When the node exposes exactly one map, :meth:`get_weights`
    and :meth:`set_weights` auto-resolve it so callers never have to call
    :meth:`use_map` for the simple case.

    Subclasses must implement:
        - :attr:`node_name`       — the Maya node string
        - :attr:`mesh_name`       — transform of the affected mesh
        - :attr:`vtx_count`       — live vertex count
        - :meth:`available_maps`  — list of queryable map names
        - :meth:`_resolve_attr`   — full Maya attribute path for a map name
        - :meth:`paint`           — open artisan for the current map

    The default ``get_weights`` / ``set_weights`` implementations use
    :meth:`_resolve_attr` and handle Maya's sparse zero-weight pruning
    automatically.  Override them only when the attribute read/write
    requires special handling (e.g. ``skinCluster`` per-influence arrays).

    Args:
        node_name:  Maya node name this wrapper targets.
        mesh_name:  Transform name of the affected mesh.

    Example::

        node = MyWeightSource('cluster1', 'pSphere1')
        node.use_map('weightList')
        weights = node.get_weights()
        node.set_weights([w * 0.5 for w in weights])

        # Chainable
        node.use_map('stretchMap').get_weights()

        # Auto-resolve when only one map exists
        single_map_node.get_weights()   # no use_map() needed
    """

    def __init__(self, node_name: str, mesh_name: str) -> None:
        self._node_name: str = node_name
        self._mesh_name: str = mesh_name
        self._current_map: Optional[str] = None

    # ------------------------------------------------------------------
    # Identity — concrete, set at construction
    # ------------------------------------------------------------------

    @property
    def node_name(self) -> str:
        """Maya node name."""
        return self._node_name

    @property
    def mesh_name(self) -> str:
        """Transform name of the affected mesh."""
        return self._mesh_name

    # ------------------------------------------------------------------
    # Map selection
    # ------------------------------------------------------------------

    def use_map(self, map_name: str) -> 'WeightSource':
        """Activate a map for subsequent weight I/O.  Chainable.

        Args:
            map_name: One of the names returned by :meth:`available_maps`.

        Returns:
            ``self`` so calls can be chained::

                node.use_map('stretchMap').get_weights()

        Raises:
            ValueError: If ``map_name`` is not in :meth:`available_maps`.
        """
        available = self.available_maps()
        if map_name not in available:
            raise ValueError(
                f"'{map_name}' is not available on '{self._node_name}'. "
                f"Available: {available}"
            )
        self._current_map = map_name
        return self

    @property
    def current_map(self) -> Optional[str]:
        """The currently selected map name, or ``None`` if not yet set."""
        return self._current_map

    def _require_map(self) -> str:
        """Return the active map name, auto-resolving single-map nodes.

        Raises:
            RuntimeError: When multiple maps exist and none has been selected.
        """
        if self._current_map:
            return self._current_map

        available = self.available_maps()
        if len(available) == 1:
            return available[0]

        raise RuntimeError(
            f"Node '{self._node_name}' exposes {len(available)} maps — "
            f"call use_map() first.  Available: {available}"
        )

    # ------------------------------------------------------------------
    # Abstract interface — subclasses must implement these
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def vtx_count(self) -> int:
        """Live vertex / CV count for the affected mesh."""

    @abstractmethod
    def available_maps(self) -> List[str]:
        """Return all queryable map names for this node.

        Example return values:

        - Cluster:    ``['weightList']``
        - NClothMap:  ``['thickness', 'stretchMap', 'bendResistance', …]``
        - ThirdCase:  ``['densityMap', 'rigidnessMap']``
        """

    @abstractmethod
    def _resolve_attr(self, map_name: str) -> str:
        """Return the full Maya attribute path for *map_name*.

        The default ``get_weights`` / ``set_weights`` call this to build
        the ``cmds.getAttr`` / ``cmds.setAttr`` target.

        Args:
            map_name: A name from :meth:`available_maps`.

        Returns:
            Full attribute path, e.g.
            ``'cluster1.weightList[0].weights[0:381]'``
        """

    @abstractmethod
    def paint(self) -> None:
        """Open Maya's artisan paint tool for the currently active map."""

    # ------------------------------------------------------------------
    # Default get / set — override when Maya's attr format differs
    # ------------------------------------------------------------------

    def get_weights(self) -> WeightList:
        """Read per-vertex weights for the active map.

        Handles Maya's sparse storage: vertices with weight 0 may be absent
        from the stored array; missing indices are filled with ``0.0`` so the
        returned list is always ``vtx_count`` long.

        Returns:
            ``List[float]`` of length :attr:`vtx_count`.
        """
        from maya import cmds  # deferred — module is Maya-free at import time

        attr = self._resolve_attr(self._require_map())
        raw = cmds.getAttr(attr) or []
        if not isinstance(raw, (list, tuple)):
            raw = [raw]

        n = self.vtx_count
        if len(raw) == n:
            return list(raw)

        # Sparse fill
        weights = [0.0] * n
        for i, v in enumerate(raw):
            if i < n:
                weights[i] = float(v)
        return weights

    def set_weights(self, weights: WeightList) -> None:
        """Write per-vertex weights for the active map.

        Args:
            weights: One ``float`` per vertex — must equal :attr:`vtx_count`.

        Raises:
            ValueError: If ``len(weights) != vtx_count``.
        """
        from maya import cmds  # deferred import

        n = self.vtx_count
        if len(weights) != n:
            raise ValueError(
                f"Weight count {len(weights)} != vertex count {n} "
                f"on '{self._node_name}'"
            )
        attr = self._resolve_attr(self._require_map())
        cmds.setAttr(attr, weights, type='doubleArray')

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"<{type(self).__name__} node='{self._node_name}' "
            f"mesh='{self._mesh_name}' "
            f"map={self._current_map!r} "
            f"vtx={self.vtx_count}>"
        )

