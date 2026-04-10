"""NClothMap — WeightSource wrapper for nCloth / nRigid per-vertex maps.

Bridges Maya nucleus simulation nodes (nCloth, nRigid) with the dw_paint
WeightSource protocol so the UI and weight operations remain backend-agnostic.

Classes:
    NClothMap: WeightSource for a single named per-vertex map on a nucleus node.

Example:
    from dw_maya.dw_nucleus_utils.dw_ncloth_class import NClothMap

    m = NClothMap('nClothShape1', 'thickness', 'pSphere1')
    weights = m.get_weights()
    m.set_weights([0.5] * m.vtx_count)
    m.paint()

Author: DrWeeny
"""

from __future__ import annotations

from maya import cmds

from dw_maya.dw_paint.protocol import WeightSource, WeightList
from dw_logger import get_logger

logger = get_logger()


class NClothMap(WeightSource):
    """Per-vertex map on an nCloth or nRigid node.

    Wraps a single named map (e.g. 'thickness', 'bendResistance') and
    exposes the same get_weights / set_weights / paint interface as Deformer
    subclasses so the UI never needs to branch on backend type.

    The map_type attribute is auto-promoted from 0 (None) to 1 (Vertex)
    on the first :meth:`set_weights` call so values actually take effect.

    Args:
        nucleus_node: nCloth or nRigid shape node name.
        map_name:     Base map name without suffix
                      (e.g. 'thickness', not 'thicknessPerVertex').
        mesh_name:    Transform of the mesh driven by nucleus_node.

    Example:
        >>> m = NClothMap('nClothShape1', 'thickness', 'pSphere1')
        >>> m.get_weights()
        >>> m.set_weights([0.5] * m.vtx_count)
    """

    def __init__(self, nucleus_node: str, map_name: str, mesh_name: str):
        if not cmds.objExists(nucleus_node):
            raise ValueError(f"Nucleus node '{nucleus_node}' does not exist")
        node_type = cmds.nodeType(nucleus_node)
        if node_type not in ('nCloth', 'nRigid'):
            raise ValueError(
                f"'{nucleus_node}' is type '{node_type}', "
                f"expected nCloth or nRigid"
            )
        self._nucleus_node = nucleus_node
        self._map_name = map_name
        self._mesh_name = mesh_name

    # ------------------------------------------------------------------
    # WeightSource protocol — identity
    # ------------------------------------------------------------------

    @property
    def node_name(self) -> str:
        return self._nucleus_node

    @property
    def map_name(self) -> str:
        """Base map name (e.g. 'thickness', not 'thicknessPerVertex')."""
        return self._map_name

    @property
    def mesh_name(self) -> str:
        return self._mesh_name

    @property
    def vtx_count(self) -> int:
        try:
            return cmds.polyEvaluate(self._mesh_name, vertex=True)
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Map type
    # ------------------------------------------------------------------

    @property
    def map_type(self) -> int:
        """Current map type: 0=None, 1=Vertex, 2=Texture."""
        attr_name = f'{self._map_name}MapType'
        if not cmds.attributeQuery(attr_name, node=self._nucleus_node, exists=True):
            raise RuntimeError(
                f"MapType attribute not found for map '{self._map_name}'"
            )
        return cmds.getAttr(f'{self._nucleus_node}.{attr_name}')

    @map_type.setter
    def map_type(self, value: int) -> None:
        cmds.setAttr(f'{self._nucleus_node}.{self._map_name}MapType', value)

    # ------------------------------------------------------------------
    # WeightSource protocol — get / set
    # ------------------------------------------------------------------

    def get_weights(self) -> WeightList:
        """Read per-vertex values, returning a full-length list.

        Maya's getAttr prunes zero-weight vertices from the stored array.
        Missing indices are filled with 0.0 so the returned list is always
        aligned to vtx_count.
        """
        per_vtx_attr_name = f'{self._map_name}PerVertex'
        if not cmds.attributeQuery(
            per_vtx_attr_name, node=self._nucleus_node, exists=True
        ):
            raise RuntimeError(
                f"PerVertex attribute not found for map '{self._map_name}'"
            )
        raw = cmds.getAttr(
            f'{self._nucleus_node}.{per_vtx_attr_name}'
        ) or []
        n = self.vtx_count
        if len(raw) == n:
            return list(raw)
        weights = [0.0] * n
        for i, v in enumerate(raw):
            if i < n:
                weights[i] = v
        return weights

    def set_weights(self, weights: WeightList) -> None:
        """Write per-vertex values, auto-promoting map_type if needed.

        Args:
            weights: Full-length per-vertex weight list.

        Raises:
            ValueError: If length does not match vtx_count.
        """
        n = self.vtx_count
        if len(weights) != n:
            raise ValueError(
                f"Weight count {len(weights)} != vertex count {n}"
            )
        if self.map_type == 0:
            logger.debug(
                f"Auto-promoting '{self._map_name}' on "
                f"'{self._nucleus_node}' from MapType=None to MapType=Vertex"
            )
            self.map_type = 1
        cmds.setAttr(
            f'{self._nucleus_node}.{self._map_name}PerVertex',
            weights, type='doubleArray'
        )

    # ------------------------------------------------------------------
    # WeightSource protocol — paint
    # ------------------------------------------------------------------

    def paint(self) -> None:
        """Open Maya's artisan paint tool for this nucleus map."""
        from dw_maya.dw_nucleus_utils import artisan_nucx_update
        artisan_nucx_update(self._nucleus_node, self._map_name, True)

    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (f"<NClothMap node='{self._nucleus_node}' "
                f"map='{self._map_name}' mesh='{self._mesh_name}' "
                f"map_type={self.map_type}>")

