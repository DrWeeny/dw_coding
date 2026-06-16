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
            ``MFnSkinCluster.setWeights`` with ``normalize=True``.  This is the
            generic array path used by smooth / mirror / clipboard ops.  For a
            *flood* that must push freed weight onto the unlocked parent the way
            Maya does, use :meth:`flood` (``cmds.skinPercent``) instead — it
            applies Maya's own lock-aware normalisation on a vertex selection.

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
        """Write per-vertex weights for one influence, lock-aware.

        Routes through :meth:`_lock_aware_write` so the freed/borrowed weight is
        moved **only onto the unlocked sibling influences** (locked influences
        untouched) exactly like :meth:`flood` — this is the generic array writer
        for smooth / mirror / clipboard / transfer / remap.

        If the lock-aware path cannot run (returns ``False`` or raises) it falls
        back to the legacy single-column ``MFnSkinCluster.setWeights`` (API 2.0)
        with ``normalize=True``.  That fallback only *scales* the other
        influences — it cannot lift weight onto influences that are currently 0,
        so it does not respect locks the way the lock-aware path does; it exists
        purely as a safety net so weight ops never silently no-op.

        Args:
            influence_name: Short or long name of the influence joint.
            weights:        Per-vertex float list (length == :attr:`vtx_count`).

        Raises:
            ValueError: When *influence_name* is not an influence of this node.
        """
        # Preferred path — lock-aware redistribution (shared with flood()).
        try:
            if self._lock_aware_write(influence_name, None, list(weights)):
                return
        except Exception as e:
            logger.debug(
                f"_set_influence_weights_column: lock-aware path failed, "
                f"falling back to scale write — {e}"
            )

        # ── Fallback: legacy single-column scale write (API 2.0) ────────────
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

        # Single-influence write: the API 2.0 setWeights overload dispatches
        # correctly for one influence (unlike the multi-influence MIntArray case
        # used by flood(), which must use API 1.0).
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

    def flood(self,
              value: float,
              components: Optional[List] = None,
              operation: str = 'replace',
              prune: float = 0.0) -> bool:
        """Flood the active influence to *value* with deterministic, lock-aware
        redistribution onto the unlocked sibling influences.

        For each affected vertex the active influence is set to *value* and the
        freed (or borrowed) weight is moved **only onto the other unlocked
        influences**, keeping the per-vertex total at 1.0 and leaving every
        locked influence (``lockInfluenceWeights``) byte-for-byte untouched.
        With a single other unlocked influence (the typical "unlock parent +
        child, flood child to 0" case) all the weight lands on that parent.

        Implementation notes
        ---------------------
        * **API 1.0 write.**  API 2.0's ``MFnSkinCluster.setWeights``
          mis-dispatches the multi-influence ``MIntArray``+``MDoubleArray``
          overload (see ``dw_skinning.apply_weight_delta``); the API 1.0 overload
          writes the correct columns.  Influence indices are resolved by NAME
          into API 1.0's own ``influenceObjects()`` order (the two APIs need not
          enumerate identically).
        * **Normalisation off during the write.**  With interactive normalise on
          (``normalizeWeights=1``) setWeights validates incrementally and may
          reject the write; our matrix is already normalised, so it is disabled
          for the whole operation and restored after.
        * **Verify-and-retry.**  The first write on a freshly loaded skin can
          land incompletely (leaving some vertices at sum 2.0).  Each pass reads
          the live weights, recomputes and rewrites, then verifies the target is
          at *value* and rows sum to 1.0 — repeating (up to 3×) does internally
          what applying the flood twice by hand does.
        * **Why not ``cmds.skinPercent(normalize=True)``?**  It redistributes
          proportionally to *every* influence and leaves residual micro-weights,
          and it overrides the target's lock.

        Flooding a *locked* active influence is a no-op (returns ``True``),
        matching Maya's Paint Skin Weights.  ``'add'``/``'multiply'`` return
        ``False`` so the caller can fall back to the generic array path.

        Args:
            value:      Weight value to set on the active influence.
            components: Vertex component strings (``'mesh.vtx[i]'``) or integer
                        indices.  ``None`` floods the whole mesh.
            operation:  Only ``'replace'`` is handled.
            prune:      Skip vertices whose current target weight is below this
                        threshold, so negligible "garbage" weights are not
                        relocated onto a sibling (the blue-noise specks on dirty
                        rigs).  ``0.0`` (default) affects every selected vertex.

        Returns:
            ``True`` when handled (flood applied or locked-influence no-op),
            ``False`` when the caller should fall back.
        """
        if operation != 'replace':
            return False

        influence = self._current_map
        if not influence or influence == 'weightList':
            return False

        try:
            return self._lock_aware_write(influence, components, float(value),
                                          prune=prune)
        except Exception as e:
            import traceback
            logger.debug(
                f"SkinCluster.flood failed, will fall back: {e}\n"
                f"{traceback.format_exc()}"
            )
            return False

    def _lock_aware_write(self,
                          influence: str,
                          vids: Optional[List] = None,
                          targets=0.0,
                          prune: float = 0.0) -> bool:
        """Set *influence* to *targets* on *vids*, redistributing lock-aware.

        Shared core of :meth:`flood` and :meth:`_set_influence_weights_column`:
        every skinCluster weight write (flood, smooth, mirror, paste, transfer …)
        routes through here so the freed/borrowed weight is moved **only onto the
        unlocked sibling influences**, keeping each per-vertex total at 1.0 and
        leaving every locked influence (``lockInfluenceWeights``) untouched.

        Implementation notes
        ---------------------
        * **API 1.0 write.**  API 2.0's ``MFnSkinCluster.setWeights``
          mis-dispatches the multi-influence ``MIntArray``+``MDoubleArray``
          overload (see ``dw_skinning.apply_weight_delta``); the API 1.0 overload
          writes the correct columns.  Influence indices are resolved by NAME
          into API 1.0's own ``influenceObjects()`` order (the two APIs need not
          enumerate identically).
        * **Normalisation off during the write.**  With interactive normalise on
          (``normalizeWeights=1``) setWeights validates incrementally and may
          reject the write; our matrix is already normalised, so it is disabled
          for the whole operation and restored after.
        * **dgdirty after each write.**  We write with API 1.0 but verify-read
          with API 2.0; the two function sets keep independent caches, so without
          dirtying the node the readback (and the viewport) can show stale,
          pre-write values — which historically looked like an "incomplete first
          write" that needed applying twice.  ``cmds.dgdirty`` forces the write
          to commit before we re-read.
        * **Verify-and-retry.**  A safety net: each pass reads the live weights,
          recomputes and rewrites, then verifies the target is at *targets* and
          rows sum to 1.0 (up to 3×).  With the dgdirty commit this should now
          converge on pass 1 — watch the per-pass debug log to confirm.

        Args:
            influence: Active influence name (short, long, or namespaced).
            vids:      Vertex component strings (``'mesh.vtx[i]'``) or integer
                       indices.  ``None`` affects the whole mesh.
            targets:   Either a scalar applied to every affected vertex (flood),
                       or a full-length per-vertex array indexed by absolute
                       vertex id (smooth / mirror / clipboard).
            prune:     Skip affected vertices whose CURRENT weight on *influence*
                       is below this threshold, so negligible "garbage" weights
                       are not relocated onto a sibling (the blue-noise specks on
                       dirty rigs).  ``0.0`` (default) affects every vertex.

        Returns:
            ``True`` when handled (write applied or locked-influence no-op),
            ``False`` when the caller should fall back to its generic path.
        """
        import numpy as np
        import maya.api.OpenMaya as om
        import maya.api.OpenMayaAnim as oma

        # ── API 2.0 read side — influenceObjects() is the ordering authority
        sel = om.MSelectionList()
        sel.add(self.node_name)
        skin_fn = oma.MFnSkinCluster(sel.getDependNode(0))
        sel.add(self.mesh_name)
        dag = sel.getDagPath(1)
        dag.extendToShape()

        inf_objs = skin_fn.influenceObjects()
        n_inf = len(inf_objs)
        inf_names = [inf_objs[i].partialPathName() for i in range(n_inf)]

        def _leaf(nm: str) -> str:
            return nm.split('|')[-1].split(':')[-1]

        inf_idx = None
        for i, nm in enumerate(inf_names):
            if nm == influence or _leaf(nm) == _leaf(influence):
                inf_idx = i
                break
        if inf_idx is None:
            logger.warning(
                f"SkinCluster._lock_aware_write: influence '{influence}' not "
                f"found among {inf_names[:5]}{'…' if n_inf > 5 else ''}"
            )
            return False

        def _read_matrix():
            w, num = skin_fn.getWeights(dag, om.MObject())
            nv = len(w) // num if num else 0
            if nv == 0 or num != n_inf:
                return None, 0
            return np.asarray(w, dtype=float).reshape(nv, n_inf), nv

        W0, n_vtx = _read_matrix()
        if W0 is None:
            return False

        # Lock state per influence (same order; missing attr → unlocked)
        locked = np.array([
            bool(cmds.getAttr(f'{nm}.lockInfluenceWeights'))
            if cmds.objExists(f'{nm}.lockInfluenceWeights') else False
            for nm in inf_names
        ], dtype=bool)

        if locked[inf_idx]:
            logger.warning(
                f"SkinCluster._lock_aware_write: influence '{influence}' is "
                f"locked — nothing to do (unlock it to edit)"
            )
            return True

        # Affected vertices
        if vids is None:
            vid_arr = np.arange(n_vtx)
        else:
            vid_arr = np.array(sorted({
                int(c.split('[')[1].split(']')[0]) if isinstance(c, str)
                else int(c)
                for c in vids
            }), dtype=int)
            vid_arr = vid_arr[(vid_arr >= 0) & (vid_arr < n_vtx)]
            if vid_arr.size == 0:
                return False

        # Per-vertex target for the active influence: scalar broadcast (flood) or
        # a full-length array indexed by absolute vertex id (smooth / mirror).
        if np.isscalar(targets):
            tgt_full = None
        else:
            tgt_full = np.asarray(targets, dtype=float)
            if tgt_full.size != n_vtx:
                logger.warning(
                    f"SkinCluster._lock_aware_write: targets length "
                    f"{tgt_full.size} != vtx count {n_vtx} on '{self.node_name}'"
                )
                return False

        # Prune: ignore verts whose target weight is negligible garbage so we
        # never relocate sub-threshold weight onto a sibling (blue noise).
        if prune and prune > 0:
            vid_arr = vid_arr[W0[vid_arr, inf_idx] >= prune]
            if vid_arr.size == 0:
                logger.debug(
                    f"SkinCluster._lock_aware_write: nothing above prune={prune} "
                    f"for '{influence}'"
                )
                return True

        target_per_vid = (np.full(vid_arr.size, float(targets))
                          if tgt_full is None else tgt_full[vid_arr])

        absorbers = (~locked).copy()
        absorbers[inf_idx] = False
        abs_cols = np.where(absorbers)[0]
        modified = [inf_idx] + abs_cols.tolist()   # W columns (API-2.0 order)

        # Names of the modified columns (API-2.0 order) — the shared writer
        # resolves them to API 1.0 physical influence indices internally.
        modified_names = [inf_names[c] for c in modified]

        def _redistribute(W):
            """Set target on vid_arr, move the delta onto unlocked siblings,
            snap each affected row to sum 1.0.  Mutates W."""
            Wm = W[vid_arr].copy()
            bdg = (1.0 - Wm[:, locked].sum(axis=1)
                   if locked.any() else np.ones(Wm.shape[0]))
            bdg = np.clip(bdg, 0.0, None)
            tt = np.clip(target_per_vid, 0.0, bdg)
            Wm[:, inf_idx] = tt
            rem = bdg - tt
            if abs_cols.size:
                cur = Wm[:, abs_cols]
                cur_sum = cur.sum(axis=1)
                has = cur_sum > 1e-9
                prop = np.where(
                    has[:, None],
                    cur / np.where(cur_sum[:, None] > 1e-9, cur_sum[:, None], 1.0),
                    1.0 / abs_cols.size,
                )
                Wm[:, abs_cols] = prop * rem[:, None]
            else:
                Wm[:, inf_idx] = bdg
            resid = 1.0 - Wm.sum(axis=1)
            rws = np.arange(Wm.shape[0])
            primary = (abs_cols[np.argmax(Wm[:, abs_cols], axis=1)]
                       if abs_cols.size else np.full(Wm.shape[0], inf_idx))
            Wm[rws, primary] = np.clip(Wm[rws, primary] + resid, 0.0, None)
            W[vid_arr] = Wm
            return W

        def _write(W):
            vals = W[:, modified].reshape(-1)
            skinning.write_influence_columns(
                self.node_name, self.mesh_name, n_vtx,
                modified_names, vals, normalize=False)

        # Disable interactive normalisation for the whole write/verify loop.
        norm_attr = f'{self.node_name}.normalizeWeights'
        prev_norm = None
        try:
            prev_norm = cmds.getAttr(norm_attr)
            cmds.setAttr(norm_attr, 0)
        except Exception:
            prev_norm = None

        converged = False
        tol = 1e-3
        tgt_ceiling = float(np.max(target_per_vid)) if target_per_vid.size else 0.0
        try:
            for attempt in range(3):
                # Always read the LIVE weights: a prior failed pass may have
                # left the skin un-normalised, and recomputing from the live
                # state + rewriting is exactly what "apply twice" does.
                W, _ = _read_matrix()
                if W is None:
                    break
                _write(_redistribute(W))

                # Force the API 1.0 write to commit before the API 2.0 readback;
                # without this the verify can read stale pre-write weights.
                try:
                    cmds.dgdirty(self.node_name)
                except Exception:
                    pass

                Wc, _ = _read_matrix()
                if Wc is None:
                    break
                tgt_max = float(Wc[vid_arr, inf_idx].max())
                rs = Wc[vid_arr].sum(axis=1)
                converged = (tgt_max <= tgt_ceiling + tol
                             and rs.max() <= 1.0 + tol
                             and rs.min() >= 1.0 - tol)
                logger.debug(
                    f"SkinCluster._lock_aware_write pass {attempt + 1}: "
                    f"tgt_max={tgt_max:.5f}, rows=[{rs.min():.4f}, "
                    f"{rs.max():.4f}], ok={converged}"
                )
                if converged:
                    break
        finally:
            if prev_norm is not None:
                try:
                    cmds.setAttr(norm_attr, prev_norm)
                except Exception:
                    pass

        if not converged:
            logger.warning(
                f"SkinCluster._lock_aware_write: '{influence}' did not converge "
                f"after retries on '{self.node_name}' — weights may be off"
            )

        # Recolour the Paint Skin Weights viewport (API write bypasses artisan)
        try:
            ctx = self.get_artisan_name()
            if cmds.currentCtx() == ctx:
                mel.eval(f'artSkinInflListChanged {ctx}')
        except Exception:
            pass

        logger.debug(
            f"SkinCluster._lock_aware_write: '{influence}' on {vid_arr.size} "
            f"vtx → {abs_cols.size} unlocked sibling(s), converged={converged}, "
            f"prune={prune} on '{self.node_name}'"
        )
        return True

# registry the node to lsNode
_node_registry.register_type('skinCluster', SkinCluster)

# This module provides the full SkinCluster implementation (per-influence
# get/set weights, use_map, flood, …).  make_deformer() resolves classes through
# dw_deformer_class._DEFORMER_CLASSES, which still maps 'skinCluster' to the
# lightweight stub defined in that module — claim the slot so make_deformer()
# (and resolve_weight_sources / Slimfast) returns this implementation.  Safe on
# reload: re-running this module body re-applies the binding.
import dw_maya.dw_deformers.dw_deformer_class as _deformer_class
_deformer_class._DEFORMER_CLASSES['skinCluster'] = SkinCluster