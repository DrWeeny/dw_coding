print(0)
from dw_maya.dw_paint.core.cache import MeshDataCache, MeshCache
# Create a global instance for general use
mesh_cache = MeshDataCache()

print(1)
# Mesh data operations
from dw_maya.dw_paint.core.mesh_data import (
    MeshData,
    MeshDataFactory,
    get_closest_vertex,
    get_vertex_shell,
    get_connected_vertices,
    find_vertex_pairs,

)
print(2)
# Weight operations
from dw_maya.dw_paint.core.weights import (
    WeightData,
    WeightDataFactory,
    WeightList,
    WeightArray,
    blend_weight_lists,
    modify_weights
)
print(3)
# Vector operations
from dw_maya.dw_paint.core.vectors import (
    VectorUtils,
    MayaVectorUtils,
    VectorDirection,
    Vector3D
)
print(4)
# Interpolation operations
from dw_maya.dw_paint.core.interpolation import (
    InterpolationSettings,
    WeightInterpolator,
)
print(5)
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