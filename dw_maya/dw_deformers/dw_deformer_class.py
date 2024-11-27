from typing import List, Dict, Union, Optional, Tuple, Literal
from maya import cmds
from dw_maya.dw_maya_nodes import MayaNode
import dw_maya.dw_paint.dw_paint_core as paint_core
import dw_maya.dw_paint.dw_paint_utils as paint_utils
import dw_maya.dw_presets_io.dw_deformer_json as deformer_json
import dw_maya.dw_presets_io.dw_preset as preset_utils
from dw_logger import get_logger

logger = get_logger()


class Deformer(MayaNode):
    """A specialized class for handling Maya deformers.

    Provides high-level access to deformer operations including weight management,
    painting, mathematical operations, and preset handling.

    Args:
        name: Name of the deformer node
        preset: Optional preset dictionary for initialization
        blend_value: Blend factor when applying presets (0-1)

    Example:
        >>> deformer = Deformer('cluster1')
        >>> deformer.get_weights()  # Get current weights
        >>> deformer.set_weights([0.5] * 100)  # Set uniform weights
        >>> deformer.paint()  # Enable weight painting
    """

    def __init__(self, name: str, preset: Optional[Dict] = None, blend_value: float = 1.0):
        super(Deformer, self).__init__(name, preset, blend_value)

        # Validate that this is actually a deformer
        if not self._is_deformer():
            raise ValueError(f"Node '{name}' is not a deformer")

        self._connection_index = 0  # Default connection index

    @property
    def connection_index(self) -> int:
        """Current geometry connection index."""
        return self._connection_index

    @connection_index.setter
    def connection_index(self, index: int):
        """Set the current geometry connection index."""
        self._connection_index = index

    @property
    def _weight_tokens(self) -> Dict[str, Union[str, int]]:
        """Tokens used to build the weight attribute path.

        Returns:
            Dictionary of tokens and their current values

        Example:
            {
                'node': self.node,
                'geoIndex': self.connection_index,
                'weightRange': f'0:{self.vertex_count-1}'
            }
        """
        count = self.vertex_count
        return {
            'node': self.node,
            'geoIndex': self.connection_index,
            'weightRange': f'0:{count - 1}' if count > 0 else '0'
        }

    @property
    def _weight_attr_template(self) -> str:
        """Template string for weight attribute path.

        Returns:
            String with {token} placeholders

        Example:
            '{node}.weightList[{geoIndex}].weights[{weightRange}]'
        """
        return '{node}.weightList[{geoIndex}].weights[{weightRange}]'

    @property
    def _weight_attr_path(self) -> str:
        """Build the full attribute path using template and tokens."""
        return self._weight_attr_template.format(**self._weight_tokens)

    def _is_deformer(self) -> bool:
        """Check if the node is a valid deformer."""
        return "geometryFilter" in (cmds.nodeType(self.node, inherited=True) or [])

    @property
    def vertex_count(self) -> int:
        """Get the number of vertices affected by this deformer.

        Returns:
            Number of vertices in the deformed geometry
        """
        try:
            mesh = cmds.listConnections(f'{self.node}.outputGeometry[0]',
                                        source=False,
                                        destination=True)[0]
            return cmds.polyEvaluate(mesh, vertex=True)
        except Exception:
            return 0

    def get_weights(self, connection_index: int = 0) -> List[float]:
        """Get weights using the defined attribute path.

        Args:
            connection_index: Index of the geometry connection

        Returns:
            List of weight values
        """
        try:
            weights = cmds.getAttr(self._weight_attr_path)
            if not isinstance(weights, (list, tuple)):
                weights = [weights]
            return list(weights)
        except Exception as e:
            logger.error(f"Failed to get weights: {e}")
            return []

    def set_weights(self, weights: List[float], connection_index: int = 0) -> None:
        """Set weights using the defined attribute path.

        Args:
            weights: List of weight values
            connection_index: Index of the geometry connection
        """
        try:
            cmds.setAttr(self._weight_attr_path, *weights, size=len(weights))
        except Exception as e:
            logger.error(f"Failed to set weights: {e}")

    def paint(self) -> None:
        """Enable the paint weights tool for this deformer."""
        paint_core.paintWeights(self.node)

    def modify_weights(self,
                       value: float,
                       operation: Literal['multiply', 'add', 'replace'] = 'replace',
                       mask: Optional[List[List[int]]] = None,
                       connection_index: int = 0) -> None:
        """Modify deformer weights using various operations.

        Args:
            value: Value to use in the operation
            operation: Type of operation to perform
            mask: Optional list of vertex indices to affect
            connection_index: Index of the geometry connection
        """
        try:
            current_weights = self.get_weights(connection_index)
            if not current_weights:
                return

            new_weights = paint_utils.modify_weights(
                current_weights,
                value,
                operation,
                mask,
                min_value=0.0,
                max_value=1.0
            )
            self.set_weights(new_weights, connection_index)
        except Exception as e:
            logger.error(f"Failed to modify weights: {e}")

    def remap_weights(self,
                      old_min: float,
                      old_max: float,
                      new_min: float,
                      new_max: float,
                      connection_index: int = 0) -> None:
        """Remap weight values from one range to another.

        Args:
            old_min: Current minimum value
            old_max: Current maximum value
            new_min: Target minimum value
            new_max: Target maximum value
            connection_index: Index of the geometry connection
        """
        try:
            current_weights = self.get_weights(connection_index)
            if not current_weights:
                return

            new_weights = paint_utils.remap_weights(
                current_weights,
                old_min,
                old_max,
                new_min,
                new_max
            )
            self.set_weights(new_weights, connection_index)
        except Exception as e:
            logger.error(f"Failed to remap weights: {e}")

    def save_preset(self, name: str, path: Optional[str] = None) -> str:
        """Save the deformer's current state as a preset.

        Args:
            name: Name for the preset file
            path: Optional custom save location

        Returns:
            Path to the saved preset file
        """
        try:
            weights_dict = deformer_json.get_deformer_weights(self.node)
            return deformer_json.saveDeformerJson(name, weights_dict, path)
        except Exception as e:
            logger.error(f"Failed to save preset: {e}")
            return ""

    def load_preset(self, preset_path: str, blend_value: float = 1.0) -> None:
        """Load a previously saved preset.

        Args:
            preset_path: Path to the preset file
            blend_value: Blend factor for applying the preset (0-1)
        """
        try:
            preset_data = deformer_json.loadDeformerJson(preset_path)
            if not preset_data:
                return

            deformer_json.setDeformersFromJson(preset_path)

            # Apply attribute preset if it exists
            if isinstance(preset_data, dict):
                preset_utils.blendAttrDic(self.node, None, preset_data, blend_value)
        except Exception as e:
            logger.error(f"Failed to load preset: {e}")

    def select_by_weight_range(self,
                               min_value: float,
                               max_value: float,
                               connection_index: int = 0) -> None:
        """Select vertices based on their weight values.

        Args:
            min_value: Minimum weight value
            max_value: Maximum weight value
            connection_index: Index of the geometry connection
        """
        try:
            weights = self.get_weights(connection_index)
            if not weights:
                return

            # Get the affected mesh
            mesh = cmds.listConnections(f'{self.node}.outputGeometry[{connection_index}]',
                                        source=False,
                                        destination=True)[0]

            paint_core.select_vtx_info_on_mesh(
                weights,
                mesh,
                'range',
                _min=min_value,
                _max=max_value
            )
        except Exception as e:
            logger.error(f"Failed to select by weight range: {e}")

    def mirror_weights(self,
                       axis: Literal['x', 'y', 'z'] = 'x',
                       world_space: bool = True,
                       connection_index: int = 0) -> None:
        """Mirror deformer weights across a specified axis.

        Args:
            axis: Axis to mirror across
            world_space: Use world or local space
            connection_index: Index of the geometry connection
        """
        try:
            # Get the connected mesh
            mesh = cmds.listConnections(f'{self.node}.outputGeometry[{connection_index}]',
                                        source=False,
                                        destination=True)[0]

            current_weights = self.get_weights(connection_index)
            if not current_weights:
                return

            new_weights = paint_core.mirror_vertex_map(
                current_weights,
                mesh,
                axis,
                world_space
            )
            if new_weights:
                self.set_weights(new_weights, connection_index)
        except Exception as e:
            logger.error(f"Failed to mirror weights: {e}")

    def smooth_weights(self,
                       iterations: int = 1,
                       smooth_factor: float = 0.5,
                       connection_index: int = 0) -> None:
        """Smooth deformer weights based on neighboring vertices.

        Args:
            iterations: Number of smoothing passes
            smooth_factor: Strength of smoothing (0-1)
            connection_index: Index of the geometry connection
        """
        try:
            # Get the connected mesh
            mesh = cmds.listConnections(f'{self.node}.outputGeometry[{connection_index}]',
                                        source=False,
                                        destination=True)[0]

            current_weights = self.get_weights(connection_index)
            if not current_weights:
                return

            new_weights = paint_core.interpolate_vertex_map(
                current_weights,
                mesh,
                iterations,
                smooth_factor
            )
            if new_weights:
                self.set_weights(new_weights, connection_index)
        except Exception as e:
            logger.error(f"Failed to smooth weights: {e}")

    def distribute_weights_by_vector(self,
                                     direction: Union[str, Tuple[float, float, float]],
                                     remap_range: Optional[Tuple[float, float]] = None,
                                     falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
                                     origin: Optional[Tuple[float, float, float]] = None,
                                     invert: bool = False,
                                     mode: Literal['projection', 'distance'] = 'projection',
                                     connection_index: int = 0) -> None:
        """Set weights based on vertex positions along a vector.

        Args:
            direction: Predefined direction ('x', 'y', 'z', etc.) or custom vector
            remap_range: Optional range to remap weights
            falloff: Type of falloff curve
            origin: Optional origin point for calculations
            invert: Whether to invert the weights
            mode: Use projection or distance for calculations
            connection_index: Index of the geometry connection
        """
        try:
            mesh = cmds.listConnections(f'{self.node}.outputGeometry[{connection_index}]',
                                        source=False,
                                        destination=True)[0]

            new_weights = paint_core.set_vertex_weights_by_vector(
                mesh,
                direction,
                remap_range,
                falloff,
                origin,
                invert,
                mode
            )
            if new_weights:
                self.set_weights(new_weights, connection_index)
        except Exception as e:
            logger.error(f"Failed to distribute weights: {e}")

    def distribute_weights_radial(self,
                                  center: Optional[Tuple[float, float, float]] = None,
                                  radius: Optional[float] = None,
                                  falloff: Literal['linear', 'quadratic', 'smooth', 'smooth2'] = 'linear',
                                  invert: bool = False,
                                  connection_index: int = 0) -> None:
        """Set weights based on radial distance from a center point.

        Args:
            center: Center point for radial distribution
            radius: Maximum affect radius
            falloff: Type of falloff curve
            invert: Whether to invert the weights
            connection_index: Index of the geometry connection
        """
        try:
            mesh = cmds.listConnections(f'{self.node}.outputGeometry[{connection_index}]',
                                        source=False,
                                        destination=True)[0]

            new_weights = paint_core.set_vertex_weights_radial(
                mesh,
                center,
                radius,
                falloff,
                invert
            )
            if new_weights:
                self.set_weights(new_weights, connection_index)
        except Exception as e:
            logger.error(f"Failed to distribute radial weights: {e}")

    def copy_weights_from(self,
                          source_deformer: 'Deformer',
                          blend_factor: float = 1.0,
                          connection_index: int = 0) -> None:
        """Copy weights from another deformer with optional blending.

        Args:
            source_deformer: Deformer to copy weights from
            blend_factor: Blend factor between current and new weights (0-1)
            connection_index: Index of the geometry connection
        """
        try:
            source_weights = source_deformer.get_weights(connection_index)
            if not source_weights:
                return

            if blend_factor < 1.0:
                current_weights = self.get_weights(connection_index)
                if current_weights:
                    new_weights = paint_utils.blend_weight_lists(
                        current_weights,
                        source_weights,
                        blend_factor
                    )
                    self.set_weights(new_weights, connection_index)
            else:
                self.set_weights(source_weights, connection_index)
        except Exception as e:
            logger.error(f"Failed to copy weights: {e}")

    def get_affected_vertices(self, connection_index: int = 0) -> List[str]:
        """Get list of vertices affected by this deformer.

        Args:
            connection_index: Index of the geometry connection

        Returns:
            List of vertex names (e.g. ['pCube1.vtx[0]', 'pCube1.vtx[1]'])
        """
        try:
            weights = self.get_weights(connection_index)
            if not weights:
                return []

            mesh = cmds.listConnections(f'{self.node}.outputGeometry[{connection_index}]',
                                        source=False,
                                        destination=True)[0]

            return [f"{mesh}.vtx[{i}]" for i, w in enumerate(weights) if w > 0.0]
        except Exception as e:
            logger.error(f"Failed to get affected vertices: {e}")
            return []

    def add_membership(self, geometry: Union[str, List[str]]) -> None:
        """Add geometry to deformer's membership set.

        Args:
            geometry: Name or list of names of geometry to add
        """
        try:
            # Get deformer's set
            deformer_set = cmds.listConnections(self.node, type="objectSet")[0]
            if isinstance(geometry, str):
                geometry = [geometry]

            cmds.sets(geometry, add=deformer_set)
        except Exception as e:
            logger.error(f"Failed to add membership: {e}")

    def remove_membership(self, geometry: Union[str, List[str]]) -> None:
        """Remove geometry from deformer's membership set.

        Args:
            geometry: Name or list of names of geometry to remove
        """
        try:
            deformer_set = cmds.listConnections(self.node, type="objectSet")[0]
            if isinstance(geometry, str):
                geometry = [geometry]

            cmds.sets(geometry, remove=deformer_set)
        except Exception as e:
            logger.error(f"Failed to remove membership: {e}")

    def get_membership(self) -> List[str]:
        """Get list of geometry in deformer's membership set.

        Returns:
            List of geometry names affected by this deformer
        """
        try:
            deformer_set = cmds.listConnections(self.node, type="objectSet")[0]
            return cmds.sets(deformer_set, q=True) or []
        except Exception as e:
            logger.error(f"Failed to get membership: {e}")
            return []

    def stash_weights(self) -> None:
        """Store current weights in a custom attribute for later restoration."""
        try:
            weights = self.get_weights()
            if not weights:
                return

            # Create array attribute if it doesn't exist
            attr_name = "storedWeights"
            if not cmds.attributeQuery(attr_name, node=self.node, exists=True):
                cmds.addAttr(self.node, ln=attr_name, dt="doubleArray")

            # Store weights
            cmds.setAttr(f"{self.node}.{attr_name}", weights, type="doubleArray")
        except Exception as e:
            logger.error(f"Failed to stash weights: {e}")

    def restore_weights(self) -> None:
        """Restore weights from stashed values."""
        try:
            attr_name = "storedWeights"
            if not cmds.attributeQuery(attr_name, node=self.node, exists=True):
                logger.warning("No stashed weights found")
                return

            weights = cmds.getAttr(f"{self.node}.{attr_name}")
            if weights:
                self.set_weights(weights)
        except Exception as e:
            logger.error(f"Failed to restore weights: {e}")


