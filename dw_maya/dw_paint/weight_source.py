"""Cross-domain WeightMap utilities for dw_paint.

Provides the functions that span both the deformer and nucleus backends,
keeping the UI and operation callers completely backend-agnostic.

All functions accept any :class:`~dw_maya.dw_paint.protocol.WeightMap`
instance — no ``isinstance`` branching needed in calling code.

Functions:
    resolve_weight_sources: Return all WeightMap objects on a mesh.
    paint_weight_source:    Open the right artisan tool for any WeightMap.
    apply_operation:        Apply a named weight operation to any WeightMap.

Example::

    from dw_maya.dw_paint.weight_source import (
        resolve_weight_sources,
        paint_weight_source,
        apply_operation,
    )

    sources = resolve_weight_sources('pSphere1')
    # Each source is a WeightMap — no type checks needed

    sources[0].use_map('thickness')          # nucleus node
    sources[1].use_map('weightList')         # deformer

    paint_weight_source(sources[0])
    apply_operation(sources[0], 'smooth', iterations=3)

Author: DrWeeny
"""

from __future__ import annotations

from typing import Dict, List, Optional

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal

from maya import cmds, mel

import dw_maya.dw_paint.core
import dw_maya.dw_paint.operations
from dw_maya.dw_paint.protocol import WeightSource, WeightList
from dw_logger import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Artisan attribute map — used by _paint_deformer
# ---------------------------------------------------------------------------

