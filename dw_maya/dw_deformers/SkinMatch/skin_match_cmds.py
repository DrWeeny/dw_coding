"""
skin_match_cmds.py - skin weight transfer with EXPLICIT influence matching.

Summary:
    A skin transfer answers two independent questions, and every Maya-native
    path guesses both at once:

    1. Which target VERTEX takes which source vertex (topology).
    2. Which target INFLUENCE takes which source influence (naming).

    ``copySkinWeights`` couples them - ``closestJoint`` re-derives the influence
    pairing by proximity, ``oneToOne`` pairs by index, and neither is inspectable
    before the write. This module separates the axes: the vertex map is chosen
    explicitly, the influence map is built by rule, shown, and hand-correctable.

Features:
    - Per-side name normalisation (regex) so both skeletons reduce to a common
      key, then match on key equality.
    - ``match_report`` quantifies what a mapping would cost BEFORE writing:
      weight mass sitting on unmatched source influences, as a percentage.
    - ``verify_transfer`` measures what actually landed: per-vertex L1 and how
      often the dominant influence changed.
    - Mappings save/load as json, so a rig convention is solved once.

Functions:
    find_skin_cluster, list_influences, canonical_name, apply_rule, auto_match,
    influence_mass, match_report, build_vertex_map, transfer_weights,
    verify_transfer, save_mapping, load_mapping

Example::

    import dw_maya.dw_deformers.SkinMatch.skin_match_cmds as smc

    src_skin = smc.find_skin_cluster("solved_mesh")
    tgt_skin = smc.find_skin_cluster("asset_mesh")
    src_infs = smc.list_influences(src_skin)
    tgt_infs = smc.list_influences(tgt_skin)

    mapping, _ = smc.auto_match(src_infs, tgt_infs,
                                src_rule=(r"^.*:", ""),
                                tgt_rule=(r"^.*:", ""))
    report = smc.match_report(src_skin, "solved_mesh", src_infs, mapping)
    print(report["at_risk_pct"])          # 0.0 == nothing would be lost

    smc.transfer_weights(src_skin, "solved_mesh",
                         tgt_skin, "asset_mesh",
                         mapping, vertex_mode="closestPoint")

TODO:
    - Many-to-one influence merging (currently one-to-one only).
    - Component (vertex selection) restricted transfer.

Author: DrWeeny
"""

import json
import re

import maya.cmds as cmds
import maya.api.OpenMaya as om

from typing import Dict, List, Optional, Tuple

import dw_maya.dw_deformers.dw_skinning as dw_skinning
from dw_logger import get_logger

logger = get_logger()


VERTEX_MODES = ("index", "closestPoint", "closestVertex")

#: Normalisation presets offered in the UI: (label, pattern, replacement).
RULE_PRESETS = (
    ("none",             r"",            ""),
    ("strip namespace",  r"^.*:",        ""),
    ("strip DAG path",   r"^.*\|",       ""),
    ("strip L/R prefix", r"^[LR]_",      ""),
    ("strip _JNT sufx",  r"_(JNT|jnt)$", ""),
)


# ---------------------------------------------------------------------------
# Scene lookups
# ---------------------------------------------------------------------------

def find_skin_cluster(mesh: str) -> Optional[str]:
    """Return the skinCluster deforming ``mesh`` (via history), or None."""
    if not mesh or not cmds.objExists(mesh):
        return None
    history = cmds.listHistory(mesh, pruneDagObjects=True) or []
    skins = cmds.ls(history, type="skinCluster") or []
    return skins[0] if skins else None


def mesh_shape(mesh: str) -> Optional[str]:
    """Return the deformed mesh shape under ``mesh`` (or ``mesh`` if a shape)."""
    if not mesh or not cmds.objExists(mesh):
        return None
    if cmds.nodeType(mesh) == "mesh":
        return mesh
    shapes = cmds.listRelatives(mesh, shapes=True, noIntermediate=True,
                                fullPath=True) or []
    return shapes[0] if shapes else None