class BlendShape(Deformer):
    """Specialized class for blendShape deformers.

    Provides access to blendShape-specific functionality like targets,
    in-between targets, and topology checking.
    """

    def __init__(self, name: str, preset: Optional[Dict] = None, blend_value: float = 1.0):
        super(BlendShape, self).__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != "blendShape":
            raise ValueError(f"Node '{name}' is not a blendShape deformer")

    @property
    def _weight_tokens(self) -> Dict[str, Union[str, int]]:
        """Override tokens for blendShape specific paths."""
        count = self.vertex_count
        return {
            'node': self.node,
            'geoIndex': self.connection_index,
            'targetIndex': 0,  # For base weights
            'weightRange': f'0:{count - 1}' if count > 0 else '0'
        }

    @property
    def _weight_attr_template(self) -> str:
        """Template for blendShape base weights."""
        return '{node}.inputTarget[{geoIndex}].baseWeights[{weightRange}]'

    def get_target_weights(self, target_index: int) -> List[float]:
        """Get weights for a specific target."""
        # Override tokens for target weights
        tokens = self._weight_tokens
        tokens['targetIndex'] = target_index

        # Use target-specific template
        template = '{node}.inputTarget[{geoIndex}].inputTargetGroup[{targetIndex}]' \
                   '.targetWeights[{weightRange}]'

        attr_path = template.format(**tokens)
        try:
            weights = cmds.getAttr(attr_path)
            if not isinstance(weights, (list, tuple)):
                weights = [weights]
            return list(weights)
        except Exception as e:
            logger.error(f"Failed to get target weights: {e}")
            return []

    @property
    def targets(self) -> List[str]:
        """Get list of all blendShape targets.

        Returns:
            List of target names
        """
        return cmds.blendShape(self.node, q=True, target=True) or []

    @property
    def target_weights(self) -> Dict[str, float]:
        """Get current weight values for all targets.

        Returns:
            Dictionary mapping target names to their weights
        """
        return {target: cmds.getAttr(f"{self.node}.{target}")
                for target in self.targets}

    def set_target_weight(self, target: str, weight: float) -> None:
        """Set the weight of a specific target.

        Args:
            target: Name of the target
            weight: Weight value (usually 0-1)
        """
        if target in self.targets:
            cmds.setAttr(f"{self.node}.{target}", weight)

    def add_target(self, target_mesh: str, weight: float = 1.0) -> None:
        """Add a new target to the blendShape.

        Args:
            target_mesh: Mesh to use as target
            weight: Initial weight value
        """
        base_mesh = cmds.listConnections(f'{self.node}.outputGeometry[0]',
                                         source=False,
                                         destination=True)[0]
        index = len(self.targets)
        cmds.blendShape(self.node, edit=True,
                        target=(base_mesh, index, target_mesh, weight))

    def add_inbetween_target(self, target: str,
                             target_mesh: str,
                             in_between_weight: float) -> None:
        """Add an in-between target at a specific weight value.

        Args:
            target: Name of the main target
            target_mesh: Mesh to use as in-between
            in_between_weight: Weight value for the in-between (0-1)
        """
        if target in self.targets:
            target_index = self.targets.index(target)
            base_mesh = cmds.listConnections(f'{self.node}.outputGeometry[0]',
                                             source=False,
                                             destination=True)[0]
            cmds.blendShape(self.node, edit=True,
                            target=(base_mesh, target_index, target_mesh, in_between_weight))


