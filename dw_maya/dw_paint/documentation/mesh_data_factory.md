# MeshData & MeshDataFactory — Reference Guide

> Module: `dw_maya.dw_paint_utils.core.mesh_data`  
> Cache backend: `dw_maya.dw_paint_utils.core.cache` (`MeshDataCache`)  
> Public re-export: `from dw_maya.dw_paint_utils.core import MeshDataFactory`

---

## 1. Purpose

Every tool that reads vertex positions, normals, neighbour topology, or vertex colors has
historically called Maya's API independently — creating a new `MSelectionList`, `MDagPath` and
`MFnMesh` on every call. For a mesh with 50 000 vertices hit ten times per stroke, that is ten
redundant round-trips into Maya's C++ layer.

`MeshData` + `MeshDataFactory` solves this by:

1. **Caching** vertex positions, neighbour maps and vertex count in a single `lru_cache`-backed
   store (`MeshDataCache`).
2. **Reusing** the `MDagPath` and `MFnMesh` objects as lazy properties — built once, reused
   until `refresh()` is called.
3. **Sharing** the same `MeshData` instance across all consumers (paint controller, deformer,
   vertex color alpha…) via the `MeshDataFactory` singleton registry.

---

## 2. Architecture overview

```
MeshDataCache  (cache.py)
│  lru_cache(maxsize=32) around _get_mesh_data_impl()
│  stores: vertex_positions (float32 ndarray), neighbors (dict), vertex_count (int)
│  auto-clears when memory > 50 MB or topology changes
│
└── mesh_cache  (global instance, created in core/__init__.py)
        │
        ▼
MeshData  (mesh_data.py)
│  __init__ pulls (positions, neighbors, vertex_count) from mesh_cache
│  lazy properties: _dag  →  MDagPath (cached)
│                   _fn_mesh  →  MFnMesh  (cached)
│  refresh()  →  invalidates _fn_mesh / _dag, re-calls mesh_cache
│
└── MeshDataFactory  (mesh_data.py)
        _instances: Dict[str, MeshData]  — one instance per mesh name
        .get(mesh_name)  →  create-or-return MeshData
        .clear()         →  drop all instances
```

---

## 3. Quick-start

### 3.1 Basic usage

```python
from dw_maya.dw_paint_utils.core import MeshDataFactory

md = MeshDataFactory.get('pSphere1')

# Vertex count (cached, no Maya call after first access)
print(md.vertex_count)   # e.g. 382

# Vertex positions — numpy float32 array, shape (N, 3)
positions = md.vertex_positions
print(positions[0])      # array([x, y, z], dtype=float32)

# Neighbour map — {vertex_id: [neighbour_ids, …]}
neighbours = md.neighbors
print(neighbours[0])     # [1, 20, 21, …]
```

### 3.2 OpenMaya API objects

`MeshData` exposes two cached API properties that avoid repeated `MSelectionList` construction:

```python
md = MeshDataFactory.get('pSphere1')

dag  = md._dag      # om.MDagPath  — use with iterators
fn   = md._fn_mesh  # om.MFnMesh   — use for read/write

# Example: read all vertex normals in one call
normals = fn.getVertexNormals(True)

# Example: create an edge iterator without rebuilding the dag path
import maya.api.OpenMaya as om2
edge_iter = om2.MItMeshEdge(dag)
```

> **Note:** `_dag` and `_fn_mesh` are name-prefixed with `_` to signal they are internal helpers,
> but they are intentionally accessible for performance-critical consumers.  
> Do not store them across undo/redo boundaries — call `md.refresh()` first.

### 3.3 Convenience methods

```python
md = MeshDataFactory.get('pSphere1')

# Bounding box
bb_min, bb_max = md.get_bounding_box()   # (ndarray, ndarray)

# Centre point
centre = md.get_center()                 # ndarray [x, y, z]

# Closest vertex to a world-space point
idx = md.get_closest_vertex((1.0, 2.0, 0.5))   # int

# Vertex normal (single vertex)
n = md.get_vertex_normal(42)             # ndarray [nx, ny, nz] or None

# All vertex normals at once
all_n = md.get_vertex_normals()          # ndarray (N, 3) or None

# Vertex colors (RGB only, from current colorSet)
colors = md.get_vertex_colors()          # ndarray (N, 3) or None

# Border edges
border = md.get_border_edges()           # List[int]

# Vertices of a specific edge
verts = md.get_edge_vertices(12)         # [v0, v1]
```

---

## 4. Module-level utilities

These functions live at module level and are re-exported by `core/__init__.py`.

### `get_connected_vertices(mesh, vertex_index)`

Returns the indices of all vertices directly connected (by an edge) to `vertex_index`.

```python
from dw_maya.dw_paint_utils.core import get_connected_vertices

neighbours = get_connected_vertices('pSphere1', 0)
# [1, 20, 380, 381]
```

