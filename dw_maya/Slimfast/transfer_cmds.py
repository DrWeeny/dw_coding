"""Maya logic for the Maya Map Transfer widget (wgt_maya_transfer).

Snapshots every paintable weight map on a mesh into a self-contained,
JSON-serializable payload (weights + world vertex positions), so a storage
saved in one Maya session can be loaded in another and applied onto a new
target mesh - even when source and target have different topology.

Keeps zero Qt here so the UI stays a thin shell, mirroring how Slimfast's
``cmds.py`` holds the controller logic.

Features:
    - snapshot_mesh:        capture all maps of a mesh (offline payload)
    - list_target_maps:     resolve live WeightSources of a target mesh
    - copy_weights:         same-topology index copy
    - transfer_weights:     nearest-neighbour cross-topology transfer
    - save_storage/load_storage: JSON round-trip for cross-Maya exchange

Functions:
    selected_mesh, map_identity, get_world_positions, snapshot_mesh,
    list_target_maps, copy_weights, transfer_weights,
    save_storage, load_storage

Example::

    from dw_maya.Slimfast import transfer_cmds
    snap = transfer_cmds.snapshot_mesh('shirt_geo')
    transfer_cmds.save_storage('C:/tmp/shirt_maps.json', [snap])

Author:
    DrWeeny
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from maya import cmds

import dw_maya.dw_presets_io.dw_json as dw_json
from dw_logger import get_logger

logger = get_logger()

SCHEMA = "maya_map_transfer"
SCHEMA_VERSION = 1

# Deformer maps that are implicit (one per geometry) carry no meaningful map
# name, so the deformer node itself is the matching identity instead.
_IMPLICIT_MAP_NAMES = ("weightList", "baseWeights", "weights")


# ---------------------------------------------------------------------------
# Scene helpers
# ---------------------------------------------------------------------------

def selected_mesh() -> Optional[str]:
    """Return the first selected mesh transform (long name), or None."""
    for node in cmds.ls(selection=True, long=True) or []:
        if cmds.nodeType(node) == "mesh":
            parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
            return parents[0] if parents else node
        shapes = cmds.listRelatives(node,
                                    shapes=True,
                                    fullPath=True,
                                    type="mesh",
                                    noIntermediate=True) or []
        if shapes:
            return node
    return None


def selected_vertex_indices(mesh: str) -> List[int]:
    """Return the indices of *mesh* vertices in the current selection.

    Components belonging to other meshes are ignored, so a stray selection on
    another object never bleeds into the transfer.
    """
    shapes = cmds.listRelatives(mesh, shapes=True, fullPath=False) or []
    valid = {mesh.split("|")[-1]}
    valid.update(s.split("|")[-1] for s in shapes)

    verts = cmds.filterExpand(cmds.ls(selection=True),
                              selectionMask=31,
                              expand=True) or []
    indices: List[int] = []
    for comp in verts:
        if ".vtx[" not in comp:
            continue
        node = comp.split(".vtx[")[0].split("|")[-1]
        if node not in valid:
            continue
        indices.append(int(comp.split("[")[-1].rstrip("]")))
    return indices


def _mesh_shape(mesh: str) -> str:
    """Return the non-intermediate mesh shape for *mesh* (or *mesh* itself)."""
    if cmds.nodeType(mesh) == "mesh":
        return mesh
    shapes = cmds.listRelatives(mesh,
                                shapes=True,
                                fullPath=True,
                                type="mesh",
                                noIntermediate=True) or []
    return shapes[0] if shapes else mesh


def get_world_positions(mesh: str) -> List[List[float]]:
    """Return per-vertex world-space positions of *mesh* as nested lists."""
    import maya.api.OpenMaya as om2
    sel = om2.MSelectionList()
    sel.add(_mesh_shape(mesh))
    fn = om2.MFnMesh(sel.getDagPath(0))
    pts = fn.getPoints(om2.MSpace.kWorld)
    return [[round(p.x, 5), round(p.y, 5), round(p.z, 5)] for p in pts]


def map_identity(node_name: str, node_type: str, map_name: str) -> str:
    """Return the name used to match a source map to a target map.

    Nucleus maps are already uniquely named (thickness, bend, ...). Implicit
    deformer maps (``weightList``) are identified by their deformer node, so a
    cluster and a blendShape on the same mesh stay distinct.
    """
    short = node_name.split("|")[-1]
    if node_type in ("nCloth", "nRigid"):
        return map_name
    if map_name in _IMPLICIT_MAP_NAMES:
        return short
    return map_name


# ---------------------------------------------------------------------------
# Snapshot (offline payload) / live target resolution
# ---------------------------------------------------------------------------

def _resolve_sources(mesh: str) -> List["Any"]:
    """Resolve every WeightSource on *mesh*, per backend.

    Each backend (deformer / nucleus / vtxColor) is resolved independently so
    a failure in one (e.g. a mesh with no deformer history) does not hide the
    maps exposed by the others.
    """
    from dw_maya.dw_paint.weight_source import resolve_weight_sources

    sources: List["Any"] = []
    for mode in ("deformer", "nucleus", "vtxColor"):
        try:
            sources.extend(resolve_weight_sources(mesh, mode=mode))
        except Exception as e:
            logger.warning(f"resolve_weight_sources({mode}) failed on '{mesh}': {e}")
    return sources


def snapshot_mesh(mesh: str) -> Dict[str, Any]:
    """Capture every paintable weight map on *mesh* into a JSON-ready dict.

    Args:
        mesh: Mesh transform (or shape) name.

    Returns:
        Dict with ``mesh``, ``vtx_count``, ``vtx_positions`` (world space,
        shared by all maps) and a ``maps`` list, each entry holding
        ``node_name`` / ``node_type`` / ``map_name`` / ``key`` / ``weights``.
    """
    positions = get_world_positions(mesh)
    maps: List[Dict[str, Any]] = []

    for src in _resolve_sources(mesh):
        node_name = src.node_name
        try:
            node_type = cmds.nodeType(node_name)
        except Exception:
            node_type = "unknown"
        try:
            available = src.available_maps()
        except Exception as e:
            logger.warning(f"snapshot_mesh: available_maps failed on '{node_name}': {e}")
            continue

        for map_name in available:
            try:
                src.use_map(map_name)
                weights = src.get_weights()
            except Exception as e:
                logger.warning(f"snapshot_mesh: read '{node_name}.{map_name}' failed: {e}")
                continue
            maps.append({
                "node_name": node_name.split("|")[-1],
                "node_type": node_type,
                "map_name": map_name,
                "key": map_identity(node_name, node_type, map_name),
                "weights": [round(float(w), 6) for w in weights],
            })

    return {
        "mesh": mesh.split("|")[-1],
        "vtx_count": len(positions),
        "vtx_positions": positions,
        "maps": maps,
    }


def list_target_maps(mesh: str) -> List[Dict[str, Any]]:
    """Resolve the live weight maps of a target mesh.

    Returns a list of dicts each carrying the live ``source`` WeightSource
    plus its ``node_name`` / ``node_type`` / ``map_name`` / ``key`` so the UI
    can match and later write weights back.
    """
    out: List[Dict[str, Any]] = []
    for src in _resolve_sources(mesh):
        node_name = src.node_name
        try:
            node_type = cmds.nodeType(node_name)
        except Exception:
            node_type = "unknown"
        try:
            available = src.available_maps()
        except Exception as e:
            logger.warning(f"list_target_maps: available_maps failed on '{node_name}': {e}")
            continue
        for map_name in available:
            out.append({
                "source": src,
                "node_name": node_name,
                "node_type": node_type,
                "map_name": map_name,
                "key": map_identity(node_name, node_type, map_name),
            })
    return out


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def copy_weights(src_weights: List[float],
                 target_source: "Any",
                 target_map: Optional[str] = None,
                 mask: Optional[List[int]] = None) -> int:
    """Index-for-index copy onto a same-topology target. Returns vtx count.

    Args:
        mask: When given, only these target vertex indices are overwritten;
              every other vertex keeps its original weight.

    Raises:
        ValueError: when source and target vertex counts differ.
    """
    if target_map:
        target_source.use_map(target_map)
    n = target_source.vtx_count
    if len(src_weights) != n:
        raise ValueError(
            f"Vertex count mismatch: source {len(src_weights)} vs target {n}. "
            f"Use 'Transfer (nearest)' for different topology."
        )
    if mask:
        result = target_source.get_weights()
        for i in mask:
            if 0 <= i < n:
                result[i] = float(src_weights[i])
        target_source.set_weights(result)
    else:
        target_source.set_weights([float(w) for w in src_weights])
    return n


def transfer_weights(src_weights: List[float],
                     src_positions: List[List[float]],
                     target_source: "Any",
                     target_map: Optional[str] = None,
                     max_distance: Optional[float] = None,
                     preserve_unmapped: bool = True,
                     mask: Optional[List[int]] = None) -> int:
    """Nearest-neighbour cross-topology transfer onto *target_source*.

    Matches every target vertex to the closest stored source vertex in world
    space, so source and target may differ in topology. Returns the number of
    target vertices written.

    Args:
        src_weights:       Per-vertex weights captured from the source map.
        src_positions:     World positions captured alongside ``src_weights``.
        target_source:     Live WeightSource to receive the weights.
        target_map:        Map to activate on the target before writing.
        max_distance:      Optional clamp; vertices farther than this keep their
                           original weight (or 0 when ``preserve_unmapped`` is
                           False) instead of pulling from the source.
        preserve_unmapped: Keep original target weights for out-of-range
                           vertices when ``max_distance`` is set.
        mask:              When given, only these target vertex indices are
                           written; every other vertex keeps its original
                           weight.
    """
    import numpy as np

    if target_map:
        target_source.use_map(target_map)

    src_pos = np.array(src_positions, dtype=np.float64)
    tgt_pos = np.array(get_world_positions(target_source.mesh_name), dtype=np.float64)
    src_arr = np.array(src_weights, dtype=np.float64)
    tgt_arr = np.array(target_source.get_weights(), dtype=np.float64)

    try:
        from scipy.spatial import cKDTree
        distances, nn_idx = cKDTree(src_pos).query(tgt_pos)
    except ImportError:
        nn_idx = np.empty(len(tgt_pos), dtype=int)
        distances = np.empty(len(tgt_pos), dtype=np.float64)
        for i, tp in enumerate(tgt_pos):
            d = np.sqrt(((src_pos - tp) ** 2).sum(axis=1))
            j = int(np.argmin(d))
            nn_idx[i] = j
            distances[i] = d[j]

    if max_distance is not None:
        new_weights = tgt_arr.copy()
        within = distances <= max_distance
        new_weights[within] = src_arr[nn_idx[within]]
        if not preserve_unmapped:
            new_weights[~within] = 0.0
    else:
        new_weights = src_arr[nn_idx]

    if mask:
        masked = tgt_arr.copy()
        valid = [i for i in mask if 0 <= i < len(masked)]
        if valid:
            idx = np.array(valid, dtype=int)
            masked[idx] = new_weights[idx]
        new_weights = masked

    target_source.set_weights(new_weights.tolist())
    return int(len(new_weights))


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------

def save_storage(path: str, meshes: List[Dict[str, Any]]) -> bool:
    """Write a storage (list of snapshot dicts) to *path*."""
    data = {"schema": SCHEMA, "version": SCHEMA_VERSION, "meshes": meshes}
    return dw_json.save_json(path, data)


def load_storage(path: str) -> Optional[Dict[str, Any]]:
    """Load a storage file, validating its schema. Returns None on mismatch."""
    data = dw_json.load_json(path)
    if not data or data.get("schema") != SCHEMA:
        logger.warning(f"load_storage: '{path}' is not a {SCHEMA} file.")
        return None
    return data