def vertex_count(mesh: str) -> int:
    """Return the vertex count of ``mesh``, or 0 when it is not a mesh."""
    shape = mesh_shape(mesh)
    if not shape:
        return 0
    return int(cmds.polyEvaluate(shape, vertex=True))


def list_influences(skin_node: str) -> List[str]:
    """Return the influence names of ``skin_node``, in weight-column order."""
    if not skin_node or not cmds.objExists(skin_node):
        return []
    return cmds.skinCluster(skin_node, query=True, influence=True) or []


# ---------------------------------------------------------------------------
# Name normalisation + matching
# ---------------------------------------------------------------------------

def canonical_name(name: str) -> str:
    """Full DAG path for a node name, so two spellings compare equal.

    Maya hands the same node back under different names depending on which
    command asked: ``skinCluster -q -influence`` answers with the shortest
    unique name, the API and ``ls -long`` with the full path. Comparing those
    two by string silently decides a joint is absent - which either refuses a
    valid transfer or, worse, leaves its column unfed and writes zeros.

    Falls back to the name as given when it resolves to nothing, so a caller
    passing a name for a node that does not exist still gets a usable key.
    """
    found = cmds.ls(name, long=True) or []
    return found[0] if found else name


def apply_rule(names: List[str],
               pattern: str = "",
               replacement: str = "",
               ) -> Tuple[List[str], Optional[str]]:
    """Reduce names to match keys with a regex substitution.

    An empty pattern is the identity, so a rule can always be applied blindly.
    A bad regex returns the untouched names plus the error text rather than
    raising - the UI shows it live while the user is still typing, and a
    half-typed pattern must not blow up the panel.

    Args:
        names:       Influence names to normalise.
        pattern:     Regex searched for (empty = no change).
        replacement: What each match becomes.

    Returns:
        ``(keys, error)`` - keys parallel to *names*; error is None when the
        pattern compiled.
    """
    stripped = [n.split("|")[-1] for n in names]
    if not pattern:
        return stripped, None
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return stripped, f"bad regex: {e}"
    return [rx.sub(replacement, n) for n in stripped], None


def auto_match(source_names: List[str],
               target_names: List[str],
               src_rule: Tuple[str, str] = ("", ""),
               tgt_rule: Tuple[str, str] = ("", ""),
               locked: Optional[Dict[str, str]] = None,
               ) -> Tuple[Dict[str, str], List[str]]:
    """Pair source influences to target influences on normalised keys.

    Both sides are normalised by their own rule and matched on key equality -
    symmetric, so conventions differing on each side are handled by the side
    that owns them rather than by one combined source-to-target expression.

    Pairing is one-to-one: a target already claimed is not offered again, and a
    key matching several targets is reported as ambiguous instead of being
    resolved arbitrarily.

    Args:
        source_names: Influences of the source skinCluster.
        target_names: Influences of the target skinCluster (or scene joints).
        src_rule:     ``(pattern, replacement)`` applied to the source names.
        tgt_rule:     ``(pattern, replacement)`` applied to the target names.
        locked:       Manual pairs to preserve; they win over any rule result.

    Returns:
        ``(mapping, ambiguous)`` - ``{source_name: target_name}`` and the source
        names whose key hit more than one free target.
    """
    locked = dict(locked or {})
    src_keys, _ = apply_rule(source_names, *src_rule)
    tgt_keys, _ = apply_rule(target_names, *tgt_rule)

    by_key: Dict[str, List[str]] = {}
    for name, key in zip(target_names, tgt_keys):
        by_key.setdefault(key, []).append(name)

    mapping: Dict[str, str] = {}
    ambiguous: List[str] = []
    claimed = set()

    # Manual pairs first - they must not be stolen by a rule match.
    for src, tgt in locked.items():
        if src in source_names and tgt in target_names:
            mapping[src] = tgt
            claimed.add(tgt)

    for name, key in zip(source_names, src_keys):
        if name in mapping:
            continue
        free = [t for t in by_key.get(key, []) if t not in claimed]
        if not free:
            continue
        if len(free) > 1:
            ambiguous.append(name)
            continue
        mapping[name] = free[0]
        claimed.add(free[0])

    return mapping, ambiguous