class SkinCluster(Deformer):
    """Specialized skinCluster deformer."""

    def __init__(self, name: str, preset: Optional[Dict] = None, blend_value: float = 1.0):
        super(SkinCluster, self).__init__(name, preset, blend_value)
        self._influence_index = 0  # Track current influence

    @property
    def _weight_tokens(self) -> Dict[str, Union[str, int]]:
        """Override tokens for skinCluster paths."""
        count = self.vertex_count
        influences = cmds.skinCluster(self.node, q=True, influence=True) or []
        return {
            'node': self.node,
            'geoIndex': self.connection_index,
            'influenceIndex': self._influence_index,
            'influence': influences[self._influence_index] if influences else '',
            'weightRange': f'0:{count - 1}' if count > 0 else '0'
        }

    @property
    def _weight_attr_template(self) -> str:
        """Template for skinCluster weights."""
        return '{node}.weightList[{geoIndex}].weights[{weightRange}].{influence}'

    def set_influence(self, influence: Union[str, int]) -> None:
        """Set the current influence for weight operations.

        Args:
            influence: Influence name or index
        """
        influences = cmds.skinCluster(self.node, q=True, influence=True) or []
        if isinstance(influence, str):
            if influence in influences:
                self._influence_index = influences.index(influence)
        elif isinstance(influence, int):
            if 0 <= influence < len(influences):
                self._influence_index = influence

    @property
    def influences(self) -> List[str]:
        """Get list of influence objects (joints).

        Returns:
            List of influence object names
        """
        return cmds.skinCluster(self.node, q=True, influence=True) or []

    def get_influence_weights(self, influence: str) -> List[float]:
        """Get weights for a specific influence object.

        Args:
            influence: Name of the influence object

        Returns:
            List of weight values for this influence
        """
        if influence in self.influences:
            influence_index = self.influences.index(influence)
            return cmds.getAttr(f"{self.node}.weightList[0].weights[{influence_index}]")
        return []

    def add_influence(self, joint: str) -> None:
        """Add a new influence object to the skinCluster.

        Args:
            joint: Name of the joint to add
        """
        if cmds.objExists(joint):
            cmds.skinCluster(self.node, edit=True, addInfluence=joint, weight=0)


