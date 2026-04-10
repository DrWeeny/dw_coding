"""Object-oriented wrappers for Maya deformer nodes.

Provides a consistent interface for both standard Maya deformers
(cluster, softMod, blendShape, wire, skinCluster) and nucleus
per-vertex maps (nCloth, nRigid), so the UI and operations layer
never need to care which backend they are talking to.

Class hierarchy:
    MayaNode
        └── Deformer              base — weights, operations, membership
                ├── Cluster       handle, origin, relative mode
                ├── SoftMod       falloff radius and curve
                ├── BlendShape    targets, per-target weights, in-betweens
                ├── Wire          wire curves, dropoff
                └── SkinCluster   influences, per-influence weights

    WeightSource (protocol)
        ├── Deformer  (also implements WeightSource)
        └── NClothMap bridges nucleus per-vertex maps

Factory:
    make_deformer(node)             -> Deformer subclass (mesh auto-resolved)
    resolve_weight_sources(mesh)    -> List[WeightSource] (deformers + nucleus)

Version: 2.0.0
Author:  DrWeeny
"""

from __future__ import annotations

# Correction de l'import de Literal pour compatibilité Python 3.7
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
import dw_maya.dw_nucleus_utils.dw_nucleus_paint
import dw_maya.dw_presets_io.dw_deformer_json as deformer_json
import dw_maya.dw_presets_io.dw_preset as preset_utils
from dw_logger import get_logger

logger = get_logger()

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------
WeightList = List[float]


# ---------------------------------------------------------------------------
# WeightSource protocol
# ---------------------------------------------------------------------------
class WeightSource:
    """Minimal protocol that every weight-bearing node must satisfy.

    Both Deformer subclasses and NClothMap implement this interface so
    the UI and operations (flood, mirror, smooth …) remain backend-agnostic.
    """

    @property
    def node_name(self) -> str:
        raise NotImplementedError

    @property
    def mesh_name(self) -> str:
        raise NotImplementedError

    @property
    def vtx_count(self) -> int:
        raise NotImplementedError

    def get_weights(self) -> WeightList:
        raise NotImplementedError

    def set_weights(self, weights: WeightList) -> None:
        raise NotImplementedError

    def paint(self) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Deformer base
