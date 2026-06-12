"""
picker.py
---------
One-shot viewport vertex-weight picker (eyedropper).

Maya's ``artAttrCtx -pickValue`` flag has no completion callback, so a
caller can't tell whether the user picked a value or pressed Escape without
polling (QTimer / scriptJob / mouse-enter tricks). This module sidesteps the
problem entirely: it swaps the active tool for a one-shot ``draggerContext``
and resolves the result synchronously inside Maya's own press callback —
the artisan picker is never involved.

Functions:
    pick_vertex_weight: Activate the eyedropper for a mesh + weight list.

Author: DrWeeny
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from maya import cmds
import maya.api.OpenMaya as om2
import maya.api.OpenMayaUI as omui2

from dw_maya.dw_paint.core.mesh_data import MeshDataFactory
from dw_logger import get_logger

logger = get_logger()

_CTX_NAME = '_dwWeightPickerCtx'
_MAX_RAY_DISTANCE = 1000000.0


def pick_vertex_weight(mesh_name: str,
                        weights: Sequence[float],
                        on_picked: Callable[[int, float], None],
                        on_cancel: Optional[Callable[[], None]] = None) -> None:
    """Activate a one-shot eyedropper for *mesh_name*'s vertex weights.

    Swaps the active tool for a crosshair ``draggerContext``. On the next
    left-click in a viewport, a ray is cast through the click point; if it
    hits *mesh_name*, the nearest vertex of the hit face is resolved and
    ``on_picked(vertex_index, weight)`` is called with the matching entry
    from *weights*. Any other click (other mouse buttons, or a miss) calls
    *on_cancel*. The previously active tool is restored in both cases.

    Args:
        mesh_name: Transform or shape name of the mesh to pick from.
        weights:   Per-vertex weights, indexed by vertex id (e.g. the result
                   of ``WeightSource.get_weights()``).
        on_picked: Called with ``(vertex_index, weight_value)`` on a hit.
        on_cancel: Called with no arguments on miss / non-left-click / error.
    """
    previous_ctx = cmds.currentCtx()

    def _restore() -> None:
        # Deferred: switching tools mid-press leaves the dragger context's
        # press/release cycle unfinished, so Maya swallows the next click.
        # Running setToolTo after this event has been fully processed avoids
        # that stuck state.
        def _do_restore() -> None:
            try:
                cmds.setToolTo(previous_ctx)
            except Exception as e:
                logger.debug(f"pick_vertex_weight: could not restore tool '{previous_ctx}': {e}")
        cmds.evalDeferred(_do_restore)

    def _on_press(*_args) -> None:
        button = cmds.draggerContext(_CTX_NAME, query=True, button=True)
        anchor = cmds.draggerContext(_CTX_NAME, query=True, anchorPoint=True)
        x, y = anchor[0], anchor[1]
        _restore()

        if button != 1:
            if on_cancel:
                on_cancel()
            return

        try:
            vtx_index = _closest_vertex_under_cursor(mesh_name, int(x), int(y))
        except Exception as e:
            logger.error(f"pick_vertex_weight: raycast on '{mesh_name}' failed: {e}")
            vtx_index = None

        if vtx_index is None or vtx_index >= len(weights):
            if on_cancel:
                on_cancel()
            return
        on_picked(vtx_index, weights[vtx_index])

    if not cmds.draggerContext(_CTX_NAME, exists=True):
        cmds.draggerContext(_CTX_NAME)
    cmds.draggerContext(_CTX_NAME, edit=True,
                         pressCommand=_on_press,
                         cursor='crossHair',
                         space='screen')
    cmds.setToolTo(_CTX_NAME)


def _closest_vertex_under_cursor(mesh_name: str, x: int, y: int) -> Optional[int]:
    """Raycast from screen point *(x, y)* and return the nearest vertex on *mesh_name*.

    Returns ``None`` when the ray misses the mesh.
    """
    view = omui2.M3dView.active3dView()
    ray_source = om2.MPoint()
    ray_direction = om2.MVector()
    view.viewToWorld(x, y, ray_source, ray_direction)

    fn_mesh = MeshDataFactory.get(mesh_name)._fn_mesh
    hit = fn_mesh.closestIntersection(
        om2.MFloatPoint(ray_source.x, ray_source.y, ray_source.z),
        om2.MFloatVector(ray_direction.x, ray_direction.y, ray_direction.z),
        om2.MSpace.kWorld, _MAX_RAY_DISTANCE, False,
    )
    if hit is None:
        return None

    hit_point = om2.MPoint(hit[0].x, hit[0].y, hit[0].z)
    hit_face = hit[2]

    best_id, best_dist = None, None
    for vid in fn_mesh.getPolygonVertices(hit_face):
        dist = (fn_mesh.getPoint(int(vid), om2.MSpace.kWorld) - hit_point).length()
        if best_dist is None or dist < best_dist:
            best_id, best_dist = int(vid), dist
    return best_id