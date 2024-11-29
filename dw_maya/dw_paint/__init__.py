"""
dw_paint - Maya Weight Painting Utilities

A comprehensive toolkit for handling vertex weights in Maya, providing:
- Weight manipulation (flood, mirror, radial, directional)
- Mesh data caching and optimization
- Vector operations
- Weight interpolation
- Validation utilities
- Conversion utilities
- Falloff calculations

Example usage:
    >>> from dw_paint import flood_weights, mirror_weights
    >>> # Flood weights on selected vertices
    >>> new_weights = flood_weights(mesh_name, weights, value=1.0)
    >>> # Mirror weights across X axis
    >>> mirrored = mirror_weights(mesh_name, weights, axis='x')
"""

# Core functionality
from .core import (
    # Cache system
    MeshCache,
    MeshDataCache,
    mesh_cache,

    # Mesh operations
    MeshData,
    MeshDataFactory,
    get_vertex_shell,
    get_connected_vertices,
    find_vertex_pairs,
    get_closest_vertex,

    # Weight operations
    WeightData,
    WeightDataFactory,
    WeightList,
    WeightArray,
    blend_weight_lists,
    modify_weights,

    # Vector operations
    VectorUtils,
    MayaVectorUtils,
    VectorDirection,
    Vector3D,

    # Interpolation
    InterpolationSettings,
    WeightInterpolator,
    interpolate_vertex_map
)

# Operations
from .operations import (
    # Flood operations
    FloodOperation,
    flood_weights,

    # Mirror operations
    MirrorOperation,
    mirror_weights,

    # Radial operations
    RadialOperation,
    set_radial_weights,

    # Directional operations
    DirectionalOperation,
    set_directional_weights
)

# Utility functions
from .utils import (
    # MEL based utils
    open_tools_window,

    # Validation
    validate_operation_type,
    validate_weight_value,
    validate_mesh,
    validate_component_mask,
    validate_component_name,
    validate_falloff_type,
    validate_axis,
    compare_two_nodes_list,
    guess_if_component_sel,

    # Falloff
    FalloffCurve,
    FalloffFunction,
    CustomFalloff,
    apply_falloff,

    # Conversion
    to_weight_list,
    to_numpy_array,
    convert_range_to_indices,
    indices_to_range_str,
    normalize_weights,
    component_to_mesh_and_index,
    mel_array_to_python,
    remap_weights
)

__all__ = [
    # Core
    'MeshCache', 'MeshDataCache', 'mesh_cache',
    'MeshData', 'MeshDataFactory', 'get_vertex_shell', 'get_connected_vertices', 'find_vertex_pairs',
    'WeightData', 'WeightDataFactory', 'WeightList', 'WeightArray', 'blend_weight_lists', 'modify_weights', 'get_closest_vertex',
    'VectorUtils', 'MayaVectorUtils', 'VectorDirection', 'Vector3D',
    'InterpolationSettings', 'WeightInterpolator', 'interpolate_vertex_map',

    # Operations
    'FloodOperation', 'flood_weights',
    'MirrorOperation', 'mirror_weights',
    'RadialOperation', 'set_radial_weights',
    'DirectionalOperation', 'set_directional_weights',

    # Utils
    'open_tools_window',
    'validate_operation_type', 'validate_weight_value', 'validate_mesh',
    'validate_component_mask', 'validate_component_name', 'validate_falloff_type',
    'validate_axis','compare_two_nodes_list','guess_if_component_sel',
    'FalloffCurve', 'FalloffFunction', 'CustomFalloff', 'apply_falloff',
    'to_weight_list', 'to_numpy_array', 'convert_range_to_indices',
    'indices_to_range_str', 'normalize_weights', 'component_to_mesh_and_index',
    'mel_array_to_python', 'remap_weights'
]

# Version information
__version__ = '1.0.0'
__author__ = 'DrWee'
