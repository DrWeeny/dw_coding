from .cache import MeshDataCache, MeshCache
# Create a global instance for general use
mesh_cache = MeshDataCache()

# Mesh data operations
from .mesh_data import (
    MeshData,
    MeshDataFactory,
    get_closest_vertex,
    get_vertex_shell,
    get_connected_vertices,
    find_vertex_pairs,

)

# Weight operations
from .weights import (
    WeightData,
    WeightDataFactory,
    WeightList,
    WeightArray,
    blend_weight_lists,
    modify_weights
)

# Vector operations
from .vectors import (
    VectorUtils,
    MayaVectorUtils,
    VectorDirection,
    Vector3D
)

# Interpolation operations
from .interpolation import (
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

    # Vectors
    'VectorUtils',
    'MayaVectorUtils',
    'VectorDirection',
    'Vector3D',

    # Interpolation
    'InterpolationSettings',
    'WeightInterpolator',
]