_ARTISAN_ATTRS: Dict[str, str] = {
    'cluster':    'cluster.{node}.weights',
    'softMod':    'softMod.{node}.weights',
    'blendShape': 'blendShape.{node}.baseWeights',
    'deltaMush':  'deltaMush.{node}.weights',
    'wire':       'wire.{node}.weights',
    'tension':    'tension.{node}.weights',
    'proximity':  'proximity.{node}.weights',
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_weight_sources(
        mesh: str,
        mode: Literal['all', 'deformer', 'nucleus'] = 'all'
) -> List[WeightSource]:
    """Return all WeightMap objects available on a mesh.

    Queries both standard deformers (via history) and nucleus per-vertex
    maps so the UI never needs to handle the two backends separately.

    Args:
        mesh: Mesh transform name.
        mode: Which backends to include:
              ``'all'``      — deformers + nucleus maps (default)
              ``'deformer'`` — standard Maya deformers only
              ``'nucleus'``  — nCloth/nRigid per-vertex maps only

    Returns:
        List of :class:`~dw_maya.dw_paint.protocol.WeightMap` instances:
        deformers first, then nucleus nodes.  Each source has no active
        map yet — call :meth:`~WeightMap.use_map` or rely on auto-resolve.

    Example::

        >>> resolve_weight_sources('pSphere1')
        [<Cluster ...>, <BlendShape ...>, <NClothMap ...>]
    """
    from dw_maya.dw_deformers.dw_core import listDeformers
    from dw_maya.dw_deformers.dw_deformer_class import make_deformer
    from dw_maya.dw_nucleus_utils.dw_core import get_nucx_node
    from dw_maya.dw_nucleus_utils.dw_ncloth_class import NClothMap

    sources: List[WeightSource] = []

    if mode in ('all', 'deformer'):
        for node in listDeformers(mesh):
            try:
                sources.append(make_deformer(node))
            except Exception as e:
                logger.warning(f"Could not wrap deformer '{node}': {e}")

    if mode in ('all', 'nucleus'):
        try:
            nucx_node = get_nucx_node(mesh)
            if nucx_node:
                # NClothMap now wraps the whole node — maps are queried lazily
                sources.append(NClothMap(nucx_node, mesh))
        except Exception as e:
            logger.debug(f"No nucleus node found for '{mesh}': {e}")

    return sources


def paint_weight_source(source: WeightSource) -> None:
    """Open the appropriate Maya paint tool for any WeightMap.

    Dispatches to the correct artisan path by checking whether the source
    is a nucleus node (``NClothMap``) or a standard deformer.  Calling code
    never needs to branch on type.

    Args:
        source: Any :class:`~dw_maya.dw_paint.protocol.WeightMap` instance
                with an active map selected via :meth:`~WeightMap.use_map`.

    Example::

        source.use_map('thickness')
        paint_weight_source(source)
    """
    # Dispatch is done through duck-typing on the class name so this module
    # does not need to import the concrete classes at the top level (avoids
    # circular imports).
    source.paint()


def apply_operation(source: WeightSource,
                    operation: Literal['flood', 'mirror', 'smooth',
                                       'vector', 'radial'],
                    **kwargs) -> None:
    """Apply a weight operation to any WeightMap.

    Reads weights from the source, runs the operation via dw_paint pure
    functions, and writes the result back.  Works identically for deformers
    and nucleus maps.

    Args:
        source:    Any :class:`~dw_maya.dw_paint.protocol.WeightMap`.
        operation: Which operation to apply:

                   ``'flood'``  — set / add / multiply a scalar value

                   ``'mirror'`` — mirror across an axis

                   ``'smooth'`` — topology-based smoothing

                   ``'vector'`` — distribute by direction vector

                   ``'radial'`` — distribute by radial distance

        **kwargs:  Forwarded to the underlying operation function.

    Keyword args by operation:

        flood:
            value (float):      Value to apply. Required.
            op (str):           ``'replace'`` | ``'add'`` | ``'multiply'``. Default ``'replace'``.
            mask (list|None):   Vertex index specs. Default None (all vertices).
            clamp_min (float):  Lower clamp. Default 0.0.
            clamp_max (float):  Upper clamp. Default 1.0.

        mirror:
            axis (str):         ``'x'`` | ``'y'`` | ``'z'``. Default ``'x'``.
            world_space (bool): Use world space. Default True.

        smooth:
            iterations (int):   Smoothing passes. Default 1.
            factor (float):     Smoothing strength 0–1. Default 0.5.

        vector:
            direction:          Predefined key or ``(x, y, z)`` tuple. Required.
            remap_range:        Optional ``(min, max)`` clamp tuple.
            falloff (str):      ``'linear'`` | ``'quadratic'`` | ``'smooth'`` | ``'smooth2'``.
            origin:             Optional ``(x, y, z)`` origin point.
            invert (bool):      Invert result. Default False.
            mode (str):         ``'projection'`` | ``'distance'``. Default ``'projection'``.

        radial:
            center:             Optional ``(x, y, z)`` centre point.
            radius (float):     Max influence radius.
            falloff (str):      Falloff curve type.
            invert (bool):      Invert result. Default False.

    Example::

        src = resolve_weight_sources('pSphere1')[0]
        apply_operation(src, 'flood', value=0.5)
        apply_operation(src, 'mirror', axis='x')
        apply_operation(src, 'smooth', iterations=3, factor=0.5)
    """
    weights = source.get_weights()
    if not weights:
        logger.warning(
            f"apply_operation: no weights returned from '{source.node_name}'"
        )
        return

    mesh = source.mesh_name
    new_weights: Optional[WeightList] = None

    if operation == 'flood':
        new_weights = _op_flood(weights, **kwargs)

    elif operation == 'mirror':
        new_weights = dw_maya.dw_paint.operations.mirror_weights(
            mesh,
            weights,
            kwargs.get('axis', 'x'),
            world_space=kwargs.get('world_space', True),
        )

    elif operation == 'smooth':
        new_weights = dw_maya.dw_paint.core.smooth_weights(
            mesh,
            weights,
            kwargs.get('iterations', 1),
            kwargs.get('factor', 0.5),
        )

    elif operation == 'vector':
        if 'direction' not in kwargs:
            raise ValueError("apply_operation 'vector' requires a 'direction' kwarg")
        new_weights = dw_maya.dw_paint.operations.set_directional_weights(
            mesh,
            kwargs['direction'],
            remap_range=kwargs.get('remap_range'),
            falloff=kwargs.get('falloff', 'linear'),
            origin=kwargs.get('origin'),
            invert=kwargs.get('invert', False),
            mode=kwargs.get('mode', 'projection'),
        )

    elif operation == 'radial':
        new_weights = dw_maya.dw_paint.operations.set_radial_weights(
            mesh,
            center=kwargs.get('center'),
            radius=kwargs.get('radius'),
            falloff=kwargs.get('falloff', 'linear'),
            invert=kwargs.get('invert', False),
        )

    else:
        raise ValueError(
            f"Unknown operation '{operation}'. "
            f"Must be one of: flood, mirror, smooth, vector, radial."
        )

    if new_weights is not None:
        source.set_weights(new_weights)
    else:
        logger.warning(
            f"apply_operation '{operation}' returned no weights for "
            f"'{source.node_name}' — weights unchanged"
        )


# ---------------------------------------------------------------------------
# Internal helpers — called by Deformer.paint() and NClothMap.paint()
# ---------------------------------------------------------------------------

def _paint_deformer(source: WeightSource) -> None:
    """Open artisan for a standard deformer WeightMap.

    Uses ``artSetToolAndSelectAttr`` — the same MEL path Maya's own UI takes.
    This correctly refreshes both the viewport weight-colour feedback and the
    Tool Settings panel even when multiple deformers are stacked.

    The attribute string format is ``"deformerType.nodeName.attributeName"``.

    Args:
        source: A deformer-backed WeightMap with :attr:`node_name` set.
    """
    node_type = cmds.nodeType(source.node_name)
    template = _ARTISAN_ATTRS.get(node_type)
    if template is None:
        logger.warning(
            f"Paint not supported for deformer type '{node_type}' "
            f"on '{source.node_name}'. "
            f"Open the Component Editor to edit weights manually."
        )
        return

    artisan_attr = template.format(node=source.node_name)
    mesh = source.mesh_name
    mesh_short = mesh.split('|')[-1]

    vtx = cmds.filterExpand(selectionMask=31, expand=False) or []
    if vtx:
        cmds.select(vtx, replace=True)
        cmds.select(mesh_short, add=True)
    else:
        cmds.select(mesh_short, replace=True)

    if not cmds.artAttrCtx('artAttrCtx', exists=True):
        cmds.artAttrCtx('artAttrCtx')

    mel.eval(f'artSetToolAndSelectAttr "artAttrCtx" "{artisan_attr}"')


def _paint_nucleus_map(source: WeightSource,
                       nucleus_node: Optional[str] = None) -> None:
    """Open artisan for a nucleus per-vertex WeightMap.

    Kept for backward compatibility.  New code should call
    ``source.paint()`` directly (which calls :func:`artisan_nucx_update`
    via :class:`~dw_maya.dw_nucleus_utils.dw_ncloth_class.NClothMap`).
    """
    from dw_maya.dw_nucleus_utils import artisan_nucx_update
    from dw_maya.dw_nucleus_utils.dw_core import get_mesh_from_nucx_node

    active_map = source.current_map or source.available_maps()[0]

    # Promote map type to PerVertex so artisan has something to paint.
    # NClothMap.map_type() and set_map_type() are the right path.
    try:
        if source.map_type(active_map) == 0:  # type: ignore[attr-defined]
            source.set_map_type(1, active_map)  # type: ignore[attr-defined]
    except AttributeError:
        pass  # non-NClothMap source — skip

    mesh_to_select = source.mesh_name
    if not mesh_to_select or not cmds.objExists(mesh_to_select):
        mesh_to_select = get_mesh_from_nucx_node(source.node_name)
    if mesh_to_select:
        cmds.select(mesh_to_select, replace=True)

    try:
        artisan_nucx_update(source.node_name, active_map, True)
    except Exception:
        if nucleus_node and cmds.objExists(nucleus_node):
            logger.debug(
                f"Artisan failed; force-enabling nucleus '{nucleus_node}' "
                f"and retrying"
            )
            _force_enable_nucleus(nucleus_node)
            if mesh_to_select:
                cmds.select(mesh_to_select, replace=True)
            try:
                artisan_nucx_update(source.node_name, active_map, True)
            except Exception as e:
                raise RuntimeError(
                    f"Could not open paint tool for nucleus map "
                    f"'{active_map}' on '{source.node_name}'. "
                    f"Ensure the nucleus is active and scrub to the first frame. "
                    f"Detail: {e}"
                )
        else:
            raise RuntimeError(
                f"Could not open paint tool for nucleus map "
                f"'{active_map}' on '{source.node_name}'. "
                f"Pass nucleus_node= to force-enable the solver."
            )


def _force_enable_nucleus(nucleus_node: str) -> None:
    """Set a nucleus solver to enabled and jump to its start frame."""
    cmds.setAttr(f'{nucleus_node}.visibility', 1)
    try:
        cmds.setAttr(f'{nucleus_node}.enable', 1)
    except Exception:
        pass
    start_frame = cmds.getAttr(f'{nucleus_node}.startFrame')
    cmds.currentTime(start_frame, update=True)


def _op_flood(weights: WeightList,
              value: float,
              op: Literal['replace', 'add', 'multiply'] = 'replace',
              mask: Optional[List] = None,
              clamp_min: float = 0.0,
              clamp_max: float = 1.0) -> WeightList:
    """Apply a flood operation to a weight list.

    Separated from :func:`apply_operation` so it can be unit-tested
    without a Maya session.
    """
    return dw_maya.dw_paint.core.modify_weights(
        weights, value, op, mask,
        min_value=clamp_min, max_value=clamp_max
    )