class Cluster(Deformer):
    """Specialized class for cluster deformers.

    Handles relative weights, handle transforms, and origins.
    """

    def __init__(self, name: str, preset: Optional[Dict] = None, blend_value: float = 1.0):
        super(Cluster, self).__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != "cluster":
            raise ValueError(f"Node '{name}' is not a cluster deformer")

    @property
    def handle(self) -> Optional[str]:
        """Get the cluster's handle transform.

        Returns:
            Name of the handle transform node
        """
        handles = cmds.listConnections(f"{self.node}.matrix", source=True, destination=False)
        return handles[0] if handles else None

    def set_origin(self, position: Tuple[float, float, float]) -> None:
        """Set the cluster's origin point.

        Args:
            position: (x, y, z) position for origin
        """
        handle = self.handle
        if handle:
            cmds.xform(handle, worldSpace=True, translation=position)

    def set_relative(self, state: bool) -> None:
        """Set whether the cluster uses relative or absolute mode.

        Args:
            state: True for relative mode, False for absolute
        """
        cmds.setAttr(f"{self.node}.relative", state)


class Wire(Deformer):
    """Specialized class for wire deformers.

    Handles wire curves, dropoff distances, and holder nodes.
    """

    def __init__(self, name: str, preset: Optional[Dict] = None, blend_value: float = 1.0):
        super(Wire, self).__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != "wire":
            raise ValueError(f"Node '{name}' is not a wire deformer")

    @property
    def wire_curves(self) -> List[str]:
        """Get the wire's curve objects.

        Returns:
            List of curve names
        """
        return cmds.wire(self.node, q=True, wire=True) or []

    def set_dropoff_distance(self, distance: float, curve_index: int = 0) -> None:
        """Set the dropoff distance for a wire curve.

        Args:
            distance: Dropoff distance value
            curve_index: Index of the wire curve
        """
        cmds.wire(self.node, edit=True, dropoffDistance=distance)


