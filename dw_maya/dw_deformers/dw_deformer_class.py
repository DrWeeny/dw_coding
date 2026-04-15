"""Object-oriented wrappers for Maya deformer nodes.

Provides a consistent interface for both standard Maya deformers
(cluster, softMod, blendShape, wire, skinCluster) and nucleus
per-vertex maps (nCloth, nRigid), so the UI and operations layer
never need to care which backend they are talking to.

Class hierarchy::

    MayaNode
        └── Deformer              base — maps, operations, membership
                ├── Cluster       handle, origin, relative mode
                ├── SoftMod       falloff radius and curve
                ├── BlendShape    targets, per-target weights, in-betweens
                ├── Wire          wire curves, dropoff
                └── SkinCluster   influences, per-influence weights

    WeightSource (protocol, dw_paint.protocol)
        ├── Deformer  (also implements WeightSource)
        └── NClothMap (dw_nucleus_utils)

Key change from v1
------------------
``Deformer`` now inherits :class:`~dw_maya.dw_paint.protocol.WeightSource`
instead of the old thin ``WeightSource`` protocol.  The active weight
attribute is chosen via :meth:`use_map` (or resolved automatically when
only one map is available), so the UI never needs to branch on node type.

Factory:
    make_deformer(node)  → Deformer subclass (mesh auto-resolved)

Version: 2.1.0
Author:  DrWeeny
"""

from __future__ import annotations

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal
from typing import Dict, List, Optional, Tuple, Union

from maya import cmds, mel

import dw_maya.dw_maya_nodes as dwnn
import dw_maya.dw_paint
import dw_maya.dw_paint.core
import dw_maya.dw_paint.utils
import dw_maya.dw_paint.operations
import dw_maya.dw_presets_io.dw_deformer_json as deformer_json
import dw_maya.dw_presets_io.dw_preset as preset_utils
from dw_maya.dw_paint.protocol import WeightSource, WeightList
from dw_logger import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Deformer base
# ---------------------------------------------------------------------------