> Uses `cmds.polyListComponentConversion` — convenient but slower than the cached
> `md.neighbors` map for bulk access.

### `get_vertex_shell(mesh, start_vertex)`

Flood-fills from `start_vertex` and returns all vertices in the same connected shell.

```python
from dw_maya.dw_paint_utils.core import get_vertex_shell

shell = get_vertex_shell('pSphere1', 0)
# [0, 1, 2, …, 381]   ← all vertices if the mesh is a single shell
```

### `find_vertex_pairs(positions, tolerance=0.001)`

Finds coincident vertex pairs within `tolerance`. Uses `scipy.spatial.KDTree` for O(n log n)
performance; falls back to a brute-force loop if scipy is unavailable.

```python
from dw_maya.dw_paint_utils.core import find_vertex_pairs

md = MeshDataFactory.get('pSphere1')
pairs = find_vertex_pairs(list(map(tuple, md.vertex_positions)), tolerance=0.001)
# {0: 381, 381: 0, …}
```

### `get_closest_vertex(point, positions)`

Module-level utility that finds the closest vertex to a world-space point. Uses numpy for
vectorised distance computation; falls back to `math.sqrt` on very old Maya without numpy.

```python
from dw_maya.dw_paint_utils.core import get_closest_vertex

idx = get_closest_vertex((1.0, 0.0, 0.0), list(map(tuple, md.vertex_positions)))
```

> Prefer `MeshData.get_closest_vertex()` when you already have a `MeshData` instance — it
> avoids converting positions back to a list.

---

## 5. Cache behaviour & invalidation

### 5.1 What is cached and where

| Data | Cache level | Reset trigger |
|---|---|---|
| `vertex_positions`, `neighbors`, `vertex_count` | `MeshDataCache` (lru_cache) | `mesh_cache.clear_cache()` or topology change detected by `check_cache_memory()` |
| `MDagPath`, `MFnMesh` | `MeshData` instance attributes | `MeshData.refresh()` |
| `MeshData` instance itself | `MeshDataFactory._instances` dict | `MeshDataFactory.clear()` |

### 5.2 Automatic invalidation

`MeshDataCache.check_cache_memory()` runs before every `get_mesh_data()` call and clears the
lru_cache automatically when either:

- Estimated memory usage exceeds **50 MB** (configurable via `MeshDataCache(memory_threshold_mb=…)`).
- The vertex count of the mesh has changed since the last cache entry (topology change).

### 5.3 Manual invalidation

```python
from dw_maya.dw_paint_utils.core import MeshDataFactory, mesh_cache

# --- After sculpting / editing mesh topology ---

# Option A: refresh a single MeshData instance (cheapest)
MeshDataFactory.get('pSphere1').refresh()

# Option B: drop all MeshData instances and the lru_cache (full reset)
MeshDataFactory.clear()
mesh_cache.clear_cache()

# --- After script finishes working on a mesh ---
# Not strictly necessary — the LRU eviction handles memory automatically.
```

### 5.4 Cache statistics

```python
stats = mesh_cache.get_stats()
# {
#   'hits': 47,
#   'misses': 3,
#   'current_size': 3,
#   'max_size': 32,
#   'memory_estimate': '~15MB (rough estimate)'
# }
```

---

## 6. Integration patterns

### 6.1 In a WeightSource / paint tool

`VertexColorSet` and `ChannelPaintController` follow this pattern:

```python
from dw_maya.dw_paint_utils.core import MeshDataFactory

class MyPaintTool:
    def __init__(self, mesh_name):
        self.mesh = mesh_name

    @property
    def _fn_mesh(self):
        """Reuse the cached MFnMesh — no repeated MSelectionList."""
        return MeshDataFactory.get(self.mesh)._fn_mesh

    def get_weights(self):
        colors = self._fn_mesh.getVertexColors('myColorSet')
        return [c.a for c in colors]

    def _build_neighbour_cache(self):
        """Delegate to MeshDataFactory — already built for this mesh."""
        md = MeshDataFactory.get(self.mesh)
        if md.neighbors:
            return md.neighbors
        # … fallback build and store back into md._neighbors
```

### 6.2 In a Deformer (vtx_count with lru_cache)

`Deformer.vtx_count` in `deformer_class.py` uses a separate module-level `lru_cache` rather than
`MeshDataFactory` because:

- The deformer queries the **shape** name (not the transform) via `cmds.deformer(query, geometry)`.
- NURBS curves need a completely different code path.
- The deformer can be used standalone without the paint system being imported.

```python
import functools
from maya import cmds

@functools.lru_cache(maxsize=256)
def _cached_poly_vtx_count(shape: str) -> int:
    result = cmds.polyEvaluate(shape, vertex=True)
    return result if isinstance(result, int) else 0

# Invalidate after topology changes:
# _cached_poly_vtx_count.cache_clear()
```