class SoftMod(Deformer):
    """Specialized class for softMod deformers.

    Handles falloff radius, center point, and falloff curve.
    """

    def __init__(self, name: str, preset: Optional[Dict] = None, blend_value: float = 1.0):
        super(SoftMod, self).__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != "softMod":
            raise ValueError(f"Node '{name}' is not a softMod deformer")

    def set_falloff_radius(self, radius: float) -> None:
        """Set the falloff radius.

        Args:
            radius: Radius value
        """
        cmds.setAttr(f"{self.node}.falloffRadius", radius)

    def set_falloff_curve(self,
                          values: List[Tuple[float, float]],
                          curve_type: Literal['spline', 'linear'] = 'spline') -> None:
        """Set the falloff curve shape.

        Args:
            values: List of (position, value) points
            curve_type: Type of curve interpolation
        """
        # Create a ramp attribute if it doesn't exist
        if not cmds.attributeQuery("falloffCurve", node=self.node, exists=True):
            cmds.addAttr(self.node, ln="falloffCurve", at="ramp")

        # Set the curve points
        ramp = f"{self.node}.falloffCurve"
        for i, (pos, val) in enumerate(values):
            cmds.setAttr(f"{ramp}[{i}].ramp_Position", pos)
            cmds.setAttr(f"{ramp}[{i}].ramp_FloatValue", val)
            if curve_type == 'linear':
                cmds.setAttr(f"{ramp}[{i}].ramp_Interp", 1)

