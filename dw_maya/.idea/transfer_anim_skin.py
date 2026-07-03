"""Examples: retarget animation (joints -> controls) and copy a skinCluster.

Two small, runnable recipes:

1. ``transfer_animation`` - capture the keyframe animation of one node with the
   preset ``AnimationComponent`` and replay it onto a *different* node. The use
   case: bake joint animation onto its control. Uses the public
   ``apply_anim_curve`` / ``flatten_animation`` primitives, so the captured
   curves (values + tangents + infinities) move across, not just raw values.

2. ``copy_skincluster`` - bind a target mesh to the source's influences (if it
   isn't already skinned) and ``copySkinWeights`` across, so a deforming mesh's
   skin transfers to another mesh of any topology.

Example (Script Editor)::

    from dw_maya.examples import transfer_anim_skin as ex

    # joints -> controls (explicit pairs, or build from selection)
    ex.transfer_animation([("L_arm_jnt", "L_arm_ctrl"),
                           ("R_arm_jnt", "R_arm_ctrl")])
    # or: select sources then targets, equal counts, and:
    ex.transfer_animation(ex.pairs_from_selection(mode="halves"))

    # mesh -> mesh skin
    ex.copy_skincluster("body_GEO", "cloth_GEO")

Caveats:
    - Animation is retargeted by attribute name (translateX -> translateX, ...).
    - Joint rotations assume the control shares the joint's rotate order; this
      example does not remap rotate orders / gimbal.

Author:
    DrWeeny
"""

from typing import List, Optional, Sequence, Tuple

from maya import cmds

from dw_maya.dw_maya_nodes import MayaNode
import dw_maya.dw_presets_io.preset_components as pcomp
from dw_logger import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Animation: joints -> controls
# ---------------------------------------------------------------------------

def pairs_from_selection(mode: str = "halves") -> List[Tuple[str, str]]:
    """Build (source, target) pairs from the current selection.

    Args:
        mode: ``'halves'`` - first half of the selection are sources, second
            half targets (1:1 by order). ``'interleaved'`` - source, target,
            source, target, ...

    Returns:
        List of (source, target) name pairs.
    """
    sel = cmds.ls(selection=True, long=False) or []
    if mode == "interleaved":
        return list(zip(sel[0::2], sel[1::2]))
    half = len(sel) // 2
    return list(zip(sel[:half], sel[half:]))


def transfer_animation(pairs: Sequence[Tuple[str, str]],
                       clear: bool = True) -> List[str]:
    """Replay each source node's animation onto its paired target node.

    Captures the source's ``animation`` slice via the preset pipeline and writes
    every animated attribute it finds onto the same-named attribute of the
    target (when that plug exists and is settable).

    Args:
        pairs: ``[(source, target), ...]`` - e.g. ``[(joint, control), ...]``.
        clear: Remove existing animation on each target plug first (default True).

    Returns:
        The target nodes that received at least one curve.
    """
    touched: List[str] = []
    for source, target in pairs:
        if not cmds.objExists(source) or not cmds.objExists(target):
            logger.warning(f"transfer_animation: skipping missing pair "
                           f"'{source}' -> '{target}'")
            continue

        body = next(iter(MayaNode(source).createPreset(only=["animation"]).values()))
        anim = body.get("animation")
        if not anim:
            logger.warning(f"transfer_animation: no animation on '{source}'")
            continue

        applied = False
        for attr, cdata in pcomp.flatten_animation(anim).items():
            plug = f"{target}.{attr}"
            if not cmds.objExists(plug):
                logger.warning(f"transfer_animation: '{plug}' does not exist; skipping.")
                continue
            if not cmds.getAttr(plug, settable=True):
                logger.warning(f"transfer_animation: '{plug}' is not settable; skipping.")
                continue
            pcomp.apply_anim_curve(plug, cdata, clear=clear)
            applied = True

        if applied:
            touched.append(target)
            logger.info(f"transfer_animation: '{source}' -> '{target}'")
    return touched


# ---------------------------------------------------------------------------
# Skin: mesh -> mesh
# ---------------------------------------------------------------------------

def _find_skincluster(mesh: str) -> Optional[str]:
    """Return the skinCluster deforming *mesh*, or None."""
    shapes = cmds.listRelatives(mesh, shapes=True, noIntermediate=True,
                                fullPath=True) or [mesh]
    for shape in shapes:
        skins = [h for h in (cmds.listHistory(shape, pruneDagObjects=True) or [])
                 if cmds.nodeType(h) == "skinCluster"]
        if skins:
            return skins[0]
    return None


def copy_skincluster(source_mesh: str,
                     target_mesh: str,
                     surface_association: str = "closestPoint",
                     influence_association: Sequence[str] = ("oneToOne", "closestJoint")) -> str:
    """Copy the skinCluster of *source_mesh* onto *target_mesh*.

    Binds the target to the source's influences when it isn't skinned yet (or
    adds any missing influences when it is), then ``copySkinWeights`` across.
    Works between different topologies via the surface/influence association.

    Args:
        source_mesh: Mesh whose skin weights are the source of truth.
        target_mesh: Mesh to receive the weights.
        surface_association: ``copySkinWeights`` surface match
            (``closestPoint`` / ``closestComponent`` / ``rayCast``).
        influence_association: Influence matching, tried in order.

    Returns:
        The target skinCluster node name.

    Raises:
        ValueError: When the source has no skinCluster / influences.
    """
    src_skin = _find_skincluster(source_mesh)
    if not src_skin:
        raise ValueError(f"No skinCluster found on '{source_mesh}'")
    influences = cmds.skinCluster(src_skin, query=True, influence=True) or []
    if not influences:
        raise ValueError(f"skinCluster '{src_skin}' has no influences")

    tgt_skin = _find_skincluster(target_mesh)
    if not tgt_skin:
        # Bind the target to the same joints. toSelectedBones avoids grabbing
        # unrelated influences; weights are copied immediately after.
        tgt_skin = cmds.skinCluster(influences, target_mesh,
                                    toSelectedBones=True,
                                    bindMethod=0,
                                    normalizeWeights=1,
                                    name=f"{target_mesh.split('|')[-1]}_skinCluster")[0]
    else:
        existing = set(cmds.skinCluster(tgt_skin, query=True, influence=True) or [])
        missing = [inf for inf in influences if inf not in existing]
        if missing:
            cmds.skinCluster(tgt_skin, edit=True, addInfluence=missing, weight=0.0)

    cmds.copySkinWeights(sourceSkin=src_skin,
                         destinationSkin=tgt_skin,
                         noMirror=True,
                         surfaceAssociation=surface_association,
                         influenceAssociation=list(influence_association))
    logger.info(f"copy_skincluster: '{src_skin}' -> '{tgt_skin}'")
    return tgt_skin