### 6.3 Sharing the neighbour map across tools

Both `AlphaPaintController` and any smooth operation can share the same neighbour map:

```python
md = MeshDataFactory.get('pSphere1')

# First tool builds it (written back to md._neighbors)
if not md.neighbors:
    # … build …
    md._neighbors = built_cache

# Second tool reads it for free
neighbours = md.neighbors   # already populated
```

---

## 7. `MeshDataFactory` API reference

```python
MeshDataFactory.get(mesh_name: str) -> MeshData
```
Returns the existing `MeshData` instance for `mesh_name`, creating one if it doesn't exist yet.
The instance is stored in `MeshDataFactory._instances`.

```python
MeshDataFactory.clear() -> None
```
Drops all cached `MeshData` instances. Does **not** clear the underlying `MeshDataCache` lru_cache
— call `mesh_cache.clear_cache()` separately if you also want to discard vertex positions and
neighbour maps.

---

## 8. `MeshData` property & method reference

| Member | Type | Description |
|---|---|---|
| `mesh_name` | `str` | The mesh name this instance was created for |
| `vertex_count` | `int` (property) | Total vertex count (from cache, 0 if not populated) |
| `vertex_positions` | `np.ndarray` (property) | Float32 array of shape `(N, 3)` in world space |
| `neighbors` | `Dict[int, List[int]]` (property) | Per-vertex adjacency map |
| `_dag` | `om.MDagPath` (property) | Cached dag path — built lazily, reset by `refresh()` |
| `_fn_mesh` | `om.MFnMesh` (property) | Cached function set — built lazily, reset by `refresh()` |
| `get_vertex_position(id)` | `ndarray \| None` | Single vertex position |
| `get_vertex_neighbors(id)` | `List[int]` | Adjacency list for one vertex |
| `get_bounding_box()` | `(ndarray, ndarray)` | `(min_point, max_point)` |
| `get_center()` | `ndarray` | Mean of all vertex positions |
| `get_closest_vertex(point)` | `int` | Nearest vertex index (numpy, vectorised) |
| `get_vertex_normal(id)` | `ndarray \| None` | Single averaged vertex normal |
| `get_vertex_normals()` | `ndarray \| None` | All vertex normals, shape `(N, 3)` |
| `get_vertex_colors()` | `ndarray \| None` | RGB colors from current colorSet, shape `(N, 3)` |
| `get_border_edges()` | `List[int]` | Edge indices on the mesh boundary |
| `get_edge_vertices(edge_idx)` | `List[int]` | The two vertex indices of an edge |
| `get_components(type)` | `List[str]` | All components of `'vtx'`, `'e'`, or `'f'` |
| `get_selected_components()` | `List[str]` | Currently selected components on this mesh |
| `refresh()` | `None` | Clears `_dag` / `_fn_mesh` and re-runs `mesh_cache` lookup |

---

## 9. Dependencies

| Package | Required | Notes |
|---|---|---|
| `maya.api.OpenMaya` | ✅ Always | Maya 2020+ |
| `numpy` | ✅ Always | Vertex positions stored as `float32` |
| `scipy.spatial.KDTree` | ⚠️ Optional | Used by `find_vertex_pairs` / `find_mirror_pairs`; brute-force fallback if absent |

---

## 10. Common pitfalls

### `MeshData.vertex_count` returns 0

The `vertex_count` property reads from `_vertex_count`, which is populated only if
`mesh_cache.get_mesh_data()` succeeded at construction time. If the mesh wasn't accessible
(e.g. a reference that hadn't loaded yet), the count stays 0.

```python
# Fix: force a refresh once the mesh is available
MeshDataFactory.get('myMesh').refresh()
```

### Stale `_fn_mesh` after undo/topology change

The `MFnMesh` object holds a C++ pointer that becomes invalid after topology changes or undo.
Always call `refresh()` if you know the mesh has been modified:

```python
# After cmds.polySubdivideFacet(...) or similar
MeshDataFactory.get('pSphere1').refresh()
_cached_poly_vtx_count.cache_clear()   # also clear deformer vtx cache if used
```

### `MeshDataFactory` instance persists across scene loads

`MeshDataFactory._instances` is a class-level dict — it survives `cmds.file(new=True)`.
Register a Maya scene-new/open callback to clear it:

```python
from maya import cmds
from dw_maya.dw_paint_utils.core import MeshDataFactory, mesh_cache

def _on_new_scene(*_):
    MeshDataFactory.clear()
    mesh_cache.clear_cache()

cmds.scriptJob(event=['NewSceneOpened', _on_new_scene])
cmds.scriptJob(event=['SceneOpened',    _on_new_scene])
```

