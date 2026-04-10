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
- Backend-agnostic WeightSource protocol (deformers + nucleus)

Example usage:
    >>> from dw_paint import flood_weights, mirror_weights
    >>> # Flood weights on selected vertices
    >>> new_weights = flood_weights(mesh_name, weights, value=1.0)
    >>> # Mirror weights across X axis
    >>> mirrored = mirror_weights(mesh_name, weights, axis='x')
    >>> # Unified WeightSource API
    >>> from dw_paint import resolve_weight_sources, apply_operation
    >>> sources = resolve_weight_sources('pSphere1')
    >>> apply_operation(sources[0], 'smooth', iterations=3)
"""

# Protocol — zero Maya dependencies, safe everywhere
from dw_maya.dw_paint.protocol import (
    WeightSource,
    WeightList,
)

# Core functionality
from dw_maya.dw_paint.core import (
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
    smooth_weights,
    select_vtx_info_on_mesh,

    # Vector operations
    VectorUtils,
    MayaVectorUtils,
    VectorDirection,
    Vector3D,
    normalize_vector,

    # Interpolation
    InterpolationSettings,
    WeightInterpolator,
)

# Operations
from dw_maya.dw_paint.operations import (
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
from dw_maya.dw_paint.utils import (
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
    remap_weights,

    #Maya Tools
    get_current_artisan_map,
    open_tools_window
)

# Cross-domain WeightSource utilities (requires deformers + nucleus — lazy-loaded)
from dw_maya.dw_paint.weight_source import (
    resolve_weight_sources,
    paint_weight_source,
    apply_operation,
)

__all__ = [
    # Core
    'MeshCache', 'MeshDataCache', 'mesh_cache',
    'MeshData', 'MeshDataFactory', 'get_vertex_shell', 'get_connected_vertices', 'find_vertex_pairs',
    'WeightData', 'WeightDataFactory', 'WeightList', 'WeightArray', 'blend_weight_lists', 'modify_weights', 'get_closest_vertex',
    'smooth_weights',
    'select_vtx_info_on_mesh',
    'VectorUtils', 'MayaVectorUtils', 'VectorDirection', 'Vector3D',
    'normalize_vector',
    'InterpolationSettings', 'WeightInterpolator',

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
    'mel_array_to_python', 'remap_weights', 'get_current_artisan_map', 'open_tools_window',

    # Protocol
    'WeightSource', 'WeightList',

    # Cross-domain
    'resolve_weight_sources', 'paint_weight_source', 'apply_operation',
]

# Version information
__version__ = '1.0.0'
__author__ = 'DrWeeny'