# ---------------------------------------------------------------------------
# Reporting - what a mapping would cost
# ---------------------------------------------------------------------------

def influence_mass(skin_node: str,
                   mesh: str,
                   ) -> Tuple[Dict[str, float], float]:
    """Total weight carried by each influence of ``skin_node``.

    Args:
        skin_node: skinCluster to read.
        mesh:      Its deformed mesh.

    Returns:
        ``(per_influence_mass, total_mass)``.
    """
    influences, _, weights = dw_skinning.get_influence_weights(skin_node, mesh)
    n = len(influences)
    mass = {inf: 0.0 for inf in influences}
    if n == 0:
        return mass, 0.0

    for i, inf in enumerate(influences):
        mass[inf] = float(sum(weights[i::n]))
    return mass, float(sum(mass.values()))


def match_report(skin_node: str,
                 mesh: str,
                 source_names: List[str],
                 mapping: Dict[str, str],
                 ) -> Dict:
    """Quantify what a mapping would cost, BEFORE anything is written.

    An unmatched influence is only a problem if it carries weight - a rig full
    of unused twist joints can be left unmatched at no cost. So the number that
    decides whether a remap is correct is the weight MASS on unmatched source
    influences, as a share of the total. ``at_risk_pct == 0`` means the mapping
    is lossless whatever the unmatched count says.

    Args:
        skin_node:    Source skinCluster.
        mesh:         Its deformed mesh.
        source_names: Influences of the source skinCluster.
        mapping:      ``{source_name: target_name}``.

    Returns:
        Dict with ``matched`` / ``unmatched`` name lists, ``at_risk_pct``,
        ``at_risk_mass``, ``total_mass``, and ``unmatched_detail`` - the
        unmatched influences that actually carry weight, worst first.
    """
    mass, total = influence_mass(skin_node, mesh)

    # ``source_names`` comes from cmds (short names) while ``mass`` is keyed by
    # the API's partialPathName. They agree until two joints share a leaf name,
    # where the API returns a longer unique path - a plain lookup would then
    # silently score a weighted influence at 0.0 and understate the headline
    # risk figure, so fall back to the leaf name.
    by_leaf = {k.split("|")[-1]: v for k, v in mass.items()}

    def _mass_of(name: str) -> float:
        if name in mass:
            return mass[name]
        return by_leaf.get(name.split("|")[-1], 0.0)

    matched = [n for n in source_names if n in mapping]
    unmatched = [n for n in source_names if n not in mapping]

    at_risk = sum(_mass_of(n) for n in unmatched)
    detail = sorted(((n, _mass_of(n)) for n in unmatched
                     if _mass_of(n) > 1e-9),
                    key=lambda kv: kv[1], reverse=True)

    return {
        "matched": matched,
        "unmatched": unmatched,
        "total_mass": total,
        "at_risk_mass": at_risk,
        "at_risk_pct": (at_risk / total * 100.0) if total > 1e-9 else 0.0,
        "unmatched_detail": detail,
    }


# ---------------------------------------------------------------------------
# Vertex correspondence
# ---------------------------------------------------------------------------

