"""NClothMap — WeightMap implementation for nCloth / nRigid per-vertex maps.

Bridges Maya nucleus simulation nodes (nCloth, nRigid) with the
:class:`~dw_maya.dw_paint.protocol.WeightMap` ABC so the UI and weight
operations remain completely backend-agnostic.

The active map is selected via :meth:`use_map`.  When the node has only
one map the auto-resolution in the base class handles it silently.

Classes:
    NClothMap: WeightMap for all named per-vertex maps on a nucleus node.

Example::

    from dw_maya.dw_nucleus_utils.dw_ncloth_class import NClothMap

    m = NClothMap('nClothShape1', 'pSphere1')
    m.available_maps()          # ['thickness', 'stretchMap', …]
    m.use_map('thickness')
    weights = m.get_weights()
    m.set_weights([0.5] * m.vtx_count)

    # Chainable
    m.use_map('stretchMap').get_weights()

Author: DrWeeny
"""

from __future__ import annotations

from maya import cmds
from typing import List, Optional

from maya import cmds

from dw_maya.dw_paint.protocol import WeightSource, WeightList
from dw_logger import get_logger

logger = get_logger()

# Map type integer → human label
_MAP_TYPE_NAMES = {
    0: 'None (disabled)',
    1: 'PerVertex',
    2: 'Texture',
}


