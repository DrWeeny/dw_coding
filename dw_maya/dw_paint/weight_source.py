"""Cross-domain WeightSource utilities for dw_paint.

Provides the functions that span both the deformer and nucleus backends,
keeping the UI and operation callers completely backend-agnostic.

Functions:
    resolve_weight_sources: Return all WeightSource objects on a mesh.
    paint_weight_source:    Open the right artisan tool for any source.
    apply_operation:        Apply a named weight operation to any source.

Example:
    from dw_maya.dw_paint.weight_source import (
        resolve_weight_sources,
        paint_weight_source,
        apply_operation,
    )

    sources = resolve_weight_sources('pSphere1')
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
# Public API
# ---------------------------------------------------------------------------

def resolve_weight_sources(
        mesh: str,
        mode: Literal['all', 'deformer', 'nucleus'] = 'all'
) -> List[WeightSource]:
    """Return all WeightSource objects available on a mesh.

    Queries both standard deformers (via history) and nucleus per-vertex
    maps so the UI never needs to handle the two backends separately.

    Args:
        mesh: Mesh transform name.
        mode: Which backends to include:
              'all'      — deformers + nucleus maps (default)
              'deformer' — standard Maya deformers only
              'nucleus'  — nCloth/nRigid per-vertex maps only

    Returns:
        List of WeightSource instances: deformers first, then nucleus maps.

    Example:
        >>> resolve_weight_sources('pSphere1')
        [<Cluster ...>, <BlendShape ...>, <NClothMap ...>]
    """
    # Lazy imports to avoid circular dependencies at module load time
    from dw_maya.dw_deformers.dw_core import listDeformers
    from dw_maya.dw_deformers.dw_deformer_class import make_deformer
    from dw_maya.dw_nucleus_utils.dw_core import get_nucx_node, get_pervertex_maps
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
                for map_name in get_pervertex_maps(nucx_node):
                    try:
                        sources.append(NClothMap(nucx_node, map_name, mesh))
                    except Exception as e:
                        logger.warning(
                            f"Could not wrap nucleus map '{map_name}' "
                            f"on '{nucx_node}': {e}"
                        )
        except Exception as e:
            logger.debug(f"No nucleus node found for '{mesh}': {e}")

    return sources


def paint_weight_source(source: WeightSource,
                        nucleus_node: Optional[str] = None) -> None:
    """Open the appropriate Maya paint tool for any WeightSource.

    Handles both standard deformer artisan and nucleus artisan so the
    UI paint button is completely backend-agnostic.

    For nucleus maps an optional ``nucleus_node`` can be supplied to
    force-enable the solver before opening artisan (useful when the
    simulation hasn't been run yet on the current frame).

    Args:
        source:       Any WeightSource — Deformer subclass or NClothMap.
        nucleus_node: Optional nucleus solver node name.  When provided
                      and artisan fails, the solver is force-enabled and
                      artisan is retried automatically.

    Example:
        >>> sources = resolve_weight_sources('pSphere1')
        >>> paint_weight_source(sources[0])
    """
    # Lazy imports — avoid circular deps and keep this module Maya-light
    from dw_maya.dw_nucleus_utils.dw_ncloth_class import NClothMap
    from dw_maya.dw_deformers.dw_deformer_class import Deformer

    if isinstance(source, NClothMap):
        _paint_nucleus_map(source, nucleus_node)
    elif isinstance(source, Deformer):
        # BlendShape, Cluster, SoftMod, Wire, deltaMush (base Deformer) — all
        # go through the same _paint_deformer path which uses cmds.artAttrCtx
        # directly to avoid artAttrToolScript.mel false warnings.
        _paint_deformer(source)
    else:
        raise TypeError(
            f"Cannot paint unsupported WeightSource type: {type(source).__name__}"
        )


def apply_operation(source: WeightSource,
                    operation: Literal['flood', 'mirror', 'smooth',
                                       'vector', 'radial'],
                    **kwargs) -> None:
    """Apply a weight operation to any WeightSource — deformer or nucleus map.

    Reads weights from the source, runs the operation via dw_paint pure
    functions, and writes the result back.  The caller never touches raw
    weight lists or cares about the backend.

    Args:
        source:    Any WeightSource (Deformer subclass or NClothMap).
        operation: Which operation to apply:
                   'flood'  — set / add / multiply a scalar value
                   'mirror' — mirror across an axis
                   'smooth' — topology-based smoothing
                   'vector' — distribute by direction vector
                   'radial' — distribute by radial distance
        **kwargs:  Forwarded to the underlying operation function.

    Keyword args by operation:

        flood:
            value (float):      Value to apply. Required.
            op (str):           'replace' | 'add' | 'multiply'. Default 'replace'.
            mask (list|None):   Vertex index specs. Default None (all vertices).
            clamp_min (float):  Lower clamp. Default 0.0.
            clamp_max (float):  Upper clamp. Default 1.0.

        mirror:
            axis (str):         'x' | 'y' | 'z'. Default 'x'.
            world_space (bool): Use world space. Default True.

        smooth:
            iterations (int):   Smoothing passes. Default 1.
            factor (float):     Smoothing strength 0–1. Default 0.5.

        vector:
            direction:          Predefined key or (x, y, z) tuple. Required.
            remap_range:        Optional (min, max) clamp tuple.
            falloff (str):      'linear' | 'quadratic' | 'smooth' | 'smooth2'.
            origin:             Optional (x, y, z) origin point.
            invert (bool):      Invert result. Default False.
            mode (str):         'projection' | 'distance'. Default 'projection'.

        radial:
            center:             Optional (x, y, z) centre point.
            radius (float):     Max influence radius.
            falloff (str):      Falloff curve type.
            invert (bool):      Invert result. Default False.

    Example:
        >>> src = resolve_weight_sources('pSphere1')[0]
        >>> apply_operation(src, 'flood', value=0.5)
        >>> apply_operation(src, 'mirror', axis='x')
        >>> apply_operation(src, 'smooth', iterations=3, factor=0.5)
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
# Private helpers
# ---------------------------------------------------------------------------

def _paint_deformer(source: WeightSource) -> None:
    """Internal: open artisan for a standard deformer WeightSource.

    Uses the MEL proc ``artSetToolAndSelectAttr`` which is the same path
    Maya's own UI takes.  It is the only approach that correctly refreshes
    both the viewport weight-colour feedback and the Tool Settings panel
    when multiple deformers are stacked on the same mesh.

    The attribute string format is ``"deformerType.nodeName.attributeName"``.
    """
    _ARTISAN_ATTRS: Dict[str, str] = {
        'cluster':    'cluster.{node}.weights',
        'softMod':    'softMod.{node}.weights',
        'blendShape': 'blendShape.{node}.baseWeights',
        'deltaMush':  'deltaMush.{node}.weights',
        'wire':       'wire.{node}.weights',
        'tension':    'tension.{node}.weights',
        'proximity':  'proximity.{node}.weights',
    }
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

    # artSetToolAndSelectAttr requires the mesh to be selected.
    mesh = source.mesh_name
    mesh_short = mesh.split('|')[-1]

    vtx = cmds.filterExpand(selectionMask=31, expand=False) or []
    vtx_mesh_short = vtx[0].split('.')[0].split('|')[-1] if vtx else ''
    sel = vtx if (vtx and vtx_mesh_short == mesh_short) else mesh_short

    cmds.select(sel, replace=True)

    # Ensure the context exists before artSetToolAndSelectAttr tries to use it.
    if not cmds.artAttrCtx('artAttrCtx', exists=True):
        cmds.artAttrCtx('artAttrCtx')

    # artSetToolAndSelectAttr is Maya's native path:
    #   - sets the paintable attribute on the context
    #   - switches the active tool to artAttrCtx
    #   - triggers the viewport colour feedback update
    #   - refreshes the Tool Settings panel
    # Any "no paintable attributes" warnings it may emit for stacked
    # deformers are cosmetic and do not prevent painting.
    mel.eval(f'artSetToolAndSelectAttr "artAttrCtx" "{artisan_attr}"')


def _paint_nucleus_map(source: "NClothMap",
                       nucleus_node: Optional[str] = None) -> None:
    """Internal: open artisan for a nucleus per-vertex map WeightSource."""
    from dw_maya.dw_nucleus_utils import artisan_nucx_update
    from dw_maya.dw_nucleus_utils.dw_ncloth_class import NClothMap  # noqa: F401 (type ref)
    from dw_maya.dw_nucleus_utils.dw_core import get_mesh_from_nucx_node

    # Ensure map type is Vertex before painting — a map at type 0 (None)
    # would accept paint strokes but silently discard them.
    if source.map_type == 0:
        logger.debug(
            f"Promoting '{source.map_name}' to MapType=Vertex before painting"
        )
        source.map_type = 1

    # artAttrNClothToolScript requires the mesh to be selected.
    # source.mesh_name is the transform; fall back to get_mesh_from_nucx_node
    # when the stored name is unavailable.
    mesh_to_select = source.mesh_name
    if not mesh_to_select or not cmds.objExists(mesh_to_select):
        mesh_to_select = get_mesh_from_nucx_node(source.node_name)
    if mesh_to_select:
        cmds.select(mesh_to_select, replace=True)

    try:
        artisan_nucx_update(source.node_name, source.map_name, True)
    except Exception:
        # First attempt failed — try force-enabling the nucleus solver
        if nucleus_node and cmds.objExists(nucleus_node):
            logger.debug(
                f"Artisan failed; force-enabling nucleus '{nucleus_node}' "
                f"and retrying"
            )
            _force_enable_nucleus(nucleus_node)
            if mesh_to_select:
                cmds.select(mesh_to_select, replace=True)
            try:
                artisan_nucx_update(source.node_name, source.map_name, True)
            except Exception as e:
                raise RuntimeError(
                    f"Could not open paint tool for nucleus map "
                    f"'{source.map_name}' on '{source.node_name}'. "
                    f"Ensure the nucleus is active and scrub to the first frame. "
                    f"Detail: {e}"
                )
        else:
            raise RuntimeError(
                f"Could not open paint tool for nucleus map "
                f"'{source.map_name}' on '{source.node_name}'. "
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

    Separated from apply_operation so it can be unit-tested without Maya.
    """
    return dw_maya.dw_paint.core.modify_weights(
        weights, value, op, mask,
        min_value=clamp_min, max_value=clamp_max
    )