def build_vertex_map(source_mesh: str,
                     target_mesh: str,
                     mode: str = "index",
                     ) -> Tuple[List[int], Optional[str]]:
    """Map every TARGET vertex to the source vertex it takes weights from.

    The topology axis, kept deliberately separate from the influence axis so
    that a failure in one is not mistaken for the other.

    Args:
        source_mesh: Mesh to read from.
        target_mesh: Mesh to write to.
        mode:        ``index`` (requires equal counts, exact),
                     ``closestPoint`` (closest point on the source surface, then
                     the nearest vertex of that face - exact when the target is
                     the source with points removed),
                     ``closestVertex`` (nearest source vertex outright).

    Returns:
        ``(vertex_map, error)`` - ``vertex_map[target_vtx] = source_vtx``.
    """
    n_src = vertex_count(source_mesh)
    n_tgt = vertex_count(target_mesh)
    if not n_src or not n_tgt:
        return [], "source or target is not a mesh"

    if mode == "index":
        if n_src != n_tgt:
            return [], (f"index mode needs equal vertex counts "
                        f"(source {n_src}, target {n_tgt})")
        return list(range(n_tgt)), None

    if mode == "closestVertex" and n_src * n_tgt > 40_000_000:
        # Brute-force nearest vertex is O(src * tgt) and would hang Maya with
        # no way out. Refuse rather than freeze - closestPoint is accelerated
        # and is the right answer at this size anyway.
        return [], (f"closestVertex is too slow at this size "
                    f"({n_src} x {n_tgt} vertices) - use closestPoint.")

    sel = om.MSelectionList()
    sel.add(mesh_shape(source_mesh))
    src_fn = om.MFnMesh(sel.getDagPath(0))

    sel = om.MSelectionList()
    sel.add(mesh_shape(target_mesh))
    tgt_fn = om.MFnMesh(sel.getDagPath(0))
    tgt_points = tgt_fn.getPoints(om.MSpace.kWorld)

    src_points = src_fn.getPoints(om.MSpace.kWorld)

    vertex_map: List[int] = []
    for point in tgt_points:
        if mode == "closestVertex":
            best_i, best_d = 0, None
            for i, sp in enumerate(src_points):
                d = (sp - point).length()
                if best_d is None or d < best_d:
                    best_i, best_d = i, d
            vertex_map.append(best_i)
            continue

        # closestPoint: land on a face, then take its nearest vertex.
        _, face_id = src_fn.getClosestPoint(point, om.MSpace.kWorld)
        face_verts = src_fn.getPolygonVertices(face_id)
        best_i, best_d = face_verts[0], None
        for vid in face_verts:
            d = (src_points[vid] - point).length()
            if best_d is None or d < best_d:
                best_i, best_d = vid, d
        vertex_map.append(best_i)

    return vertex_map, None


# ---------------------------------------------------------------------------
# Transfer
# ---------------------------------------------------------------------------

