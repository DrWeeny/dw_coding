from dw_maya.dw_paint.core.cache import MeshDataCache, MeshCache
# Create a global instance for general use
mesh_cache = MeshDataCache()

# Mesh data operations
from dw_maya.dw_paint.core.mesh_data import (
    MeshData,
    MeshDataFactory,
    get_closest_vertex,
    get_vertex_shell,
    get_connected_vertices,
    find_vertex_pairs,

)
# Weight operations
from dw_maya.dw_paint.core.weights import (
    WeightData,
    WeightDataFactory,
    WeightList,
    WeightArray,
    blend_weight_lists,
    modify_weights,
    smooth_weights,
    select_vtx_info_on_mesh,
)
# Vector operations
from dw_maya.dw_paint.core.vectors import (
    VectorUtils,
    MayaVectorUtils,
    VectorDirection,
    Vector3D,
    normalize_vector,
)
# Interpolation operations
from dw_maya.dw_paint.core.interpolation import (
    InterpolationSettings,
    WeightInterpolator,
)
__all__ = [
    # Cache
    'MeshCache',
    'MeshDataCache',
    'mesh_cache',

    # Mesh
    'MeshData',
    'MeshDataFactory',
    'get_vertex_shell',
    'get_connected_vertices',
    'find_vertex_pairs',
    'get_closest_vertex',

    # Weights
    'WeightData',
    'WeightDataFactory',
    'WeightList',
    'WeightArray',
    'blend_weight_lists',
    'modify_weights',
    'smooth_weights',
    'select_vtx_info_on_mesh',

    # Vectors
    'VectorUtils',
    'MayaVectorUtils',
    'VectorDirection',
    'Vector3D',
    'normalize_vector',

    # Interpolation
    'InterpolationSettings',
    'WeightInterpolator',
]