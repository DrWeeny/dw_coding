# utils/transfer.py
"""Nearest-neighbour weight transfer between point clouds.

Supports an optional *radius* to blend contributions from multiple source
points within a search sphere (IDW — Inverse Distance Weighting), and an
optional *falloff* that modulates the influence by normalised distance.

Backend priority:
    1. ``scipy.spatial.KDTree``  — fast, C-extension, O(n log n) build.
    2. Pure numpy brute-force   — always available, O(n·m) query.

Usage example::

    from TechArtsSandbox.abi.maya.paint_utils.utils.transfer import transfer_weights

    new_weights = transfer_weights(
        src_positions=[[0,0,0], [1,0,0]],
        src_weights=[0.0, 1.0],
        tgt_positions=[[0.5, 0, 0]],
        radius=0.8,
        falloff='linear',
    )
    # → [0.5]  (blended halfway between the two source points)
"""

from __future__ import annotations

from typing import List, Optional, Union

import numpy as np

from dw_maya.dw_compat import Literal

from dw_maya.dw_paint.utils.falloff import FalloffCurve

from dw_logger import get_logger
logger = get_logger()

# ── scipy availability ────────────────────────────────────────────────────────
try:
    from scipy.spatial import KDTree as _ScipyKDTree
    _HAS_SCIPY = True
    logger.debug("transfer: scipy KDTree available")
except ImportError:
    _HAS_SCIPY = False
    logger.debug("transfer: scipy not found — using numpy brute-force fallback")

# Type aliases
PositionList = Union[List[List[float]], np.ndarray]
WeightList   = Union[List[float], np.ndarray]
FalloffType  = Literal["linear", "quadratic", "smooth", "smooth2", "gaussian", "sine", "exponential"]


# ── internal helpers ──────────────────────────────────────────────────────────

def _to_float64(arr: PositionList) -> np.ndarray:
    """Ensure *arr* is a 2-D float64 numpy array of shape (N, 3)."""
    a = np.asarray(arr, dtype=np.float64)
    if a.ndim == 1:
        a = a.reshape(-1, 3)
    if a.ndim != 2 or a.shape[1] != 3:
        raise ValueError(
            f"Position array must be shape (N, 3), got {a.shape}"
        )
    return a


def _nn_scipy(src_pos: np.ndarray, tgt_pos: np.ndarray) -> np.ndarray:
    """Nearest-neighbour indices via scipy KDTree."""
    tree = _ScipyKDTree(src_pos)
    _, idx = tree.query(tgt_pos, workers=-1)
    return idx


def _nn_numpy(src_pos: np.ndarray, tgt_pos: np.ndarray) -> np.ndarray:
    """Nearest-neighbour indices via numpy brute-force."""
    idx = np.array([
        int(np.argmin(np.sum((src_pos - tp) ** 2, axis=1)))
        for tp in tgt_pos
    ])
    return idx


def _radius_scipy(
    src_pos: np.ndarray,
    tgt_pos: np.ndarray,
    src_weights: np.ndarray,
    radius: float,
    falloff_curve: FalloffCurve,
    nn_fallback_idx: np.ndarray,
) -> np.ndarray:
    """IDW blend using scipy KDTree radius search."""
    tree = _ScipyKDTree(src_pos)
    result = np.empty(len(tgt_pos), dtype=np.float64)

    for i, tp in enumerate(tgt_pos):
        neighbour_idx = tree.query_ball_point(tp, r=radius)
        if not neighbour_idx:
            # No point within radius — fall back to nearest neighbour
            result[i] = src_weights[nn_fallback_idx[i]]
            continue

        neighbour_idx = np.asarray(neighbour_idx, dtype=int)
        dists = np.linalg.norm(src_pos[neighbour_idx] - tp, axis=1)
        norm_dists = np.clip(dists / radius, 0.0, 1.0)

        # Influence = (1 - falloff(normalised_distance)); closest → most weight
        influence = 1.0 - falloff_curve.evaluate(norm_dists).astype(np.float64)
        influence = np.clip(influence, 0.0, 1.0)
        total = influence.sum()

        if total < 1e-12:
            result[i] = src_weights[nn_fallback_idx[i]]
        else:
            result[i] = np.dot(influence, src_weights[neighbour_idx]) / total

    return result