def transfer_weights(src_skin: str,
                     source_mesh: str,
                     tgt_skin: str,
                     target_mesh: str,
                     mapping: Dict[str, str],
                     vertex_mode: str = "index",
                     vertex_map: Optional[List[int]] = None,
                     add_missing_influences: bool = True,
                     normalize: bool = True,
                     ) -> Tuple[bool, str]:
    """Re-column the source weights through ``mapping`` and write them.

    Every target influence is written, not only the mapped ones: an unmapped
    target influence is explicitly zeroed, otherwise its previous weights would
    survive underneath the transferred ones and quietly blend with them.

    ``maintainMaxInfluences`` is switched off for the write and restored after -
    left on, it prunes the incoming columns to the target's own cap and the
    result silently disagrees with the source.

    Args:
        src_skin:               Source skinCluster.
        source_mesh:            Its mesh.
        tgt_skin:               Target skinCluster.
        target_mesh:            Its mesh.
        mapping:                ``{source_influence: target_influence}``.
        vertex_mode:            One of ``VERTEX_MODES`` (ignored when
                                *vertex_map* is supplied).
        vertex_map:             Precomputed ``target_vtx -> source_vtx``, so the
                                report and the write share one correspondence.
        add_missing_influences: Add mapped joints that are not yet influences of
                                the target skinCluster.
        normalize:             Normalise each vertex row on write.

    Returns:
        ``(ok, message)``.
    """
    if not mapping:
        return False, "The influence mapping is empty - nothing to transfer."

    if vertex_map is None:
        vertex_map, err = build_vertex_map(source_mesh, target_mesh, vertex_mode)
        if err:
            return False, err

    src_infs, _, src_weights = dw_skinning.get_influence_weights(
        src_skin, source_mesh)
    n_src_cols = len(src_infs)
    # Both axes are keyed on the full path: the mapping is written by a caller
    # that may spell a joint any way Maya allowed it to, and matching by raw
    # string makes a present influence look absent.
    src_col = {canonical_name(name): i for i, name in enumerate(src_infs)}

    # Add mapped joints the target cluster does not carry yet.
    tgt_infs = list_influences(tgt_skin)
    tgt_by_key = {canonical_name(name): name for name in tgt_infs}
    wanted = sorted(set(mapping.values()))
    missing = [j for j in wanted if canonical_name(j) not in tgt_by_key]
    if missing:
        if not add_missing_influences:
            return False, (f"{len(missing)} mapped joints are not influences of "
                           f"'{tgt_skin}' (first: {missing[0]}).")
        for joint in missing:
            if not cmds.objExists(joint):
                return False, f"Mapped joint '{joint}' does not exist."
            cmds.skinCluster(tgt_skin, edit=True, addInfluence=joint,
                             weight=0.0, lockWeights=False)
        tgt_infs = list_influences(tgt_skin)
        tgt_by_key = {canonical_name(name): name for name in tgt_infs}

    # target influence -> source column feeding it (None = zero it out)
    feed: Dict[str, Optional[int]] = {name: None for name in tgt_infs}
    for src_name, tgt_name in mapping.items():
        resolved = tgt_by_key.get(canonical_name(tgt_name))
        src_key = canonical_name(src_name)
        if resolved is not None and src_key in src_col:
            feed[resolved] = src_col[src_key]

    n_tgt = len(vertex_map)
    n_cols = len(tgt_infs)
    flat = [0.0] * (n_tgt * n_cols)
    for v_tgt, v_src in enumerate(vertex_map):
        base_src = v_src * n_src_cols
        base_tgt = v_tgt * n_cols
        for c, name in enumerate(tgt_infs):
            col = feed[name]
            if col is not None:
                flat[base_tgt + c] = src_weights[base_src + col]

    shape = mesh_shape(target_mesh)
    prior = cmds.getAttr(f"{tgt_skin}.maintainMaxInfluences")
    try:
        cmds.setAttr(f"{tgt_skin}.maintainMaxInfluences", False)
        dw_skinning.write_influence_columns(tgt_skin, shape, n_tgt,
                                            tgt_infs, flat,
                                            normalize=normalize)
    except Exception as e:
        logger.error(f"SkinMatch transfer failed: {e}")
        return False, f"Write failed: {e}"
    finally:
        cmds.setAttr(f"{tgt_skin}.maintainMaxInfluences", prior)

    zeroed = sum(1 for name in tgt_infs if feed[name] is None)
    return True, (f"Transferred {len(mapping)} influence columns onto "
                  f"{n_tgt} vertices ({zeroed} target influences zeroed).")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_transfer(src_skin: str,
                    source_mesh: str,
                    tgt_skin: str,
                    target_mesh: str,
                    mapping: Dict[str, str],
                    vertex_map: List[int],
                    ) -> Dict:
    """Measure what actually landed, by comparing weights directly.

    A fidelity check at the bind pose proves nothing - every weighting
    reproduces the rest shape there, so a positional comparison validates the
    bind matrices and stays blind to the weights. This compares the weight
    values themselves, which is true at any frame.

    ``dominant_changed`` is the number that matters most: an L1 of 0.02 spread
    over eight influences is invisible, while a single vertex whose dominant
    influence flipped is a visible artefact.

    Args:
        src_skin/source_mesh: The source side.
        tgt_skin/target_mesh: The target side, after the transfer.
        mapping:              The influence mapping that was applied.
        vertex_map:           The vertex correspondence that was applied.

    Returns:
        Dict with ``mean_l1``, ``max_l1``, ``dominant_changed``,
        ``dominant_changed_pct`` and ``vertices``.
    """
    src_infs, _, src_w = dw_skinning.get_influence_weights(src_skin, source_mesh)
    tgt_infs, _, tgt_w = dw_skinning.get_influence_weights(tgt_skin, target_mesh)
    n_src, n_tgt_cols = len(src_infs), len(tgt_infs)

    # Keyed on the full path for the same reason the transfer is: a mapping
    # spelled differently from the influence list would pair nothing here and
    # report a perfect transfer as having moved no weight at all.
    src_col = {canonical_name(n): i for i, n in enumerate(src_infs)}
    tgt_col = {canonical_name(n): i for i, n in enumerate(tgt_infs)}
    pairs = [(src_col[canonical_name(s)], tgt_col[canonical_name(t)])
             for s, t in mapping.items()
             if canonical_name(s) in src_col and canonical_name(t) in tgt_col]
    expected_col = dict(pairs)      # hoisted: per-vertex rebuild is O(n) each

    total_l1 = 0.0
    max_l1 = 0.0
    dominant_changed = 0
    counted = 0

    for v_tgt, v_src in enumerate(vertex_map):
        base_src = v_src * n_src
        base_tgt = v_tgt * n_tgt_cols

        l1 = 0.0
        best_src, best_src_w = None, -1.0
        best_tgt, best_tgt_w = None, -1.0
        for cs, ct in pairs:
            ws = src_w[base_src + cs]
            wt = tgt_w[base_tgt + ct]
            l1 += abs(ws - wt)
            if ws > best_src_w:
                best_src, best_src_w = cs, ws
            if wt > best_tgt_w:
                best_tgt, best_tgt_w = ct, wt

        total_l1 += l1
        max_l1 = max(max_l1, l1)
        counted += 1
        # Compare the dominant influence through the mapping, not by column id.
        if best_src is not None and best_tgt is not None:
            if expected_col.get(best_src) != best_tgt:
                dominant_changed += 1

    return {
        "vertices": counted,
        "mean_l1": (total_l1 / counted) if counted else 0.0,
        "max_l1": max_l1,
        "dominant_changed": dominant_changed,
        "dominant_changed_pct": (dominant_changed / counted * 100.0)
                                if counted else 0.0,
    }


