from __future__ import annotations

import functools

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal
from typing import Dict, List, Optional, Tuple, Union

from maya import cmds, mel
import dw_maya.dw_node_registry as _node_registry
from dw_maya.dw_deformers.dw_deformer_class import Deformer
import dw_maya.dw_deformers.dw_skinning as skinning

from dw_logger import get_logger
logger = get_logger()

# ---------------------------------------------------------------------------
# SkinCluster
# ---------------------------------------------------------------------------

class SkinCluster(Deformer):
    """SkinCluster deformer — influences, per-influence weights.

    :meth:`available_maps` returns ``'weightList'`` plus one entry per
    influence joint.  :meth:`use_map` selects which influence's weights
    :meth:`get_weights` / :meth:`set_weights` operate on.

    Example::

        sc = make_deformer('skinCluster1')
        sc.available_maps()               # ['weightList', 'joint1', 'joint2']
        sc.use_map('joint1').get_weights()
        sc.use_map('weightList').get_weights()  # full packed array
    """

    def __init__(self, name: str, preset: Optional[Dict] = None,
                 blend_value: float = 1.0):
        super().__init__(name, preset, blend_value)
        if cmds.nodeType(self.node) != 'skinCluster':
            raise ValueError(f"'{name}' is not a skinCluster deformer")
        self.__dict__['_influence_index'] = 0

    def available_maps(self) -> List[str]:
        """``'weightList'`` + one entry per influence joint."""
        return ['weightList'] + self.influences

    def use_map(self, map_name: str) -> 'SkinCluster':
        """Activate a map and switch the artisan influence if the tool is open.

        Extends the base ``use_map`` so that selecting an influence from the
        ``SkinPanel`` joint list immediately updates the Paint Skin Weights
        viewport colouring — identical to clicking a bone in Maya's own
        Influence list in the Tool Settings panel.

        The MEL calls are only issued when ``artAttrSkinPaintCtx`` is the
        current context; otherwise this is a pure ``_current_map`` assignment
        with no Maya side-effects.

        Args:
            map_name: Influence joint name (full DAG path or short name) or
                      ``'weightList'`` for the packed per-vertex array.

        Returns:
            ``self`` for chaining.
        """
        # equivalent of doing `map_name in available_maps()`
        super().use_map(map_name)
        if map_name and map_name != 'weightList':
            try:
                _artisan_ctx = self.get_artisan_name()
                if cmds.currentCtx() == _artisan_ctx:
                    bone_short = map_name.split('|')[-1]
                    mel.eval(f'artSkinInflListChanging "{bone_short}" 1')
                    mel.eval(f'artSkinInflListChanged {_artisan_ctx}')
            except Exception as e:
                logger.debug(
                    f"SkinCluster.use_map: could not switch influence "
                    f"'{map_name}' — {e}"
                )
        return self

    def _resolve_attr(self, map_name: str) -> str:
        n = self.vtx_count
        weight_range = f'0:{n - 1}' if n > 0 else '0'
        if map_name == 'weightList':
            return (
                f'{self.node_name}.weightList[{self.geo_index}]'
                f'.weights[{weight_range}]'
            )
        # Per-influence path — use the physical influence index
        all_influences = self.influences
        if map_name in all_influences:
            inf_index = all_influences.index(map_name)
            return (
                f'{self.node_name}.weightList[0:{n - 1}]'
                f'.weights[{inf_index}]'
            )
        raise ValueError(
            f"Unknown map '{map_name}' on SkinCluster '{self.node_name}'"
        )

    @property
    def influences(self) -> List[str]:
        return cmds.skinCluster(self.node_name, query=True, influence=True) or []

    def _resolve_influence_index(self, influence_name: str) -> Optional[int]:
        """Return the physical column index of *influence_name*.

        Handles three name forms so callers never need to normalise:

        - full DAG path  ``'|root|spine|ns:joint1'``
        - short with ns  ``'ns:joint1'``
        - short bare     ``'joint1'``

        Returns:
            Integer index, or ``None`` when the influence is not found.
        """
        all_infs = self.influences  # cmds.skinCluster(q=True, influence=True)

        # 1. Exact match — covers the common case when names are consistent
        if influence_name in all_infs:
            return all_infs.index(influence_name)

        # 2. Leaf-name fallback — strip DAG prefix from both sides
        short_query = influence_name.split('|')[-1]
        for i, inf in enumerate(all_infs):
            if inf.split('|')[-1] == short_query:
                return i

        return None

    # ------------------------------------------------------------------
    # Bulk weight queries (API 2.0)
    # ------------------------------------------------------------------

    def get_weights(self) -> List[float]:
        """Per-vertex weight array for the active map.

        Active map is set by :meth:`use_map`:

        ``'weightList'``
            Full packed flat array ``[vtx0_inf0, vtx0_inf1, …, vtxN_infM-1]``.
            Length = ``vtx_count × influence_count``.

        joint name
            Per-vertex weights for that influence only.
            Length = ``vtx_count``.

        Both paths use ``MFnSkinCluster.getWeights`` (already called by
        :meth:`get_all_weights`) — no ``_resolve_attr`` / ``cmds.getAttr``.
        """
        map_name = self._current_map or 'weightList'

        weights, num_influences = self.get_all_weights()  # one API call

        if map_name == 'weightList':
            return weights

        # Per-influence: extract one column from the flat array
        inf_idx = self._resolve_influence_index(map_name)
        if inf_idx is None:
            logger.warning(
                f"SkinCluster.get_weights: influence '{map_name}' not found "
                f"on '{self.node_name}', returning zeros"
            )
            return [0.0] * self.vtx_count

        # Flat layout: [vtx0_inf0, vtx0_inf1, …] → stride = num_influences
        return list(weights[inf_idx::num_influences])

    def set_weights(self, weights: List[float]) -> None:
        """Write a weight array for the active map back to the skinCluster.

        Active map is set by :meth:`use_map`:

        joint name
            Writes the per-vertex weight column for that influence via
            ``MFnSkinCluster.setWeights`` with ``normalize=True`` so Maya
            redistributes the remaining weight across the other (unlocked)
            influences.  The skin cluster is always left normalised.

        ``'weightList'``
            Not implemented — the full packed write requires careful index
            reconstruction and is not needed by Slimfast operations.
            Use :meth:`transfer_soft_weights` / :func:`apply_weight_delta`
            for bulk redistribution instead.

        Args:
            weights: Per-vertex float list (length must equal :attr:`vtx_count`).

        Raises:
            ValueError:          When the active influence is not found.
            NotImplementedError: When ``current_map == 'weightList'``.
        """
        map_name = self._current_map or 'weightList'

        if map_name == 'weightList':
            raise NotImplementedError(
                "SkinCluster.set_weights: writing the full packed 'weightList' "
                "is not supported.  Activate a specific influence first with "
                "use_map(joint_name), or use apply_weight_delta() for bulk "
                "redistribution."
            )

        self._set_influence_weights_column(map_name, weights)

    def _set_influence_weights_column(self,
                                      influence_name: str,
                                      weights: List[float]) -> None:
        """Write per-vertex weights for one influence via the API.

        Uses ``MFnSkinCluster.setWeights`` (API 2.0) with ``normalize=True``
        so Maya redistributes the remaining weight across unlocked influences
        automatically.

        Only one column is written per call — all other influences are
        untouched by the write itself; Maya's normalisation adjusts them.

        Args:
            influence_name: Short or long name of the influence joint.
            weights:        Per-vertex float list (length == :attr:`vtx_count`).

        Raises:
            ValueError: When *influence_name* is not an influence of this node.
        """
        import maya.api.OpenMaya as om
        import maya.api.OpenMayaAnim as oma

        inf_idx = self._resolve_influence_index(influence_name)
        if inf_idx is None:
            raise ValueError(
                f"SkinCluster._set_influence_weights_column: "
                f"'{influence_name}' is not an influence of '{self.node_name}'.\n"
                f"Known: {self.influences[:5]}{'…' if len(self.influences) > 5 else ''}"
            )

        # Build MFnSkinCluster
        sel = om.MSelectionList()
        sel.add(self.node_name)
        skin_fn = oma.MFnSkinCluster(sel.getDependNode(0))

        # Mesh DAG path — must extend to shape
        sel.add(self.mesh_name)
        dag = sel.getDagPath(1)
        dag.extendToShape()

        # setWeights(dagPath, components, influenceIndices, weights, normalize)
        #   om.MObject()        → "all vertices" (same convention as getWeights)
        #   inf_indices=[idx]   → only the target influence column
        #   weights length      → vtx_count × len(inf_indices) == vtx_count
        #   normalize=True      → redistribute remainder across unlocked infs
        inf_indices = om.MIntArray([inf_idx])
        wt_array = om.MDoubleArray(weights)

        skin_fn.setWeights(dag, om.MObject(), inf_indices, wt_array, True)

        logger.debug(
            f"SkinCluster: wrote {len(weights)} weights for "
            f"'{influence_name}' (col {inf_idx}) on '{self.node_name}'"
        )

    def get_all_weights(self) -> Tuple[List[float], int]:
        """Return the full flat weight array and influence count.

        Format: ``[vtx0_inf0, vtx0_inf1, …, vtxN_infM-1]``
        """
        import maya.api.OpenMaya as om
        import maya.api.OpenMayaAnim as oma

        sel = om.MSelectionList()
        sel.add(self.node_name)
        skin_fn = oma.MFnSkinCluster(sel.getDependNode(0))

        sel.add(self.mesh_name)
        mesh_path = sel.getDagPath(1)
        mesh_path.extendToShape()
        weights, num_influences = skin_fn.getWeights(mesh_path, om.MObject())
        return list(weights), num_influences

    def get_influence_weights(self, influence: str) -> List[float]:
        """Per-vertex weights for a single influence (fast array slice).

        Uses :meth:`_resolve_influence_index` for robust name matching so
        full DAG paths, short names and namespaced names all resolve correctly.
        """
        inf_idx = self._resolve_influence_index(influence)
        if inf_idx is None:
            logger.warning(
                f"SkinCluster.get_influence_weights: '{influence}' not found "
                f"in '{self.node_name}', returning zeros"
            )
            return [0.0] * self.vtx_count

        weights, num_influences = self.get_all_weights()
        return list(weights[inf_idx::num_influences])

    # ------------------------------------------------------------------
    # Soft-selection / participation helpers (delegate to skinning.py)
    # ------------------------------------------------------------------

    def get_vertex_influence_weights(self,
                                     soft_mask: List[float]
                                     ) -> Dict[str, List[float]]:
        """Per-bone weight arrays aligned to the full vertex list.

        Args:
            soft_mask: Full-length float list (index == vertex index,
                       0.0 for unselected vertices).

        Returns:
            ``{bone_name: [weight_per_vtx, …]}``
        """
        return skinning.get_vertex_influence_weights(
            self.node_name, soft_mask, self.mesh_name
        )

    def get_participation(self,
                          soft_mask: List[float],
                          heat_participation: float = 0.0
                          ) -> Dict[str, float]:
        """Each bone's soft-weighted participation percentage.

        Args:
            soft_mask:          Full-length soft selection mask.
            heat_participation: Ignore soft-mask values below this threshold.

        Returns:
            ``{bone_name: percentage}`` sorted descending, values sum ~100.
        """
        bone_arrays = self.get_vertex_influence_weights(soft_mask)
        return skinning.get_participation(bone_arrays, soft_mask, heat_participation)

    def get_dominant_bones(self,
                           soft_mask: List[float],
                           top_n: int = 1,
                           heat_participation: float = 0.0
                           ) -> List[str]:
        """Return the *top_n* most influential bones inside the soft selection.

        Combines :meth:`get_vertex_influence_weights`,
        :meth:`get_participation` and ``get_dominant_bone`` in one call.

        Args:
            soft_mask:          Full-length soft selection mask.
            top_n:              How many bones to return (highest first).
            heat_participation: Threshold passed to :meth:`get_participation`.

        Returns:
            List of bone names, highest participation first.
        """
        bone_arrays  = self.get_vertex_influence_weights(soft_mask)
        participation = skinning.get_participation(bone_arrays, soft_mask, heat_participation)
        return skinning.get_dominant_bone(participation, top_n)

    def get_accumulated_influences(self,
                                   components: List[str]
                                   ) -> Dict[str, float]:
        """Accumulated weights per influence across *components*.

        Args:
            components: Maya component strings, e.g. ``['pSphere1.vtx[0]', …]``.

        Returns:
            ``{bone_name: accumulated_weight}`` sorted descending.
        """
        return skinning.get_accumulated_influences(self.node_name, components)

    # ------------------------------------------------------------------
    # Jiggle weight redistribution
    # ------------------------------------------------------------------

    def transfer_soft_weights(self,
                              target_joint: str,
                              soft_mask: List[float],
                              donor_bones: Optional[List[str]] = None,
                              normalize: bool = True) -> Dict[str, object]:
        """Redirect a soft-selection–weighted portion of bone weights to *target_joint*.

        General-purpose weight transfer driven by a soft-selection mask.
        Each vertex donates ``soft_mask[v]`` × its current donor-bone weight
        to *target_joint*, keeping the per-vertex total at exactly 1.0.

        Typical uses
        ------------
        * Jiggle / secondary motion joints.
        * PIN joints for cloth / accessory attachments.
        * Any additional influence that should blend smoothly with existing skinning.

        Steps
        -----
        1. Adds *target_joint* as an influence (weight 0) if not already present.
        2. Computes the per-vertex delta via :func:`skinning.compute_weight_delta`.
        3. Writes all weights in a single C++ call (unnormalised).
        4. Runs ``forceNormalizeWeights`` so the skin cluster is always in a
           valid state — Maya requires all per-vertex weights to sum to 1.0.
           Pass ``normalize=False`` only if you are batching multiple transfers
           and will normalise manually afterwards.

        Args:
            target_joint: Joint that will receive the redistributed weights.
            soft_mask:    Full-length soft selection mask ([0, 1] per vertex).
            donor_bones:  Bones to pull weight from.  ``None`` → auto-pick the
                          dominant bone inside the soft selection.
            normalize:    Force-normalise the skin cluster after writing
                          (default ``True`` — almost always required).

        Returns:
            The delta dict ``{'jiggle': […], 'bones': {…}}`` for inspection or undo.
        """
        if donor_bones is None:
            donor_bones = self.get_dominant_bones(soft_mask, top_n=1)

        # Only keep bones that are actually influences of this skin cluster
        sc_bones = [b for b in donor_bones if b in self.influences]
        if not sc_bones:
            raise RuntimeError(
                f"transfer_soft_weights: none of {donor_bones} are influences "
                f"of '{self.node_name}'"
            )

        # Ensure the target is an influence before writing
        if target_joint not in self.influences:
            self.add_influence(target_joint, default_weight=0.0)

        bone_arrays = self.get_vertex_influence_weights(soft_mask)
        delta = skinning.compute_weight_delta(
            bone_arrays, soft_mask, sc_bones, self.mesh_name
        )

        # Write weights — always unnormalised here so the C++ call is a pure
        # data write; normalisation is handled explicitly below.
        skinning.apply_weight_delta(self.node_name, target_joint, delta,
                                    normalize=False)

        # Maya skin clusters must have normalised weights — do it here so the
        # step is visible and controllable at the class level.
        if normalize:
            cmds.skinCluster(self.node_name, edit=True, forceNormalizeWeights=True)

        return delta

    # ------------------------------------------------------------------
    # Influence management
    # ------------------------------------------------------------------

    def add_influence(self, joint: str, default_weight: float = 0.0) -> None:
        if cmds.objExists(joint):
            cmds.skinCluster(
                self.node_name, edit=True,
                addInfluence=joint, weight=default_weight,
                lockWeights=False,
            )
        else:
            logger.warning(f"Joint '{joint}' does not exist")

    # ------------------------------------------------------------------
    # Paint — skin weights artisan
    # ------------------------------------------------------------------

    def get_artisan_name(self) -> str:
        """Return the Maya artisan context name for Paint Skin Weights."""
        return "artAttrSkinPaintCtx"

    def _paint(self) -> None:
        """Open Paint Skin Weights focused on the currently active map (influence).

        Flow
        ----
        1. Select the mesh.
        2. Enter ``artAttrSkinPaintCtx`` via ``ArtPaintSkinWeightsTool``.
        3. If ``_current_map`` is a bone name (not ``'weightList'``), call
           ``artSkinSelectInfluence`` to lock the viewport colouring onto that
           specific influence — the same action as clicking a bone in the
           Influence list in the Tool Settings panel.

        The ``use_map()`` → ``_paint()`` call chain is the intended API::

            sc = SkinCluster('skinCluster1')
            sc.use_map('BB_M_0_Spine').paint()  # opens paint locked on Spine
        """
        active_map = self._current_map  # set by use_map()

        mesh = self.mesh_name
        mesh_short = mesh.split('|')[-1]

        # 1. Select the mesh (preserving any vertex pre-selection)
        vtx = cmds.filterExpand(selectionMask=31, expand=False) or []
        if vtx:
            cmds.select(vtx, replace=True)
            cmds.select(mesh_short, add=True)
        else:
            cmds.select(mesh_short, replace=True)

        # 2. Enter Paint Skin Weights tool
        mel.eval('ArtPaintSkinWeightsTool')

        if not active_map or active_map == 'weightList':
            # No specific influence — just open the tool on the mesh
            return

        # 3. Select the influence in the Tool Settings panel and update the
        #    viewport weight-colour display.
        #
        #    The correct MEL sequence (observed via Echo All Commands) is:
        #      artSkinInflListChanging "<bone_with_ns>" 1;
        #      artSkinInflListChanged  artAttrSkinPaintCtx;
        #
        #    The bone name must keep its namespace — the artisan stores
        #    influences under their full name (e.g. "_NS_:BB_M_0_Spine").
        #    We only strip the DAG path prefix ("|") if present.
        bone_full = active_map.split('|')[-1]

        try:
            mel.eval(f'artSkinInflListChanging "{bone_full}" 1')
            mel.eval('artSkinInflListChanged artAttrSkinPaintCtx')
        except Exception as e:
            logger.warning(
                f"SkinCluster._paint: could not select influence "
                f"'{bone_full}' — {e}"
            )

    def paint_influence(self, bone: str) -> None:
        """Convenience wrapper: ``use_map(bone)`` then ``_paint()``.

        Args:
            bone: Influence joint name (short, long, or with namespace).
        """
        self.use_map(bone)
        self._paint()

# registry the node to lsNode
_node_registry.register_type('skinCluster', SkinCluster)