def _radius_numpy(
    src_pos: np.ndarray,
    tgt_pos: np.ndarray,
    src_weights: np.ndarray,
    radius: float,
    falloff_curve: FalloffCurve,
    nn_fallback_idx: np.ndarray,
) -> np.ndarray:
    """IDW blend using numpy brute-force radius search."""
    result = np.empty(len(tgt_pos), dtype=np.float64)
    r2 = radius * radius

    for i, tp in enumerate(tgt_pos):
        sq_dists = np.sum((src_pos - tp) ** 2, axis=1)
        mask = sq_dists <= r2
        if not np.any(mask):
            result[i] = src_weights[nn_fallback_idx[i]]
            continue

        dists = np.sqrt(sq_dists[mask])
        norm_dists = np.clip(dists / radius, 0.0, 1.0)
        influence = 1.0 - falloff_curve.evaluate(norm_dists).astype(np.float64)
        influence = np.clip(influence, 0.0, 1.0)
        total = influence.sum()

        if total < 1e-12:
            result[i] = src_weights[nn_fallback_idx[i]]
        else:
            result[i] = np.dot(influence, src_weights[mask]) / total

    return result


# ── public API ────────────────────────────────────────────────────────────────

def transfer_weights(
                        src_positions: PositionList,
                        src_weights: WeightList,
                        tgt_positions: PositionList,
                        radius: Optional[float] = None,
                        falloff: FalloffType = "linear",
                        clamp: bool = True,
                        clamp_min: float = 0.0,
                        clamp_max: float = 1.0,) -> List[float]:
    """Transfer weights from a source point cloud to a target point cloud.

    For each target vertex the function finds the closest source vertex (or
    the set of source vertices within *radius*) and returns an interpolated
    weight.

    Args:
        src_positions: World-space XYZ positions of the source vertices —
                       shape ``(N, 3)`` as a nested list or numpy array.
        src_weights:   Per-vertex weights for the source — length ``N``.
        tgt_positions: World-space XYZ positions of the target vertices —
                       shape ``(M, 3)``.
        radius:        If given (> 0), blend all source vertices within this
                       world-space radius using Inverse Distance Weighting
                       modulated by *falloff*.  When ``None`` (default) a
                       strict nearest-neighbour lookup is performed.
        falloff:       Falloff curve applied to normalised distance within the
                       radius.  One of ``'linear'``, ``'quadratic'``,
                       ``'smooth'``, ``'smooth2'``, ``'gaussian'``,
                       ``'sine'``, ``'exponential'``.  Only used when
                       *radius* is set.
        clamp:         Clamp result weights to ``[clamp_min, clamp_max]``.
        clamp_min:     Lower clamp bound (default ``0.0``).
        clamp_max:     Upper clamp bound (default ``1.0``).

    Returns:
        List of ``M`` floats — the transferred weights for each target vertex.

    Raises:
        ValueError: When position arrays are not shape (N, 3) / (M, 3), or
                    when ``src_positions`` and ``src_weights`` have different
                    lengths.

    Example::

        # Nearest-neighbour (no radius)
        result = transfer_weights(src_pos, src_w, tgt_pos)

        # Blended within a 5-unit radius with smooth falloff
        result = transfer_weights(src_pos, src_w, tgt_pos,
                                  radius=5.0, falloff='smooth')
    """
    # ── validation ────────────────────────────────────────────────────────────
    src_pos = _to_float64(src_positions)
    tgt_pos = _to_float64(tgt_positions)
    src_arr = np.asarray(src_weights, dtype=np.float64)

    if src_arr.ndim != 1:
        raise ValueError(
            f"src_weights must be a 1-D array, got shape {src_arr.shape}"
        )
    if len(src_pos) != len(src_arr):
        raise ValueError(
            f"src_positions length ({len(src_pos)}) != src_weights length ({len(src_arr)})"
        )
    if len(tgt_pos) == 0:
        return []

    use_radius = radius is not None and radius > 0.0

    # ── nearest-neighbour index (always computed — needed as fallback) ─────────
    logger.debug(
        f"transfer_weights: src={len(src_pos)} pts, tgt={len(tgt_pos)} pts, "
        f"radius={radius}, falloff='{falloff}', backend={'scipy' if _HAS_SCIPY else 'numpy'}"
    )

    nn_idx = _nn_scipy(src_pos, tgt_pos) if _HAS_SCIPY else _nn_numpy(src_pos, tgt_pos)

    if not use_radius:
        # Pure nearest-neighbour
        result = src_arr[nn_idx]
    else:
        # Radius-based IDW
        falloff_curve = FalloffCurve(falloff)
        if _HAS_SCIPY:
            result = _radius_scipy(src_pos, tgt_pos, src_arr, radius, falloff_curve, nn_idx)
        else:
            result = _radius_numpy(src_pos, tgt_pos, src_arr, radius, falloff_curve, nn_idx)

    # ── clamp ─────────────────────────────────────────────────────────────────
    if clamp:
        result = np.clip(result, clamp_min, clamp_max)

    logger.debug(
        f"transfer_weights: done — result range [{result.min():.4f}, {result.max():.4f}]"
    )
    return result.tolist()