# ---------------------------------------------------------------------------
class Deformer(dwnn.MayaNode, WeightSource):
    """Base class for Maya geometry deformers.

    Inherits MayaNode for attribute access and ObjPointer for API identity.
    The target mesh is resolved automatically from the deformer's output
    connections — no need to pass it in.

    Subclasses override :attr:`_weight_attr_template` and optionally
    :attr:`_weight_tokens` to customise the attribute path used for
    reading and writing weights.

    Args:
        name:        Deformer node name.
        preset:      Optional preset dict forwarded to MayaNode.
        blend_value: Blend factor for preset loading.

    Example:
        >>> d = make_deformer('cluster1')
        >>> d.mesh_name           # auto-resolved
        'pSphere1'
        >>> d.get_weights()
        [0.0, 0.5, 1.0, ...]
        >>> d.set_weights([1.0] * d.vtx_count)
    """

    def __init__(self,
                 name: str,
                 preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        super().__init__(name, preset, blend_value)

        if not self._is_deformer():
            raise ValueError(f"Node '{name}' is not a geometry deformer")

        # Settable so callers can target a specific mesh when multiple are
        # connected (multi-mesh deformer case).
        self.__dict__['_geo_index'] = 0

    # ------------------------------------------------------------------
    # WeightSource protocol — identity
    # ------------------------------------------------------------------

    @property
    def node_name(self) -> str:
        """The deformer node name (shape-priority via MayaNode.node)."""
        return self.node

    @property
    def geo_index(self) -> int:
        """Current geometry connection index (0-based)."""
        return self.__dict__['_geo_index']

    @geo_index.setter
    def geo_index(self, index: int) -> None:
        """Set the active geometry index for multi-mesh deformers."""
        self.__dict__['_geo_index'] = index

    @property
    def meshes(self) -> List[str]:
        """All mesh/nurbsCurve transforms connected to this deformer.

        Queries every outputGeometry slot so NURBS curves and multi-mesh
        setups are both handled.  Returns transform names, not shapes.
        """
        shapes = cmds.listConnections(
            f'{self.node_name}.outputGeometry',
            source=False,
            destination=True
        ) or []
        result = []
        for sh in shapes:
            parents = cmds.listRelatives(sh, parent=True, fullPath=True)
            if parents:
                result.append(parents[0])
            else:
                result.append(sh)
        return result

    @property
    def mesh_name(self) -> str:
        """Transform name of the currently active geometry (by geo_index)."""
        all_meshes = self.meshes
        if not all_meshes:
            raise RuntimeError(
                f"No geometry connected to deformer '{self.node_name}'"
            )
        if self.geo_index >= len(all_meshes):
            raise IndexError(
                f"geo_index {self.geo_index} out of range "
                f"(deformer has {len(all_meshes)} connected meshes)"
            )
        return all_meshes[self.geo_index]

    @property
    def vtx_count(self) -> int:
        """Live vertex / CV count for the active geometry."""
        try:
            shape = cmds.listConnections(
                f'{self.node_name}.outputGeometry[{self.geo_index}]',
                source=False,
                destination=True
            )[0]
            # polyMesh
            result = cmds.polyEvaluate(shape, vertex=True)
            if isinstance(result, int):
                return result
            # NURBS curve — fall back to CV count
            spans = cmds.getAttr(f'{shape}.spans')
            degree = cmds.getAttr(f'{shape}.degree')
            form = cmds.getAttr(f'{shape}.form')  # 0=open, 2=periodic
            return spans + degree if form == 0 else spans
        except Exception as e:
            logger.warning(f"Could not determine vertex count: {e}")
            return 0

    # ------------------------------------------------------------------
    # Weight attribute path — override in subclasses
    # ------------------------------------------------------------------

    @property
    def _weight_tokens(self) -> Dict[str, Union[str, int]]:
        """Tokens used to build the weight attribute path.

        Override in subclasses that use a different attribute layout
        (e.g. BlendShape, SkinCluster).
        """
        n = self.vtx_count
        return {
            'node':        self.node_name,
            'geoIndex':    self.geo_index,
            'weightRange': f'0:{n - 1}' if n > 0 else '0',
        }

    @property
    def _weight_attr_template(self) -> str:
        """Template string for the weight attribute path.

        Override in subclasses that use a different attribute.
        """
        return '{node}.weightList[{geoIndex}].weights[{weightRange}]'

    @property
    def _weight_attr_path(self) -> str:
        """Fully resolved weight attribute path."""
        return self._weight_attr_template.format(**self._weight_tokens)

    # ------------------------------------------------------------------
    # WeightSource protocol — get / set weights
    # ------------------------------------------------------------------

    def get_weights(self) -> WeightList:
        """Return the full per-vertex weight list for this deformer.

        Returns:
            List of weight values, one per vertex.
        """
        try:
            weights = cmds.getAttr(self._weight_attr_path)
            if weights is None:
                return []
            if not isinstance(weights, (list, tuple)):
                weights = [weights]
            return list(weights)
        except Exception as e:
            logger.error(f"Failed to get weights on '{self.node_name}': {e}")
            return []

    def set_weights(self, weights: WeightList) -> None:
        """Set the full per-vertex weight list for this deformer.

        Args:
            weights: One value per vertex.

        Raises:
            ValueError: If length does not match vtx_count.
        """
        n = self.vtx_count
        if len(weights) != n:
            raise ValueError(
                f"Weight count {len(weights)} != vertex count {n} "
                f"on '{self.node_name}'"
            )
        try:
            cmds.setAttr(self._weight_attr_path, *weights, size=n)
        except Exception as e:
            logger.error(f"Failed to set weights on '{self.node_name}': {e}")
            raise

    # ------------------------------------------------------------------
    # Operations — delegate to paint_core / paint_utils
    # ------------------------------------------------------------------

    def modify_weights(self,
                       value: float,
                       operation: Literal['multiply', 'add', 'replace'] = 'replace',
                       mask: Optional[List[List[int]]] = None) -> None:
        """Modify weights with a scalar operation.

        Args:
            value:     Scalar to apply.
            operation: 'multiply', 'add', or 'replace'.
            mask:      Optional list of vertex index specs [[start, end], [i], …].
        """
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
        """Remap weight values from one range to another.

        Args:
            old_min: Current minimum.
            old_max: Current maximum.
            new_min: Target minimum.
            new_max: Target maximum.
        """
        current = self.get_weights()
        if not current:
            return
        self.set_weights(
            dw_maya.dw_paint.remap_weights(current, old_min, old_max, new_min, new_max)
        )

    def mirror_weights(self,
                       axis: Literal['x', 'y', 'z'] = 'x',
                       world_space: bool = True) -> None:
        """Mirror weights across a specified axis.

        Args:
            axis:        Axis to mirror across.
            world_space: Use world or local space coordinates.
        """
        current = self.get_weights()
        if not current:
            return
        new_weights = dw_maya.dw_nucleus_utils.dw_nucleus_paint.mirror_vertex_map(
            current, self.mesh_name, axis, world_space
        )
        if new_weights:
            self.set_weights(new_weights)

    def smooth_weights(self,
                       iterations: int = 1,
                       smooth_factor: float = 0.5) -> None:
        """Smooth weights based on mesh topology.

        Args:
            iterations:    Number of smoothing passes.
            smooth_factor: Strength of smoothing (0–1).
        """
        current = self.get_weights()
        if not current:
            return
        new_weights = dw_maya.dw_nucleus_utils.dw_nucleus_paint.interpolate_vertex_map(
            current, self.mesh_name, iterations, smooth_factor
        )
        if new_weights:
            self.set_weights(new_weights)

    def distribute_weights_by_vector(self,
                                     direction: Union[str, Tuple[float, float, float]],
                                     remap_range: Optional[Tuple[float, float]] = None,
                                     falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
                                     origin: Optional[Tuple[float, float, float]] = None,
                                     invert: bool = False,
                                     mode: Literal['projection', 'distance'] = 'projection') -> None:
        """Set weights by projecting vertex positions onto a direction vector.

        Args:
            direction:   Predefined key ('x', 'y', 'z', …) or custom (x, y, z).
            remap_range: Optional (min, max) to clamp the result.
            falloff:     Falloff curve type.
            origin:      Origin point; defaults to mesh centre.
            invert:      Invert the resulting weights.
            mode:        'projection' (signed) or 'distance' (unsigned).
        """
        new_weights = dw_maya.dw_paint.set_vertex_weights_by_vector(
            self.mesh_name, direction, remap_range, falloff, origin, invert, mode
        )
        if new_weights:
            self.set_weights(new_weights)

    def distribute_weights_radial(self,
                                  center: Optional[Tuple[float, float, float]] = None,
                                  radius: Optional[float] = None,
                                  falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
                                  invert: bool = False) -> None:
        """Set weights by radial distance from a centre point.

        Args:
            center:  Centre of the radial distribution; defaults to mesh centre.
            radius:  Maximum influence radius; defaults to mesh extents.
            falloff: Falloff curve type.
            invert:  Invert the resulting weights.
        """
        new_weights = dw_maya.dw_paint.set_vertex_weights_radial(
            self.mesh_name, center, radius, falloff, invert
        )
        if new_weights:
            self.set_weights(new_weights)

    def copy_weights_from(self,
                          source: 'Deformer',
                          blend_factor: float = 1.0) -> None:
        """Copy weights from another Deformer, with optional blending.

        Args:
            source:       Source deformer to copy from.
            blend_factor: 1.0 = full copy; 0.0 = keep current weights.
        """
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

    def select_by_weight_range(self,
                               min_value: float,
                               max_value: float) -> None:
        """Select vertices whose weight falls within [min_value, max_value].

        Args:
            min_value: Lower bound (inclusive).
            max_value: Upper bound (inclusive).
        """
        weights = self.get_weights()
        if not weights:
            return
        dw_maya.dw_nucleus_utils.dw_nucleus_paint.select_vtx_info_on_mesh(
            weights, self.mesh_name, 'range',
            _min=min_value, _max=max_value
        )

    def get_affected_vertices(self) -> List[str]:
        """Return component strings for all vertices with weight > 0.

        Returns:
            e.g. ['pSphere1.vtx[0]', 'pSphere1.vtx[3]', …]
        """
        weights = self.get_weights()
        mesh = self.mesh_name
        return [f'{mesh}.vtx[{i}]' for i, w in enumerate(weights) if w > 0.0]

    # ------------------------------------------------------------------
    # Membership set
    # ------------------------------------------------------------------

    def _get_deformer_set(self) -> str:
        """Return the objectSet node connected to this deformer."""
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
        """Add geometry to this deformer's membership set."""
        try:
            if isinstance(geometry, str):
                geometry = [geometry]
            cmds.sets(geometry, add=self._get_deformer_set())
        except Exception as e:
            logger.error(f"Failed to add membership: {e}")

    def remove_membership(self, geometry: Union[str, List[str]]) -> None:
        """Remove geometry from this deformer's membership set."""
        try:
            if isinstance(geometry, str):
                geometry = [geometry]
            cmds.sets(geometry, remove=self._get_deformer_set())
        except Exception as e:
            logger.error(f"Failed to remove membership: {e}")

    # ------------------------------------------------------------------
    # Weight stash — lightweight undo buffer stored on the node itself
    # ------------------------------------------------------------------

    def stash_weights(self) -> None:
        """Store current weights in a custom attribute on the deformer node.

        Useful as a pre-operation backup before destructive edits.
        Restore with :meth:`restore_weights`.
        """
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
        """Save deformer weights to a JSON preset file.

        Args:
            name: Base name for the file (without extension).
            path: Directory path; uses project default if omitted.

        Returns:
            Absolute path to the saved file.
        """
        try:
            weights_dict = deformer_json.get_deformer_weights(self.node_name)
            return deformer_json.saveDeformerJson(name, weights_dict, path)
        except Exception as e:
            logger.error(f"Failed to save preset: {e}")
            return ''

    def load_preset(self, preset_path: str, blend_value: float = 1.0) -> None:
        """Load weights from a JSON preset file.

        Args:
            preset_path: Path to the JSON preset file.
            blend_value: Blend factor (1.0 = full replacement).
        """
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
    # Paint
    # ------------------------------------------------------------------

    def paint(self) -> None:
        """Open Maya's artisan paint tool for this deformer."""
        from dw_maya.dw_deformers.dw_core import paintWeights
        paintWeights(self.node_name)

    # ------------------------------------------------------------------
    # Internal helpers
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
        return (f"<{type(self).__name__} node='{self.node_name}' "
                f"mesh='{mesh}' vtx={self.vtx_count}>")


# ---------------------------------------------------------------------------
# Cluster
# ---------------------------------------------------------------------------
class Cluster(Deformer):
    """Cluster deformer — relative mode, handle, origin.

    Example:
        >>> c = make_deformer('cluster1')
        >>> c.get_weights()
        >>> c.set_origin((0, 5, 0))
    """

    def __init__(self, name: str, preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        super().__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != 'cluster':
            raise ValueError(f"'{name}' is not a cluster deformer")

    @property
    def handle(self) -> Optional[str]:
        """The cluster handle transform node."""
        handles = cmds.listConnections(
            f'{self.node_name}.matrix', source=True, destination=False
        )
        return handles[0] if handles else None

    def set_origin(self, position: Tuple[float, float, float]) -> None:
        """Move the cluster origin to a world-space position."""
        handle = self.handle
        if handle:
            cmds.xform(handle, worldSpace=True, translation=position)

    def set_relative(self, state: bool) -> None:
        """Toggle relative mode (True) vs absolute mode (False)."""
        cmds.setAttr(f'{self.node_name}.relative', state)


# ---------------------------------------------------------------------------
# SoftMod
# ---------------------------------------------------------------------------
class SoftMod(Deformer):
    """SoftMod deformer — falloff radius and curve.

    Example:
        >>> s = make_deformer('softMod1')
        >>> s.set_falloff_radius(5.0)
    """

    def __init__(self, name: str, preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        super().__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != 'softMod':
            raise ValueError(f"'{name}' is not a softMod deformer")

    def set_falloff_radius(self, radius: float) -> None:
        """Set the softMod falloff radius."""
        cmds.setAttr(f'{self.node_name}.falloffRadius', radius)

    def set_falloff_curve(self,
                          values: List[Tuple[float, float]],
                          curve_type: Literal['spline', 'linear'] = 'spline') -> None:
        """Set the falloff curve shape via ramp control points.

        Args:
            values:     List of (position, value) points, both in 0–1 range.
            curve_type: 'spline' for smooth or 'linear' for hard transitions.
        """
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

    :meth:`get_weights` / :meth:`set_weights` operate on the base (mask)
    weights.  Per-target vertex weights are accessed via
    :meth:`get_target_weights` / :meth:`set_target_weights`.
    Target slider values are accessed via :attr:`target_weights` and
    :meth:`set_target_weight`.

    Example:
        >>> bs = make_deformer('blendShape1')
        >>> bs.targets                       # [('smile', 0), ('frown', 1)]
        >>> bs.target_weights                # {'smile': 0.0, 'frown': 1.0}
        >>> bs.get_target_weights(0)         # per-vertex mask for target 0
        >>> bs.set_target_weight('smile', 0.5)
        >>> bs.add_target('myMesh_sculpted')
    """

    def __init__(self, name: str, preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        super().__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != 'blendShape':
            raise ValueError(f"'{name}' is not a blendShape deformer")

    @property
    def _weight_tokens(self) -> Dict[str, Union[str, int]]:
        n = self.vtx_count
        return {
            'node':        self.node_name,
            'geoIndex':    self.geo_index,
            'weightRange': f'0:{n - 1}' if n > 0 else '0',
        }

    @property
    def _weight_attr_template(self) -> str:
        """BlendShape base weights live on inputTarget, not weightList."""
        return '{node}.inputTarget[{geoIndex}].baseWeights[{weightRange}]'

    @property
    def targets(self) -> List[Tuple[str, int]]:
        """List of (name, index) pairs for all blend targets."""
        names = cmds.blendShape(self.node_name, query=True, target=True) or []
        return [(name, i) for i, name in enumerate(names)]

    @property
    def target_weights(self) -> Dict[str, float]:
        """Current slider values for all targets as {name: value}."""
        return {
            name: cmds.getAttr(f'{self.node_name}.{name}')
            for name, _ in self.targets
        }

    def get_target_weights(self, target_index: int) -> WeightList:
        """Per-vertex mask weights for a specific blend target.

        Args:
            target_index: Index matching the targets list.
        """
        n = self.vtx_count
        attr = (f'{self.node_name}.inputTarget[{self.geo_index}]'
                f'.inputTargetGroup[{target_index}].targetWeights[0:{n - 1}]')
        try:
            weights = cmds.getAttr(attr)
            if not isinstance(weights, (list, tuple)):
                weights = [weights]
            return list(weights)
        except Exception as e:
            logger.error(f"Failed to get target weights for index {target_index}: {e}")
            return []

    def set_target_weights(self, target_index: int, weights: WeightList) -> None:
        """Set per-vertex mask weights for a specific blend target.

        Args:
            target_index: Index matching the targets list.
            weights:      Per-vertex weight values.
        """
        n = self.vtx_count
        if len(weights) != n:
            raise ValueError(f"Weight count {len(weights)} != vertex count {n}")
        attr = (f'{self.node_name}.inputTarget[{self.geo_index}]'
                f'.inputTargetGroup[{target_index}].targetWeights[0:{n - 1}]')
        cmds.setAttr(attr, *weights, size=n)

    def set_target_weight(self, target: str, weight: float) -> None:
        """Set the slider value (envelope) for a named target.

        Args:
            target: Target name as it appears in the targets list.
            weight: Slider value (typically 0–1).
        """
        target_names = [name for name, _ in self.targets]
        if target in target_names:
            cmds.setAttr(f'{self.node_name}.{target}', weight)
        else:
            logger.warning(
                f"Target '{target}' not found on '{self.node_name}'. "
                f"Available: {target_names}"
            )

    def add_target(self, target_mesh: str, weight: float = 1.0) -> None:
        """Add a new blend target from an existing mesh.

        Args:
            target_mesh: Name of the sculpted mesh to add as a target.
            weight:      Initial slider weight.
        """
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
        """Add an in-between target at a specific slider value.

        Args:
            target:            Name of the parent target.
            target_mesh:       Mesh to use as the in-between shape.
            in_between_weight: Slider value at which the in-between peaks.
        """
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
        """Open artisan specifically for blendShape base weights."""
        cmds.select(self.mesh_name, replace=True)
        cmds.setToolTo('selectSuperContext')
        mel.eval(
            f'artSetToolAndSelectAttr("artAttrCtx", '
            f'"blendShape.{self.node_name}.baseWeights")'
        )


# ---------------------------------------------------------------------------
# Wire
# ---------------------------------------------------------------------------
class Wire(Deformer):
    """Wire deformer — wire curves and dropoff distance.

    Example:
        >>> w = make_deformer('wire1')
        >>> w.wire_curves
        ['curve1']
        >>> w.set_dropoff_distance(3.0)
    """

    def __init__(self, name: str, preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        super().__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != 'wire':
            raise ValueError(f"'{name}' is not a wire deformer")

    @property
    def wire_curves(self) -> List[str]:
        """Names of the wire curve objects."""
        return cmds.wire(self.node_name, query=True, wire=True) or []

    def set_dropoff_distance(self, distance: float,
                              curve_index: int = 0) -> None:
        """Set the dropoff distance for a wire curve.

        Args:
            distance:    Influence dropoff distance.
            curve_index: Index of the wire curve (multi-wire setups).
        """
        cmds.wire(self.node_name, edit=True,
                  dropoffDistance=(curve_index, distance))


# ---------------------------------------------------------------------------
# SkinCluster
# ---------------------------------------------------------------------------
class SkinCluster(Deformer):
    """SkinCluster deformer — influences, per-influence weights.

    Example:
        >>> sc = make_deformer('skinCluster1')
        >>> sc.influences
        ['joint1', 'joint2']
        >>> sc.get_influence_weights('joint1')
    """

    def __init__(self, name: str, preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        super().__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != 'skinCluster':
            raise ValueError(f"'{name}' is not a skinCluster deformer")
        self.__dict__['_influence_index'] = 0

    @property
    def _weight_tokens(self) -> Dict[str, Union[str, int]]:
        n = self.vtx_count
        influences = self.influences
        return {
            'node':           self.node_name,
            'geoIndex':       self.geo_index,
            'influenceIndex': self.__dict__['_influence_index'],
            'influence':      (influences[self.__dict__['_influence_index']]
                               if influences else ''),
            'weightRange':    f'0:{n - 1}' if n > 0 else '0',
        }

    @property
    def _weight_attr_template(self) -> str:
        return '{node}.weightList[{geoIndex}].weights[{weightRange}]'

    @property
    def influences(self) -> List[str]:
        """All influence objects (joints) bound to this skinCluster."""
        return cmds.skinCluster(self.node_name, query=True, influence=True) or []

    def set_influence(self, influence: Union[str, int]) -> None:
        """Set the active influence for subsequent weight operations.

        Args:
            influence: Joint name or zero-based index.
        """
        all_influences = self.influences
        if isinstance(influence, str):
            if influence in all_influences:
                self.__dict__['_influence_index'] = all_influences.index(influence)
            else:
                logger.warning(
                    f"Influence '{influence}' not found on '{self.node_name}'"
                )
        elif isinstance(influence, int):
            if 0 <= influence < len(all_influences):
                self.__dict__['_influence_index'] = influence
            else:
                raise IndexError(
                    f"Influence index {influence} out of range "
                    f"({len(all_influences)} influences)"
                )

    def get_influence_weights(self, influence: str) -> WeightList:
        """Per-vertex weights for a specific influence object.

        Args:
            influence: Joint name.
        """
        all_influences = self.influences
        if influence not in all_influences:
            logger.warning(f"Influence '{influence}' not found")
            return []
        n = self.vtx_count
        attr = (f'{self.node_name}.weightList[{self.geo_index}]'
                f'.weights[0:{n - 1}]')
        weights = cmds.getAttr(attr) or []
        return list(weights)

    def add_influence(self, joint: str, default_weight: float = 0.0) -> None:
        """Add a joint as an influence to this skinCluster.

        Args:
            joint:          Joint node name.
            default_weight: Initial weight for new influence (usually 0).
        """
        if cmds.objExists(joint):
            cmds.skinCluster(
                self.node_name, edit=True,
                addInfluence=joint, weight=default_weight
            )
        else:
            logger.warning(f"Joint '{joint}' does not exist")


# ---------------------------------------------------------------------------
# NClothMap
# ---------------------------------------------------------------------------
class NClothMap(WeightSource):
    """Per-vertex map on an nCloth or nRigid node.

    Wraps a single named map (e.g. 'thickness', 'bendResistance') and
    exposes the same get_weights / set_weights interface as Deformer
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

    @property
    def node_name(self) -> str:
        return self._nucleus_node

    @property
    def mesh_name(self) -> str:
        return self._mesh_name

    @property
    def vtx_count(self) -> int:
        try:
            return cmds.polyEvaluate(self._mesh_name, vertex=True)
        except Exception:
            return 0

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

    def paint(self) -> None:
        """Open Maya's artisan paint tool for this nucleus map."""
        from dw_maya.dw_nucleus_utils import artisan_nucx_update
        artisan_nucx_update(self._nucleus_node, self._map_name, True)

    def __repr__(self) -> str:
        return (f"<NClothMap node='{self._nucleus_node}' "
                f"map='{self._map_name}' mesh='{self._mesh_name}' "
                f"map_type={self.map_type}>")


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

    The target mesh is resolved automatically from the deformer's output
    connections — no need to pass it in.

    Args:
        node:        Deformer node name.
        preset:      Optional preset dict.
        blend_value: Blend factor for preset loading.

    Returns:
        Appropriate Deformer subclass instance.

    Raises:
        ValueError: If node does not exist or is not a geometry deformer.

    Example:
        >>> make_deformer('cluster1')
        <Cluster node='cluster1' mesh='pSphere1' vtx=382>

        >>> make_deformer('blendShape1')
        <BlendShape node='blendShape1' mesh='pSphere1' vtx=382>
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


def resolve_weight_sources(mesh: str,
                           mode: Literal['all', 'deformer', 'nucleus'] = 'all'
                           ) -> List[WeightSource]:
    """Return all WeightSource objects available on a mesh.

    Queries both standard deformers (via history) and nucleus per-vertex
    maps so the UI never needs to handle the two backends separately.
    The ``mode`` parameter lets callers restrict to one backend — useful
    for the UI's mode-toggle button.

    Args:
        mesh: Mesh transform name.
        mode: Which backends to include:
              'all'      — deformers + nucleus maps (default)
              'deformer' — standard Maya deformers only
              'nucleus'  — nCloth/nRigid per-vertex maps only

    Returns:
        List of WeightSource instances: deformers first, then nucleus maps.

    Example:
        >>> resolve_weight_sources('pSphere1')
        [<Cluster ...>, <BlendShape ...>, <NClothMap ...>]

        >>> resolve_weight_sources('pSphere1', mode='nucleus')
        [<NClothMap ...>, <NClothMap ...>]
    """
    from dw_maya.dw_deformers.dw_core import listDeformers
    from dw_maya.dw_nucleus_utils.dw_core import get_nucx_node, get_pervertex_maps

    sources: List[WeightSource] = []

    if mode in ('all', 'deformer'):
        for node in listDeformers(mesh):
            try:
                sources.append(make_deformer(node))
            except Exception as e:
                logger.warning(f"Could not wrap deformer '{node}': {e}")

    if mode in ('all', 'nucleus'):
        try:
            nucx_node = get_nucx_node(mesh)
            if nucx_node:
                for map_name in get_pervertex_maps(nucx_node):
                    try:
                        sources.append(NClothMap(nucx_node, map_name, mesh))
                    except Exception as e:
                        logger.warning(
                            f"Could not wrap nucleus map '{map_name}' "
                            f"on '{nucx_node}': {e}"
                        )
        except Exception as e:
            logger.debug(f"No nucleus node found for '{mesh}': {e}")

    return sources


# ---------------------------------------------------------------------------
# Phase 3 — unified paint dispatch and operation helpers
# ---------------------------------------------------------------------------

def paint_weight_source(source: WeightSource,
                        nucleus_node: Optional[str] = None) -> None:
    """Open the appropriate Maya paint tool for any WeightSource.

    Handles both standard deformer artisan and nucleus artisan so the
    UI paint button is completely backend-agnostic.

    For nucleus maps an optional ``nucleus_node`` can be supplied to
    force-enable the solver before opening artisan (useful when the
    simulation hasn't been run yet on the current frame).

    Args:
        source:       Any WeightSource — Deformer subclass or NClothMap.
        nucleus_node: Optional nucleus solver node name.  When provided
                      and artisan fails, the solver is force-enabled and
                      artisan is retried automatically.

    Example:
        >>> sources = resolve_weight_sources('pSphere1')
        >>> paint_weight_source(sources[0])   # works for cluster or nCloth map
    """
    if isinstance(source, NClothMap):
        _paint_nucleus_map(source, nucleus_node)
    elif isinstance(source, BlendShape):
        # BlendShape overrides paint() itself — delegate
        source.paint()
    elif isinstance(source, Deformer):
        _paint_deformer(source)
    else:
        raise TypeError(
            f"Cannot paint unsupported WeightSource type: {type(source).__name__}"
        )


def _paint_deformer(source: Deformer) -> None:
    """Internal: open artisan for a standard deformer WeightSource."""
    _ARTISAN_ATTRS: Dict[str, str] = {
        'cluster':    'cluster.{node}.weights',
        'softMod':    'softMod.{node}.weights',
        'blendShape': 'blendShape.{node}.baseWeights',
        'deltaMush':  'deltaMush.{node}.weights',
        'wire':       'wire.{node}.weights',
    }
    node_type = cmds.nodeType(source.node_name)
    template = _ARTISAN_ATTRS.get(node_type)
    if template is None:
        logger.warning(
            f"Paint not supported for deformer type '{node_type}' "
            f"on '{source.node_name}'"
        )
        return

    artisan_attr = template.format(node=source.node_name)

    # Prefer any selected vertices on the target mesh; fall back to full mesh
    vtx = cmds.filterExpand(selectionMask=31, expand=False) or []
    if vtx and vtx[0].split('.')[0] == source.mesh_name:
        sel = vtx
    else:
        sel = source.mesh_name

    cmds.select(sel, replace=True)
    cmds.setToolTo('selectSuperContext')
    mel.eval(f'artSetToolAndSelectAttr("artAttrCtx", "{artisan_attr}")')


def _paint_nucleus_map(source: NClothMap,
                       nucleus_node: Optional[str] = None) -> None:
    """Internal: open artisan for a nucleus per-vertex map WeightSource."""
    from dw_maya.dw_nucleus_utils import artisan_nucx_update

    # Ensure map type is Vertex before painting — a map at type 0 (None)
    # would accept paint strokes but silently discard them.
    if source.map_type == 0:
        logger.debug(
            f"Promoting '{source._map_name}' to MapType=Vertex before painting"
        )
        source.map_type = 1

    try:
        artisan_nucx_update(source.node_name, source._map_name, True)
    except Exception:
        # First attempt failed — try force-enabling the nucleus solver
        if nucleus_node and cmds.objExists(nucleus_node):
            logger.debug(
                f"Artisan failed; force-enabling nucleus '{nucleus_node}' "
                f"and retrying"
            )
            _force_enable_nucleus(nucleus_node)
            try:
                artisan_nucx_update(source.node_name, source._map_name, True)
            except Exception as e:
                raise RuntimeError(
                    f"Could not open paint tool for nucleus map "
                    f"'{source._map_name}' on '{source.node_name}'. "
                    f"Ensure the nucleus is active and scrub to the first frame. "
                    f"Detail: {e}"
                )
        else:
            raise RuntimeError(
                f"Could not open paint tool for nucleus map "
                f"'{source._map_name}' on '{source.node_name}'. "
                f"Pass nucleus_node= to force-enable the solver."
            )


def _force_enable_nucleus(nucleus_node: str) -> None:
    """Set a nucleus solver to enabled and jump to its start frame."""
    cmds.setAttr(f'{nucleus_node}.visibility', 1)
    try:
        cmds.setAttr(f'{nucleus_node}.enable', 1)
    except Exception:
        pass
    start_frame = cmds.getAttr(f'{nucleus_node}.startFrame')
    cmds.currentTime(start_frame, update=True)


def apply_operation(source: WeightSource,
                    operation: Literal['flood', 'mirror', 'smooth',
                                       'vector', 'radial'],
                    **kwargs) -> None:
    """Apply a weight operation to any WeightSource — deformer or nucleus map.

    This is the single call-site for the UI's operation buttons.  It reads
    weights from the source, runs the operation, and writes the result back
    — the caller never touches raw weight lists or cares about the backend.

    Args:
        source:    Any WeightSource (Deformer subclass or NClothMap).
        operation: Which operation to apply:
                   'flood'  — set / add / multiply a scalar value
                   'mirror' — mirror across an axis
                   'smooth' — topology-based smoothing
                   'vector' — distribute by direction vector
                   'radial' — distribute by radial distance
        **kwargs:  Forwarded to the underlying operation function.
                   See each operation's docstring for accepted kwargs.

    Keyword args by operation:

        flood:
            value (float):      Value to apply. Required.
            op (str):           'replace' | 'add' | 'multiply'. Default 'replace'.
            mask (list|None):   Vertex index specs. Default None (all vertices).
            clamp_min (float):  Lower clamp. Default 0.0.
            clamp_max (float):  Upper clamp. Default 1.0.

        mirror:
            axis (str):         'x' | 'y' | 'z'. Default 'x'.
            world_space (bool): Use world space. Default True.

        smooth:
            iterations (int):   Smoothing passes. Default 1.
            factor (float):     Smoothing strength 0–1. Default 0.5.

        vector:
            direction:          Predefined key or (x, y, z) tuple. Required.
            remap_range:        Optional (min, max) clamp tuple.
            falloff (str):      'linear' | 'quadratic' | 'smooth' | 'smooth2'.
            origin:             Optional (x, y, z) origin point.
            invert (bool):      Invert result. Default False.
            mode (str):         'projection' | 'distance'. Default 'projection'.

        radial:
            center:             Optional (x, y, z) centre point.
            radius (float):     Max influence radius.
            falloff (str):      Falloff curve type.
            invert (bool):      Invert result. Default False.

    Example:
        >>> src = resolve_weight_sources('pSphere1')[0]
        >>> apply_operation(src, 'flood', value=0.5)
        >>> apply_operation(src, 'mirror', axis='x')
        >>> apply_operation(src, 'smooth', iterations=3, factor=0.5)
        >>> apply_operation(src, 'vector', direction='y', falloff='smooth')
        >>> apply_operation(src, 'radial', center=(0,0,0), invert=True)
    """
    weights = source.get_weights()
    if not weights:
        logger.warning(
            f"apply_operation: no weights returned from '{source.node_name}'"
        )
        return

    mesh = source.mesh_name
    new_weights: Optional[WeightList] = None

    if operation == 'flood':
        new_weights = _op_flood(weights, **kwargs)

    elif operation == 'mirror':
        new_weights = dw_maya.dw_nucleus_utils.dw_nucleus_paint.mirror_vertex_map(weights, mesh, kwargs.get('axis', 'x'), kwargs.get('world_space', True))

    elif operation == 'smooth':
        new_weights = dw_maya.dw_nucleus_utils.dw_nucleus_paint.interpolate_vertex_map(
            weights, mesh,
            kwargs.get('iterations', 1),
            kwargs.get('factor', 0.5)
        )

    elif operation == 'vector':
        if 'direction' not in kwargs:
            raise ValueError("apply_operation 'vector' requires a 'direction' kwarg")
        new_weights = dw_maya.dw_nucleus_utils.dw_nucleus_paint.set_vertex_weights_by_vector(
            mesh,
            kwargs['direction'],
            kwargs.get('remap_range'),
            kwargs.get('falloff', 'linear'),
            kwargs.get('origin'),
            kwargs.get('invert', False),
            kwargs.get('mode', 'projection'),
        )

    elif operation == 'radial':
        new_weights = dw_maya.dw_nucleus_utils.dw_nucleus_paint.set_vertex_weights_radial(
            mesh,
            kwargs.get('center'),
            kwargs.get('radius'),
            kwargs.get('falloff', 'linear'),
            kwargs.get('invert', False),
        )

    else:
        raise ValueError(
            f"Unknown operation '{operation}'. "
            f"Must be one of: flood, mirror, smooth, vector, radial."
        )

    if new_weights is not None:
        source.set_weights(new_weights)
    else:
        logger.warning(
            f"apply_operation '{operation}' returned no weights for "
            f"'{source.node_name}' — weights unchanged"
        )


def _op_flood(weights: WeightList,
              value: float,
              op: Literal['replace', 'add', 'multiply'] = 'replace',
              mask: Optional[List] = None,
              clamp_min: float = 0.0,
              clamp_max: float = 1.0) -> WeightList:
    """Apply a flood operation to a weight list.

    Separated from apply_operation so it can be unit-tested without Maya.
    """
    return dw_maya.dw_paint.modify_weights(
        weights, value, op, mask,
        min_value=clamp_min, max_value=clamp_max
    )