# ---------------------------------------------------------------------------
# Mapping I/O
# ---------------------------------------------------------------------------

def save_mapping(path: str,
                 mapping: Dict[str, str],
                 src_rule: Tuple[str, str] = ("", ""),
                 tgt_rule: Tuple[str, str] = ("", ""),
                 ) -> bool:
    """Write a mapping (and the rules that produced it) to json.

    The rules travel with the pairs on purpose: a mapping solved for one rig
    convention should re-derive itself on the next asset that follows it,
    rather than being replayed as a frozen name list that silently misses
    everything renamed since.
    """
    data = {
        "format": "dw_skin_match",
        "version": 1,
        "src_rule": list(src_rule),
        "tgt_rule": list(tgt_rule),
        "mapping": mapping,
    }
    try:
        with open(path, "w") as fh:
            json.dump(data, fh, indent=2)
    except Exception as e:
        logger.error(f"Failed to save mapping '{path}': {e}")
        return False
    return True


def load_mapping(path: str,
                 ) -> Tuple[Dict[str, str], Tuple[str, str], Tuple[str, str]]:
    """Read a mapping json. Returns ``(mapping, src_rule, tgt_rule)``."""
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
    except Exception as e:
        logger.error(f"Failed to load mapping '{path}': {e}")
        return {}, ("", ""), ("", "")

    if data.get("format") != "dw_skin_match":
        logger.warning(f"'{path}' is not a dw_skin_match file.")
        return {}, ("", ""), ("", "")

    src_rule = tuple(data.get("src_rule", ["", ""]))
    tgt_rule = tuple(data.get("tgt_rule", ["", ""]))
    return dict(data.get("mapping", {})), src_rule, tgt_rule