class NClothMap(WeightSource):
    """All per-vertex maps on a single nCloth or nRigid node.

    Unlike the old single-map ``NClothMap``, this class wraps the *node*
    and lets the caller pick the active map via :meth:`use_map`.

    The map_type for the active map is auto-promoted from 0 (None) to
    1 (PerVertex) on the first :meth:`set_weights` call so values actually
    take effect.

    Args:
        nucleus_node: nCloth or nRigid shape node name.
        mesh_name:    Transform of the mesh driven by *nucleus_node*.
        map_name:     Optional initial map to activate (passed to
                      :meth:`use_map`).  When omitted the base class
                      auto-resolves if only one map exists.

    Example::

        m = NClothMap('nClothShape1', 'pSphere1')
        m.available_maps()
        # ['thickness', 'stretchMap', 'bendResistance', 'shearResistance', …]

        m.use_map('thickness').get_weights()
        m.use_map('stretchMap').set_weights([1.0] * m.vtx_count)
    """

    def __init__(self,
                 nucleus_node: str,
                 mesh_name: str,
                 map_name: Optional[str] = None) -> None:
        if not cmds.objExists(nucleus_node):
            raise ValueError(f"Nucleus node '{nucleus_node}' does not exist")
        node_type = cmds.nodeType(nucleus_node)
        if node_type not in ('nCloth', 'nRigid'):
            raise ValueError(
                f"'{nucleus_node}' is type '{node_type}', "
                f"expected nCloth or nRigid"
            )
        super().__init__(nucleus_node, mesh_name)
        if map_name is not None:
            self.use_map(map_name)

    # ------------------------------------------------------------------
    # WeightMap identity
    # ------------------------------------------------------------------

    @property
    def vtx_count(self) -> int:
        try:
            return cmds.polyEvaluate(self._mesh_name, vertex=True)
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # WeightMap — available_maps / _resolve_attr
    # ------------------------------------------------------------------

    def available_maps(self) -> List[str]:
        """All per-vertex map *base names* available on the nucleus node.

        Discovers maps by querying for ``*MapType`` attributes and stripping
        the ``MapType`` suffix, so new maps added by Maya or plugins are
        automatically included.

        Returns:
            e.g. ``['thickness', 'stretchMap', 'bendResistance', …]``
        """
        all_attrs = cmds.listAttr(self._node_name) or []
        maps = []
        for attr in all_attrs:
            if attr.endswith('MapType'):
                base = attr[: -len('MapType')]
                # Verify the corresponding PerVertex attribute also exists
                pv_attr = f'{base}PerVertex'
                if cmds.attributeQuery(pv_attr, node=self._node_name, exists=True):
                    maps.append(base)
        return maps

    def _resolve_attr(self, map_name: str) -> str:
        """Return the ``*PerVertex`` attribute path for *map_name*."""
        return f'{self._node_name}.{map_name}PerVertex'

    # ------------------------------------------------------------------
    # Map type helpers
    # ------------------------------------------------------------------

    def map_type(self, map_name: Optional[str] = None) -> int:
        """Current map type for *map_name* (default: active map).

        Returns:
            0 = None/disabled, 1 = PerVertex, 2 = Texture
        """
        target = map_name or self._require_map()
        attr_name = f'{target}MapType'
        if not cmds.attributeQuery(attr_name, node=self._node_name, exists=True):
            raise RuntimeError(
                f"MapType attribute not found for map '{target}' "
                f"on '{self._node_name}'"
            )
        return cmds.getAttr(f'{self._node_name}.{attr_name}')

    def set_map_type(self, value: int, map_name: Optional[str] = None) -> None:
        """Set the map type for *map_name* (default: active map).

        Args:
            value:    0 = disable, 1 = PerVertex, 2 = Texture.
            map_name: Map to target; defaults to the currently active map.
        """
        target = map_name or self._require_map()
        cmds.setAttr(f'{self._node_name}.{target}MapType', value)

    # ------------------------------------------------------------------
    # get_weights / set_weights — override to handle sparse fill and
    # auto-promote map type on write
    # ------------------------------------------------------------------

    def get_weights(self) -> WeightList:
        """Read per-vertex values for the active map.

        Maya's ``getAttr`` prunes zero-weight vertices from the stored array.
        Missing indices are filled with ``0.0`` so the returned list is always
        :attr:`vtx_count` long.
        """
        per_vtx_attr = self._resolve_attr(self._require_map())
        if not cmds.attributeQuery(
                per_vtx_attr.split('.')[-1], node=self._node_name, exists=True
        ):
            raise RuntimeError(
                f"PerVertex attribute '{per_vtx_attr}' not found "
                f"on '{self._node_name}'"
            )
        raw = cmds.getAttr(per_vtx_attr) or []
        n = self.vtx_count
        if len(raw) == n:
            return list(raw)
        weights = [0.0] * n
        for i, v in enumerate(raw):
            if i < n:
                weights[i] = float(v)
        return weights

    def set_weights(self, weights: WeightList) -> None:
        """Write per-vertex values for the active map.

        Auto-promotes map type from ``None`` (0) to ``PerVertex`` (1) when
        needed so the values actually take effect in the simulation.

        Args:
            weights: Full-length per-vertex weight list.

        Raises:
            ValueError: If length does not match :attr:`vtx_count`.
        """
        n = self.vtx_count
        if len(weights) != n:
            raise ValueError(
                f"Weight count {len(weights)} != vertex count {n}"
            )
        active = self._require_map()
        if self.map_type(active) == 0:
            logger.debug(
                f"Auto-promoting '{active}' on '{self._node_name}' "
                f"from MapType=None to MapType=PerVertex"
            )
            self.set_map_type(1, active)
        cmds.setAttr(
            self._resolve_attr(active),
            weights, type='doubleArray'
        )

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def get_artisan_name(self) ->str:
        return "artAttrNClothContext"

    def paint(self) -> None:
        """Open Maya's artisan paint tool for the currently active map."""
        from dw_maya.dw_nucleus_utils import artisan_nucx_update
        active = self._require_map()
        # Promote map type so artisan has something to paint
        if self.map_type(active) == 0:
            logger.debug(
                f"Promoting '{active}' to MapType=PerVertex before painting"
            )
            self.set_map_type(1, active)
        artisan_nucx_update(self._node_name, active, True)

    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        mt_label = ''
        try:
            mt = self.map_type()
            mt_label = _MAP_TYPE_NAMES.get(mt, str(mt))
        except Exception:
            pass
        return (
            f"<NClothMap node='{self._node_name}' "
            f"mesh='{self._mesh_name}' "
            f"map={self._current_map!r} "
            f"map_type='{mt_label}' "
            f"vtx={self.vtx_count}>"
        )