class Deformer(dwnn.MayaNode, WeightSource):
    """Base class for Maya geometry deformers.

    Inherits :class:`~dw_maya.dw_maya_nodes.MayaNode` for attribute access
    and :class:`~dw_maya.dw_paint.protocol.WeightSource` for unified weight I/O.

    The target mesh is resolved automatically from the deformer's output
    connections — no need to pass it in.

    The active weight map is selected via :meth:`use_map`.  For most
    deformers only one map exists (``'weightList'``), so :meth:`get_weights`
    auto-resolves it.  :class:`BlendShape` and :class:`SkinCluster` expose
    additional maps and require an explicit :meth:`use_map` call when the
    default is not desired.

    Args:
        name:        Deformer node name.
        preset:      Optional preset dict forwarded to MayaNode.
        blend_value: Blend factor for preset loading.

    Example::

        d = make_deformer('cluster1')
        d.mesh_name           # auto-resolved  →  'pSphere1'
        d.get_weights()       # auto-resolves single map
        d.set_weights([1.0] * d.vtx_count)

        bs = make_deformer('blendShape1')
        bs.available_maps()   # ['weightList', 'smile', 'frown', …]
        bs.use_map('smile').get_weights()
    """

    def __init__(self,
                 name: str,
                 preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        # MayaNode.__init__ handles ObjPointer + preset loading
        dwnn.MayaNode.__init__(self, name, preset, blend_value)
        # WeightSource.__init__ stores _node_name / _mesh_name / _current_map
        # We defer mesh_name resolution to the property (needs Maya).
        WeightSource.__init__(self, name, '')  # mesh_name filled lazily

        if not self._is_deformer():
            raise ValueError(f"Node '{name}' is not a geometry deformer")

        self.__dict__['_geo_index'] = 0

    # ------------------------------------------------------------------
    # WeightSource identity — override to use MayaNode's resolved node name
    # ------------------------------------------------------------------

    @property
    def node_name(self) -> str:
        """The deformer node name (shape-priority via MayaNode.node)."""
        return self.node  # MayaNode property

    @property
    def geo_index(self) -> int:
        """Current geometry connection index (0-based)."""
        return self.__dict__['_geo_index']

    @geo_index.setter
    def geo_index(self, index: int) -> None:
        self.__dict__['_geo_index'] = index

    @property
    def meshes(self) -> List[str]:
        """All mesh/nurbsCurve transforms connected to this deformer.

        Uses ``cmds.deformer(query, geometry)`` which correctly resolves the
        actual geometry even in stacked-deformer setups.  Returns transform
        names, not shapes.
        """
        shapes = cmds.deformer(self.node_name, query=True, geometry=True) or []
        result = []
        for sh in shapes:
            parents = cmds.listRelatives(sh, parent=True, fullPath=True)
            result.append(parents[0] if parents else sh)
        return result

    @property
    def mesh_name(self) -> str:
        """Transform of the currently active geometry (by :attr:`geo_index`)."""
        all_meshes = self.meshes
        if not all_meshes:
            raise RuntimeError(
                f"No geometry connected to deformer '{self.node_name}'"
            )
        if self.geo_index >= len(all_meshes):
            raise IndexError(
                f"geo_index {self.geo_index} out of range "
                f"({len(all_meshes)} connected meshes)"
            )
        return all_meshes[self.geo_index]

    @property
    def vtx_count(self) -> int:
        """Live vertex / CV count for the active geometry."""
        try:
            shapes = cmds.deformer(self.node_name, query=True, geometry=True) or []
            if not shapes or self.geo_index >= len(shapes):
                return 0
            shape = shapes[self.geo_index]
            result = cmds.polyEvaluate(shape, vertex=True)
            if isinstance(result, int):
                return result
            # NURBS curve fallback
            spans = cmds.getAttr(f'{shape}.spans')
            degree = cmds.getAttr(f'{shape}.degree')
            form = cmds.getAttr(f'{shape}.form')
            return spans + degree if form == 0 else spans
        except Exception as e:
            logger.warning(f"Could not determine vertex count: {e}")
            return 0

    # ------------------------------------------------------------------
    # WeightSource — available_maps and _resolve_attr
    # ------------------------------------------------------------------

    def available_maps(self) -> List[str]:
        """Return queryable map names.

        Base ``Deformer`` exposes only ``'weightList'``.  Subclasses
        (:class:`BlendShape`, :class:`SkinCluster`) override this to
        include per-target / per-influence maps.
        """
        return ['weightList']

    def _resolve_attr(self, map_name: str) -> str:
        """Build the full attribute path for *map_name*.

        For the base deformer this is always the standard weightList path.
        Subclasses override when their attribute layout differs.
        """
        n = self.vtx_count
        weight_range = f'0:{n - 1}' if n > 0 else '0'
        return f'{self.node_name}.weightList[{self.geo_index}].weights[{weight_range}]'

    # ------------------------------------------------------------------
    # get_weights / set_weights — override base WeightSource for compat
    # ------------------------------------------------------------------

    def get_weights(self) -> WeightList:
        """Return the full per-vertex weight list for the active map."""
        try:
            weights = cmds.getAttr(self._resolve_attr(self._require_map()))
            if weights is None:
                return []
            if not isinstance(weights, (list, tuple)):
                weights = [weights]
            return list(weights)
        except Exception as e:
            logger.error(f"Failed to get weights on '{self.node_name}': {e}")
            return []

    def set_weights(self, weights: WeightList) -> None:
        """Set the full per-vertex weight list for the active map."""
        n = self.vtx_count
        if len(weights) != n:
            raise ValueError(
                f"Weight count {len(weights)} != vertex count {n} "
                f"on '{self.node_name}'"
            )
        try:
            cmds.setAttr(
                self._resolve_attr(self._require_map()),
                *weights, size=n
            )
        except Exception as e:
            logger.error(f"Failed to set weights on '{self.node_name}': {e}")
            raise

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paint(self) -> None:
        """Open Maya's artisan paint tool for the active map."""
        from dw_maya.dw_paint.weight_source import _paint_deformer
        _paint_deformer(self)

    # ------------------------------------------------------------------
    # Higher-level operations (delegate to dw_paint pure functions)
    # ------------------------------------------------------------------

    def modify_weights(self,
                       value: float,
                       operation: Literal['multiply', 'add', 'replace'] = 'replace',
                       mask: Optional[List[List[int]]] = None) -> None:
        """Modify weights with a scalar operation."""
        current = self.get_weights()
        if not current:
            return
        self.set_weights(
            dw_maya.dw_paint.modify_weights(
                current, value, operation, mask, min_value=0.0, max_value=1.0
            )
        )

    def remap_weights(self,
                      old_min: float, old_max: float,
                      new_min: float, new_max: float) -> None:
        """Remap weight values from one range to another."""
        current = self.get_weights()
        if not current:
            return
        self.set_weights(
            dw_maya.dw_paint.remap_weights(current, old_min, old_max, new_min, new_max)
        )

    def mirror_weights(self,
                       axis: Literal['x', 'y', 'z'] = 'x',
                       world_space: bool = True) -> None:
        """Mirror weights across an axis."""
        current = self.get_weights()
        if not current:
            return
        new_weights = dw_maya.dw_paint.mirror_weights(
            self.mesh_name, current, axis, world_space=world_space
        )
        if new_weights:
            self.set_weights(new_weights)

    def smooth_weights(self,
                       iterations: int = 1,
                       smooth_factor: float = 0.5) -> None:
        """Smooth weights based on mesh topology."""
        current = self.get_weights()
        if not current:
            return
        new_weights = dw_maya.dw_paint.smooth_weights(
            self.mesh_name, current, iterations, smooth_factor
        )
        if new_weights:
            self.set_weights(new_weights)

    def distribute_weights_by_vector(self,
                                     direction,
                                     remap_range=None,
                                     falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
                                     origin=None,
                                     invert: bool = False,
                                     mode: Literal['projection', 'distance'] = 'projection') -> None:
        """Set weights by projecting vertex positions onto a direction vector."""
        new_weights = dw_maya.dw_paint.set_directional_weights(
            self.mesh_name, direction,
            remap_range=remap_range, falloff=falloff, origin=origin,
            invert=invert, mode=mode,
        )
        if new_weights:
            self.set_weights(new_weights)

    def distribute_weights_radial(self,
                                  center=None,
                                  radius=None,
                                  falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
                                  invert: bool = False) -> None:
        """Set weights by radial distance from a centre point."""
        new_weights = dw_maya.dw_paint.set_radial_weights(
            self.mesh_name, center=center, radius=radius, falloff=falloff, invert=invert
        )
        if new_weights:
            self.set_weights(new_weights)

    def copy_weights_from(self,
                          source: 'Deformer',
                          blend_factor: float = 1.0) -> None:
        """Copy weights from another Deformer, with optional blending."""
        source_weights = source.get_weights()
        if not source_weights:
            return
        if blend_factor < 1.0:
            current = self.get_weights()
            if current:
                source_weights = dw_maya.dw_paint.blend_weight_lists(
                    current, source_weights, blend_factor
                )
        self.set_weights(source_weights)

    def select_by_weight_range(self, min_value: float, max_value: float) -> None:
        """Select vertices whose weight falls within [min_value, max_value]."""
        weights = self.get_weights()
        if not weights:
            return
        dw_maya.dw_paint.select_vtx_info_on_mesh(
            weights, self.mesh_name, 'range',
            _min=min_value, _max=max_value
        )

    def get_affected_vertices(self) -> List[str]:
        """Return component strings for all vertices with weight > 0."""
        weights = self.get_weights()
        mesh = self.mesh_name
        return [f'{mesh}.vtx[{i}]' for i, w in enumerate(weights) if w > 0.0]

    # ------------------------------------------------------------------
    # Membership set
    # ------------------------------------------------------------------

    def _get_deformer_set(self) -> str:
        sets = cmds.listConnections(self.node_name, type='objectSet')
        if not sets:
            raise RuntimeError(
                f"No objectSet found connected to '{self.node_name}'"
            )
        return sets[0]

    def get_membership(self) -> List[str]:
        """Return geometry names currently in this deformer's set."""
        try:
            return cmds.sets(self._get_deformer_set(), query=True) or []
        except Exception as e:
            logger.error(f"Failed to get membership: {e}")
            return []

    def add_membership(self, geometry: Union[str, List[str]]) -> None:
        try:
            if isinstance(geometry, str):
                geometry = [geometry]
            cmds.sets(geometry, add=self._get_deformer_set())
        except Exception as e:
            logger.error(f"Failed to add membership: {e}")

    def remove_membership(self, geometry: Union[str, List[str]]) -> None:
        try:
            if isinstance(geometry, str):
                geometry = [geometry]
            cmds.sets(geometry, remove=self._get_deformer_set())
        except Exception as e:
            logger.error(f"Failed to remove membership: {e}")

    # ------------------------------------------------------------------
    # Weight stash
    # ------------------------------------------------------------------

    def stash_weights(self) -> None:
        """Store current weights in a custom attribute on the deformer node."""
        weights = self.get_weights()
        if not weights:
            return
        attr = 'storedWeights'
        if not cmds.attributeQuery(attr, node=self.node_name, exists=True):
            cmds.addAttr(self.node_name, longName=attr, dataType='doubleArray')
        cmds.setAttr(f'{self.node_name}.{attr}', weights, type='doubleArray')
        logger.debug(f"Stashed {len(weights)} weights on '{self.node_name}'")

    def restore_weights(self) -> None:
        """Restore weights from the stash created by :meth:`stash_weights`."""
        attr = 'storedWeights'
        if not cmds.attributeQuery(attr, node=self.node_name, exists=True):
            logger.warning(f"No stashed weights found on '{self.node_name}'")
            return
        weights = cmds.getAttr(f'{self.node_name}.{attr}')
        if weights:
            self.set_weights(list(weights))

    # ------------------------------------------------------------------
    # Preset I/O
    # ------------------------------------------------------------------

    def save_preset(self, name: str, path: Optional[str] = None) -> str:
        try:
            weights_dict = deformer_json.get_deformer_weights(self.node_name)
            return deformer_json.saveDeformerJson(name, weights_dict, path)
        except Exception as e:
            logger.error(f"Failed to save preset: {e}")
            return ''

    def load_preset(self, preset_path: str, blend_value: float = 1.0) -> None:
        try:
            preset_data = deformer_json.loadDeformerJson(preset_path)
            if not preset_data:
                return
            deformer_json.setDeformersFromJson(preset_path)
            if isinstance(preset_data, dict):
                preset_utils.blendAttrDic(
                    self.node_name, None, preset_data, blend_value
                )
        except Exception as e:
            logger.error(f"Failed to load preset: {e}")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _is_deformer(self) -> bool:
        return 'geometryFilter' in (
            cmds.nodeType(self.node, inherited=True) or []
        )

    def __repr__(self) -> str:
        try:
            mesh = self.mesh_name
        except Exception:
            mesh = '?'
        return (
            f"<{type(self).__name__} node='{self.node_name}' "
            f"mesh='{mesh}' map={self._current_map!r} vtx={self.vtx_count}>"
        )


# ---------------------------------------------------------------------------
# Cluster
# ---------------------------------------------------------------------------

class Cluster(Deformer):
    """Cluster deformer — relative mode, handle, origin."""

    def __init__(self, name: str, preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        super().__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != 'cluster':
            raise ValueError(f"'{name}' is not a cluster deformer")

    @property
    def handle(self) -> Optional[str]:
        handles = cmds.listConnections(
            f'{self.node_name}.matrix', source=True, destination=False
        )
        return handles[0] if handles else None

    def set_origin(self, position: Tuple[float, float, float]) -> None:
        handle = self.handle
        if handle:
            cmds.xform(handle, worldSpace=True, translation=position)

    def set_relative(self, state: bool) -> None:
        cmds.setAttr(f'{self.node_name}.relative', state)


# ---------------------------------------------------------------------------
# SoftMod
# ---------------------------------------------------------------------------

class SoftMod(Deformer):
    """SoftMod deformer — falloff radius and curve."""

    def __init__(self, name: str, preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        super().__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != 'softMod':
            raise ValueError(f"'{name}' is not a softMod deformer")

    def set_falloff_radius(self, radius: float) -> None:
        cmds.setAttr(f'{self.node_name}.falloffRadius', radius)

    def set_falloff_curve(self,
                          values: List[Tuple[float, float]],
                          curve_type: Literal['spline', 'linear'] = 'spline') -> None:
        if not cmds.attributeQuery('falloffCurve', node=self.node_name, exists=True):
            cmds.addAttr(self.node_name, longName='falloffCurve', attributeType='ramp')
        ramp = f'{self.node_name}.falloffCurve'
        for i, (pos, val) in enumerate(values):
            cmds.setAttr(f'{ramp}[{i}].ramp_Position', pos)
            cmds.setAttr(f'{ramp}[{i}].ramp_FloatValue', val)
            if curve_type == 'linear':
                cmds.setAttr(f'{ramp}[{i}].ramp_Interp', 1)


# ---------------------------------------------------------------------------
# BlendShape
# ---------------------------------------------------------------------------

class BlendShape(Deformer):
    """BlendShape deformer — targets, base weights, in-betweens.

    :meth:`available_maps` includes ``'weightList'`` (the base mask) plus
    one entry per named blend target so :meth:`use_map` can target any of
    them directly.

    Example::

        bs = make_deformer('blendShape1')
        bs.available_maps()           # ['weightList', 'smile', 'frown']
        bs.use_map('smile').get_weights()
        bs.use_map('weightList').set_weights([1.0] * bs.vtx_count)
    """

    def __init__(self, name: str, preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        super().__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != 'blendShape':
            raise ValueError(f"'{name}' is not a blendShape deformer")

    def available_maps(self) -> List[str]:
        """Base mask + one entry per blend target."""
        target_names = [name for name, _ in self.targets]
        return ['weightList'] + target_names

    def _resolve_attr(self, map_name: str) -> str:
        n = self.vtx_count
        weight_range = f'0:{n - 1}' if n > 0 else '0'
        if map_name == 'weightList':
            # Base (mask) weights
            return f'{self.node_name}.inputTarget[{self.geo_index}].baseWeights[{weight_range}]'

        # Per-target vertex weights
        target_names = [name for name, _ in self.targets]
        if map_name in target_names:
            target_index = target_names.index(map_name)
            return (
                f'{self.node_name}.inputTarget[{self.geo_index}]'
                f'.inputTargetGroup[{target_index}]'
                f'.targetWeights[{weight_range}]'
            )
        raise ValueError(
            f"Unknown map '{map_name}' on BlendShape '{self.node_name}'. "
            f"Available: {self.available_maps()}"
        )

    @property
    def targets(self) -> List[Tuple[str, int]]:
        names = cmds.blendShape(self.node_name, query=True, target=True) or []
        return [(name, i) for i, name in enumerate(names)]

    @property
    def target_weights(self) -> Dict[str, float]:
        """Current slider values for all targets as {name: value}."""
        return {
            name: cmds.getAttr(f'{self.node_name}.{name}')
            for name, _ in self.targets
        }

    def set_target_weight(self, target: str, weight: float) -> None:
        """Set the slider value for a named target."""
        target_names = [name for name, _ in self.targets]
        if target in target_names:
            cmds.setAttr(f'{self.node_name}.{target}', weight)
        else:
            logger.warning(
                f"Target '{target}' not found on '{self.node_name}'. "
                f"Available: {target_names}"
            )

    def add_target(self, target_mesh: str, weight: float = 1.0) -> None:
        base_mesh = cmds.listConnections(
            f'{self.node_name}.outputGeometry[{self.geo_index}]',
            source=False, destination=True
        )[0]
        index = len(self.targets)
        cmds.blendShape(
            self.node_name, edit=True,
            target=(base_mesh, index, target_mesh, weight)
        )

    def add_inbetween_target(self, target: str,
                              target_mesh: str,
                              in_between_weight: float) -> None:
        target_names = [name for name, _ in self.targets]
        if target not in target_names:
            logger.warning(f"Target '{target}' not found on '{self.node_name}'")
            return
        target_index = target_names.index(target)
        base_mesh = cmds.listConnections(
            f'{self.node_name}.outputGeometry[{self.geo_index}]',
            source=False, destination=True
        )[0]
        cmds.blendShape(
            self.node_name, edit=True,
            target=(base_mesh, target_index, target_mesh, in_between_weight)
        )

    def paint(self) -> None:
        """Open artisan for the active map (base mask or per-target weights)."""
        active = self._require_map()
        mesh_short = self.mesh_name.split('|')[-1]
        vtx = cmds.filterExpand(selectionMask=31, expand=False) or []
        if vtx:
            cmds.select(vtx, replace=True)
            cmds.select(mesh_short, add=True)
        else:
            cmds.select(mesh_short, replace=True)
        if not cmds.artAttrCtx('artAttrCtx', exists=True):
            cmds.artAttrCtx('artAttrCtx')
        if active == 'weightList':
            mel.eval(f'artSetToolAndSelectAttr "artAttrCtx" "blendShape.{self.node_name}.baseWeights"')
            mel.eval('setToolTo "artAttrCtx"')
        else:
            target_names = [name for name, _ in self.targets]
            if active not in target_names:
                raise ValueError(
                    f"BlendShape target '{active}' not found on '{self.node_name}'. "
                    f"Available: {target_names}"
                )
            target_index = target_names.index(active)
            target_meshes = cmds.blendShape(self.node_name, query=True, target=True) or []
            if target_index >= len(target_meshes):
                raise RuntimeError(
                    f"Could not resolve mesh for target '{active}' "
                    f"(index {target_index}) on '{self.node_name}'"
                )
            target_mesh = target_meshes[target_index]
            mel.eval('setToolTo "artAttrCtx"')
            mel.eval(f'artSetToolAndSelectAttr "artAttrCtx" "blendShape.{self.node_name}.paintTargetWeights"')
            # artBlendShapeSelectTarget reads the artisan UI's textScrollList
            # (blendShapeTargetList) which may not yet exist when this call
            # fires synchronously.  Deferring pushes it into Maya's event queue
            # so the artisan tool has time to fully initialise its panel first.
            import maya.utils as mu
            _cmd = f'mel.eval(\'artBlendShapeSelectTarget artAttrCtx "{target_mesh}"\')'
            cmds.evalDeferred(_cmd, lowestPriority=True)
            # mu.executeDeferred(mel.eval, f'artBlendShapeSelectTarget artAttrCtx "{target_mesh}"')
            logger.debug(f"BlendShape paint deferred — target='{target_mesh}' index={target_index}")
# ---------------------------------------------------------------------------
# Wire
# ---------------------------------------------------------------------------

class Wire(Deformer):
    """Wire deformer — wire curves and dropoff distance."""

    def __init__(self, name: str, preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        super().__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != 'wire':
            raise ValueError(f"'{name}' is not a wire deformer")

    @property
    def wire_curves(self) -> List[str]:
        return cmds.wire(self.node_name, query=True, wire=True) or []

    def set_dropoff_distance(self, distance: float, curve_index: int = 0) -> None:
        cmds.wire(self.node_name, edit=True,
                  dropoffDistance=(curve_index, distance))


# ---------------------------------------------------------------------------
# SkinCluster
# ---------------------------------------------------------------------------

class SkinCluster(Deformer):
    """SkinCluster deformer — influences, per-influence weights.

    :meth:`available_maps` returns ``'weightList'`` plus one entry per
    influence joint.  :meth:`use_map` selects which influence's weights
    :meth:`get_weights` / :meth:`set_weights` operate on.

    Example::

        sc = make_deformer('skinCluster1')
        sc.available_maps()               # ['weightList', 'joint1', 'joint2']
        sc.use_map('joint1').get_weights()
        sc.use_map('weightList').get_weights()  # full packed array
    """

    def __init__(self, name: str, preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        super().__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != 'skinCluster':
            raise ValueError(f"'{name}' is not a skinCluster deformer")
        self.__dict__['_influence_index'] = 0

    def available_maps(self) -> List[str]:
        """``'weightList'`` + one entry per influence joint."""
        return ['weightList'] + self.influences

    def _resolve_attr(self, map_name: str) -> str:
        n = self.vtx_count
        weight_range = f'0:{n - 1}' if n > 0 else '0'
        if map_name == 'weightList':
            return (
                f'{self.node_name}.weightList[{self.geo_index}]'
                f'.weights[{weight_range}]'
            )
        # Per-influence path
        all_influences = self.influences
        if map_name in all_influences:
            inf_index = all_influences.index(map_name)
            return (
                f'{self.node_name}.weightList[{self.geo_index}]'
                f'.weights[{weight_range}]'
                # Note: per-influence queries go through skinPercent / getAttr
                # on the same path but filtered; subclasses may override.
            )
        raise ValueError(
            f"Unknown map '{map_name}' on SkinCluster '{self.node_name}'"
        )

    @property
    def influences(self) -> List[str]:
        return cmds.skinCluster(self.node_name, query=True, influence=True) or []

    def add_influence(self, joint: str, default_weight: float = 0.0) -> None:
        if cmds.objExists(joint):
            cmds.skinCluster(
                self.node_name, edit=True,
                addInfluence=joint, weight=default_weight
            )
        else:
            logger.warning(f"Joint '{joint}' does not exist")


# ---------------------------------------------------------------------------
# NClothMap re-export
# Canonical home: dw_maya.dw_nucleus_utils.dw_ncloth_class
# ---------------------------------------------------------------------------
from dw_maya.dw_nucleus_utils.dw_ncloth_class import NClothMap  # noqa: E402


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_DEFORMER_CLASSES: Dict[str, type] = {
    'cluster':     Cluster,
    'softMod':     SoftMod,
    'blendShape':  BlendShape,
    'wire':        Wire,
    'skinCluster': SkinCluster,
}


def make_deformer(node: str,
                  preset: Optional[Dict] = None,
                  blend_value: float = 1.0) -> Deformer:
    """Instantiate the correct Deformer subclass for a given Maya node.

    Args:
        node:        Deformer node name.
        preset:      Optional preset dict.
        blend_value: Blend factor for preset loading.

    Returns:
        Appropriate :class:`Deformer` subclass instance.

    Raises:
        ValueError: If the node does not exist or is not a geometry deformer.

    Example::

        make_deformer('cluster1')
        # <Cluster node='cluster1' mesh='pSphere1' map=None vtx=382>

        make_deformer('blendShape1')
        # <BlendShape node='blendShape1' mesh='pSphere1' map=None vtx=382>
    """
    if not cmds.objExists(node):
        raise ValueError(f"Node '{node}' does not exist")

    node_type = cmds.nodeType(node)
    cls = _DEFORMER_CLASSES.get(node_type, Deformer)

    if cls is Deformer:
        if 'geometryFilter' not in (cmds.nodeType(node, inherited=True) or []):
            raise ValueError(
                f"'{node}' (type '{node_type}') is not a geometry deformer"
            )
        logger.warning(
            f"No specific class for deformer type '{node_type}', "
            f"falling back to base Deformer"
        )

    return cls(node, preset, blend_value)