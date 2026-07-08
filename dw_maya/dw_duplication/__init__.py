"""Maya object duplication package providing flexible ways to duplicate objects.

This package provides multiple approaches for duplicating Maya objects with
different use cases and requirements:

Core Functions:
    cleanDuplication: Sanitizes duplicated objects by removing history, layers, 
                     shaders and freezing transforms
    dupMesh: Standard duplication with unique naming and sanitization
    freshDuplicate: Creates clean duplicates by copying shape data only
    outmesh: Advanced component duplication supporting partial mesh copying

Animation/Cache Functions:
    dupAnim: Duplicates animated objects with baked geometry cache
    dupWCache: Duplicates objects while preserving existing caches

Specialized Functions:
    dupWithPivotAdjustment: Duplicates with customized pivot placement
    instanceObjects: Creates Maya instances instead of full duplicates
    duplicate_nodes: Hybrid duplicate keeping the incoming graph - native
                     cmds.duplicate for the content (full shape fidelity),
                     preset replay for inputs and driving constraints
    mn_duplicate_nodes: Same graph replay, but the copies themselves are
                     rebuilt purely from their preset entry (round-trip
                     check; mesh-only geometry)

Common Use Cases:
    - Clean mesh duplication: dupMesh()
    - Animated mesh duplication: dupAnim() 
    - Component duplication: outmesh()
    - Cached mesh duplication: dupWCache()
    - Instance creation: instanceObjects()

Example Usage:
    >>> from dw_maya import dw_duplication as dwd
    >>> # Duplicate and clean meshes
    >>> new_meshes = dwd.dupMesh(['pCube1', 'pSphere1'])
    >>> # Duplicate with animation cache
    >>> cached = dwd.dupAnim(['character_mesh'])
    >>> # Duplicate components
    >>> faces = dwd.outmesh(['pCube1.f[1:10]'])
"""

from .dw_clean_duplication import cleanDuplication
from .dw_dup_mesh import dupMesh
from .dw_fresh_dup import freshDuplicate
from .dw_dup_bake import dupAnim
from .dw_outmesh import outmesh
from .dw_with_cache import dupWCache
from .dw_dup_change_pivot import dupWithPivotAdjustment
from .dw_dup_preset import duplicate_nodes, mn_duplicate_nodes

__all__ = ['cleanDuplication', 'dupMesh', 'freshDuplicate', 'dupAnim',
           'outmesh', 'dupWCache', 'dupWithPivotAdjustment',
           'duplicate_nodes', 'mn_duplicate_nodes']