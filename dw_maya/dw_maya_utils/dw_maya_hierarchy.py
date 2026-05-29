"""
Maya Hierarchy Transform Cleaning Utilities

Scan a DAG hierarchy for non-identity transform values and fix them safely,
even when attributes are locked or hidden by pipeline constraints.

Features:
    - Detect dirty transforms: translate, rotate, scale, shear, pivots and
      their compensate-translate counterparts (rotatePivotTranslate,
      scalePivotTranslate) which Maya adds silently when a user moves a pivot.
    - Build a flat dict and a nested tree from a single DAG traversal.
    - Context manager that saves lock/keyable/channelBox state, temporarily
      unlocks attributes, runs the operation, then restores original state.
    - Freeze transforms (makeIdentity) and reset pivots per node.
    - Batch fix across a hierarchy with optional skip of constrained nodes.
    - All fix entry points accept either a plain string path or a MayaNode
      instance (duck-typed via .tr), so the module integrates naturally with
      the dw_maya_nodes layer without creating a circular import.

dw_maya_nodes integration notes:
    - Detection (get_dirty_reasons, build_dirty_cache) uses om2 MItDag
      directly — this is the fastest path; MayaNode adds overhead here.
    - Fix functions (_resolve_transform, freeze_node, reset_node_pivot, …)
      accept MayaNode via duck-typing: any object that exposes a .tr property
      is treated as a node wrapper and its .tr value is used as the path.
    - is_constrained lazily imports MAttr from dw_maya.dw_maya_nodes.attr
      (attr.py has no dw_maya_utils dependency, so it is import-safe) to
      perform per-attribute connection queries through the wrapper API.
    - MayaNode is NOT imported at module level to avoid the circular import:
      dw_maya_utils.__init__ → dw_maya_hierarchy → dw_maya_nodes → maya_node
                                                                  → dw_maya_utils

Classes:
    None (plain dicts are used for dirty-reason reports)

Functions:
    get_dirty_reasons    : Inspect one DAG node, return dirty breakdown dict.
    build_dirty_cache    : Traverse DAG, return (flat, nested) caches.
    get_subtree          : Navigate the nested cache by short node names.
    dirty_in_subtree     : Collect dirty fullpaths under a given ancestor.
    unlocked_attrs       : Context manager – unlock attrs, restore on exit.
    is_constrained       : Check if a node's transform channels are driven.
    freeze_node          : Apply makeIdentity, bypassing locked attrs.
    reset_node_pivot     : Zero all pivot attrs, bypassing locked attrs.
    fix_node             : Apply matrix and/or pivot fix to one node.
    fix_hierarchy        : Scan and fix all dirty nodes under a root.

Example:
    >>> import dw_maya.dw_maya_utils.dw_maya_hierarchy as dw_hierarchy
    >>> flat, nested = dw_hierarchy.build_dirty_cache(root="|rig")
    >>> dirty = dw_hierarchy.dirty_in_subtree(nested, "rig", "offset_grp")

    >>> # Works with plain strings
    >>> dw_hierarchy.fix_node("|rig|arm_grp")

    >>> # Works with MayaNode instances (duck-typed)
    >>> import dw_maya.dw_maya_nodes as dwn
    >>> mn = dwn.MayaNode("|rig|arm_grp")
    >>> dw_hierarchy.fix_node(mn)

    >>> report = dw_hierarchy.fix_hierarchy("|rig", fix_matrix=True, fix_pivot=True)

TODO:
    - Extend skip logic for boss-defined constraint cases (e.g. keep
      parentConstraint but still freeze scale).
    - Add joint-orient dirty detection for skeleton hierarchies.
    - Surface results in a UI (see dw_widgets).

Author: DrWeeny
"""

import contextlib
import maya.api.OpenMaya
from maya import cmds
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# Attribute name constants
# ---------------------------------------------------------------------------

# Short names of all local-matrix attributes needed by makeIdentity
_MATRIX_ATTRS: List[str] = [
    "tx", "ty", "tz",
    "rx", "ry", "rz",
    "sx", "sy", "sz",
    "shxy", "shxz", "shyz",
]

# Short names of pivot + pivot-compensate attrs needed by reset-pivot
_PIVOT_ATTRS: List[str] = [
    "rpx", "rpy", "rpz",       # rotatePivot
    "spx", "spy", "spz",       # scalePivot
    "rptx", "rpty", "rptz",    # rotatePivotTranslate  (Maya auto-compensate)
    "sptx", "spty", "sptz",    # scalePivotTranslate   (Maya auto-compensate)
]

# Channels checked by is_constrained (standard constraint targets)
_DRIVEN_ATTRS: List[str] = ["tx", "ty", "tz", "rx", "ry", "rz"]

# Shear attrs — never driven by standard Maya constraints; always fixable
_SHEAR_ATTRS: List[str] = ["shxy", "shxz", "shyz"]

# Scale attrs — driven only by scaleConstraint (rarer than parent/point/orient)
_SCALE_ATTRS: List[str] = ["sx", "sy", "sz"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_transform(node: Any) -> str:
    """
    Return the string transform path from a plain string or a MayaNode.

    Duck-types anything that exposes a ``.tr`` property as a MayaNode.
    This avoids a direct import of MayaNode (which would create a circular
    import via dw_maya_utils.__init__) while still benefiting from MayaNode's
    namespace and DAG resolution logic.

    Args:
        node: Either a plain Maya fullpath string or any object with ``.tr``.

    Returns:
        Transform node path as a string.
    """
    if isinstance(node, str):
        return node
    # Duck-type: MayaNode exposes .tr; any future wrapper that does the same works too
    tr = getattr(node, "tr", None)
    if tr is not None:
        return str(tr)
    raise TypeError(f"Expected a str or MayaNode-like object, got {type(node)}")


# ---------------------------------------------------------------------------
# Dirty detection  (om2 path – fastest, no MayaNode overhead)
# ---------------------------------------------------------------------------

def get_dirty_reasons(
    dag_path: maya.api.OpenMaya.MDagPath,
    tol: float = 1e-5,
) -> Dict[str, bool]:
    """
    Inspect a single DAG transform node for non-identity transform values.

    Pivots in Maya are subtle: moving a rotatePivot causes Maya to silently
    add a rotatePivotTranslate to keep the geometry in place.  Both values
    are checked so the result reflects the true data state, not just the
    visual result.

    Args:
        dag_path: MDagPath pointing to a transform node.
        tol: Floating-point comparison tolerance.

    Returns:
        dict with three boolean keys:
            dirty  – True when any value is non-identity.
            matrix – True when translate / rotate / scale / shear is off.
            pivot  – True when any pivot or compensate-translate is non-zero.

    Example:
        >>> dag = iterator.getPath()
        >>> reasons = get_dirty_reasons(dag)
        >>> if reasons["matrix"]:
        ...     freeze_node(dag.fullPathName())
    """
    fn = maya.api.OpenMaya.MFnTransform(dag_path)
    tm = fn.transformation()

    t  = tm.translation(maya.api.OpenMaya.MSpace.kTransform)
    r  = tm.rotation(asQuaternion=True)
    s  = tm.scale(maya.api.OpenMaya.MSpace.kTransform)
    sh = tm.shear(maya.api.OpenMaya.MSpace.kTransform)

    rp  = fn.rotatePivot(maya.api.OpenMaya.MSpace.kTransform)
    sp  = fn.scalePivot(maya.api.OpenMaya.MSpace.kTransform)
    # Maya compensate-translates: non-zero whenever the user has moved a pivot
    rpt = fn.rotatePivotTranslation(maya.api.OpenMaya.MSpace.kTransform)
    spt = fn.scalePivotTranslation(maya.api.OpenMaya.MSpace.kTransform)

    # Quaternion: for identity, x/y/z == 0 (w is ±1, irrelevant for dirtiness)
    matrix_dirty = (
        any(abs(v)       > tol for v in [t.x, t.y, t.z])
        or any(abs(v)    > tol for v in [r.x, r.y, r.z])
        or any(abs(v-1.) > tol for v in s)
        or any(abs(v)    > tol for v in sh)
    )

    pivot_dirty = (
        any(abs(v) > tol for v in [rp.x,  rp.y,  rp.z])
        or any(abs(v) > tol for v in [sp.x,  sp.y,  sp.z])
        or any(abs(v) > tol for v in [rpt.x, rpt.y, rpt.z])
        or any(abs(v) > tol for v in [spt.x, spt.y, spt.z])
    )

    return {
        "dirty" : matrix_dirty or pivot_dirty,
        "matrix": matrix_dirty,
        "pivot" : pivot_dirty,
    }


def build_dirty_cache(
    root: Optional[str] = None,
    tol: float = 1e-5,
) -> Tuple[Dict[str, Dict[str, bool]], Dict]:
    """
    Traverse the DAG and build flat + nested dirty caches in one pass.

    Args:
        root: Optional DAG fullpath string to limit the scan (e.g. '|rig').
              When None the entire scene is traversed.
        tol: Tolerance forwarded to get_dirty_reasons.

    Returns:
        Tuple (flat, nested):
            flat   – {fullpath: dirty_reasons_dict}
            nested – Tree dict mirroring the DAG; each leaf stores its data
                     under the '__dirty__' key; children are sibling keys.

    Example:
        >>> flat, nested = build_dirty_cache(root="|rig")
        >>> print([p for p, r in flat.items() if r["dirty"]])
    """
    it = maya.api.OpenMaya.MItDag(
        maya.api.OpenMaya.MItDag.kDepthFirst,
        maya.api.OpenMaya.MFn.kTransform,
    )

    if root:
        sel = maya.api.OpenMaya.MSelectionList()
        sel.add(root)
        it.reset(
            sel.getDagPath(0),
            maya.api.OpenMaya.MItDag.kDepthFirst,
            maya.api.OpenMaya.MFn.kTransform,
        )

    flat: Dict[str, Dict[str, bool]] = {}
    nested: Dict = {}

    while not it.isDone():
        dag      = it.getPath()
        fullpath = dag.fullPathName()
        reasons  = get_dirty_reasons(dag, tol)

        flat[fullpath] = reasons
        _insert_nested(nested, fullpath, reasons)
        it.next()

    return flat, nested


def _insert_nested(cache: Dict, fullpath: str, value: Dict[str, bool]) -> None:
    """
    Insert a fullpath and its dirty data into a nested dict mirroring the DAG.

    Children are stored as sibling keys; the node's own data lives under
    the reserved '__dirty__' key to avoid clashing with child node names.
    """
    parts = [p for p in fullpath.split("|") if p]
    node  = cache

    for part in parts[:-1]:
        node = node.setdefault(part, {})

    leaf = node.setdefault(parts[-1], {})
    leaf["__dirty__"] = value


def get_subtree(nested: Dict, *path: str) -> Dict:
    """
    Navigate the nested cache to a specific ancestor node.

    Args:
        nested: The nested cache from build_dirty_cache.
        *path: Short node names forming the path (e.g. 'rig', 'offset_grp').

    Returns:
        Sub-dict at that position, or {} when the path does not exist.

    Example:
        >>> sub = get_subtree(nested, "rig", "offset_grp", "arm_grp")
    """
    node = nested
    for key in path:
        node = node.get(key, {})
    return node


def dirty_in_subtree(nested: Dict, *path: str) -> List[str]:
    """
    Collect fullpaths of all dirty nodes under a given ancestor.

    Args:
        nested: The nested cache from build_dirty_cache.
        *path: Short node names leading to the ancestor node.

    Returns:
        List of dirty fullpath strings.

    Example:
        >>> dirty = dirty_in_subtree(nested, "rig", "deform_grp")
    """
    sub   = get_subtree(nested, *path)
    found: List[str] = []
    _walk_dirty(sub, "|".join(path), found)
    return found


def _walk_dirty(node: Dict, prefix: str, acc: List[str]) -> None:
    """Recursively collect dirty fullpaths from the nested cache."""
    for key, val in node.items():
        if key == "__dirty__":
            continue
        fullpath = f"{prefix}|{key}" if prefix else key
        # '__dirty__' holds a dict – check its inner 'dirty' bool, not the dict itself
        if val.get("__dirty__", {}).get("dirty", False):
            acc.append(fullpath)
        _walk_dirty(val, fullpath, acc)


# ---------------------------------------------------------------------------
# Attribute state context manager
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def unlocked_attrs(
    node: Union[str, Any],
    attrs: List[str],
) -> Generator[Dict[str, Any], None, None]:
    """
    Temporarily unlock and unhide attributes, then restore their original state.

    Pipeline rigs often lock or hide transform channels to protect published
    data.  This context manager saves the full lock / keyable / channelBox
    state, opens the attributes for the duration of the block, and restores
    every flag on exit – even if an exception occurs.

    Accepts either a plain string path or a MayaNode-like object (duck-typed).

    Args:
        node: Maya node name / fullpath, or any object with a ``.tr`` property
              (e.g. a MayaNode instance).
        attrs: Short attribute names to manage (e.g. ['tx', 'ty', 'tz']).

    Yields:
        dict mapping each attribute name to its saved state dict.

    Example:
        >>> with unlocked_attrs("arm_grp", ["tx", "ty", "tz"]):
        ...     cmds.makeIdentity("arm_grp", apply=True, translate=True)

        >>> import dw_maya.dw_maya_nodes as dwn
        >>> mn = dwn.MayaNode("arm_grp")
        >>> with unlocked_attrs(mn, ["tx", "ty", "tz"]):
        ...     cmds.makeIdentity(mn.tr, apply=True, translate=True)
    """
    node_path = _resolve_transform(node)
    saved: Dict[str, Dict[str, Any]] = {}

    for attr in attrs:
        path = f"{node_path}.{attr}"
        if not cmds.objExists(path):
            continue
        saved[attr] = {
            "lock"   : cmds.getAttr(path, lock=True),
            "keyable": cmds.getAttr(path, keyable=True),
            "cb"     : cmds.getAttr(path, channelBox=True),
        }
        if saved[attr]["lock"]:
            cmds.setAttr(path, lock=False)

    try:
        yield saved
    finally:
        for attr, state in saved.items():
            path = f"{node_path}.{attr}"
            if not cmds.objExists(path):
                continue
            try:
                cmds.setAttr(path, lock=state["lock"])
                # Keyable and channelBox only matter when the attr is unlocked
                if not state["lock"]:
                    cmds.setAttr(path, keyable=state["keyable"])
                    if not state["keyable"]:
                        cmds.setAttr(path, channelBox=state["cb"])
            except Exception as exc:
                cmds.warning(f"Could not restore {path}: {exc}")


# ---------------------------------------------------------------------------
# Fix helpers
# ---------------------------------------------------------------------------

def is_constrained(node: Union[str, Any]) -> bool:
    """
    Return True if any translate or rotate channel has an incoming connection.

    Uses MAttr from dw_maya_nodes (lazily imported) for a clean per-attribute
    connection query through the wrapper API.  Falls back to cmds on import
    error so the function works even outside a full dw_maya_nodes install.

    Args:
        node: Maya node name / fullpath, or a MayaNode-like object.

    Returns:
        True when at least one channel has a source connection.

    Example:
        >>> if is_constrained("|rig|arm_grp"):
        ...     print("Skipping constrained node")
    """
    node_path = _resolve_transform(node)

    # Lazy import: MAttr (attr.py) has no dw_maya_utils dependency, so it is
    # safe to import here without triggering a circular import.
    try:
        from dw_maya.dw_maya_nodes.attr import MAttr
        for attr_name in _DRIVEN_ATTRS:
            mattr = MAttr(node_path, attr_name)
            if mattr.listConnections(source=True, destination=False):
                return True
        return False
    except Exception:
        # Fallback: plain cmds query (always available)
        for attr_name in _DRIVEN_ATTRS:
            if cmds.listConnections(
                f"{node_path}.{attr_name}", source=True, destination=False
            ):
                return True
        return False


def freeze_node(node: Union[str, Any]) -> bool:
    """
    Apply makeIdentity (Freeze Transforms) on a node, bypassing locked attrs.

    Saves the lock / keyable / channelBox state of all matrix attributes,
    unlocks them, runs makeIdentity, then restores original states.

    Accepts either a plain string path or a MayaNode-like object.

    Note:
        Processing order matters in a hierarchy: freezing a parent changes
        the world positions of its children.  Call fix_hierarchy to handle
        a full subtree in correct top-down order.

    Args:
        node: Maya node name / fullpath, or a MayaNode-like object.

    Returns:
        True on success, False when an exception occurred (warning is emitted).

    Example:
        >>> freeze_node("|rig|offset_grp|arm_grp")

        >>> import dw_maya.dw_maya_nodes as dwn
        >>> freeze_node(dwn.MayaNode("|rig|offset_grp|arm_grp"))
    """
    node_path = _resolve_transform(node)
    try:
        with unlocked_attrs(node_path, _MATRIX_ATTRS):
            cmds.makeIdentity(
                node_path,
                apply=True,
                translate=True,
                rotate=True,
                scale=True,
                normal=False,
                preserveNormals=True,
            )
        return True
    except Exception as exc:
        cmds.warning(f"freeze_node failed on {node_path}: {exc}")
        return False


def reset_node_pivot(node: Union[str, Any]) -> bool:
    """
    Zero out all pivot and pivot-compensate attributes, bypassing locked attrs.

    Handles rotatePivot, scalePivot and their compensate-translate counterparts
    (rotatePivotTranslate, scalePivotTranslate) that Maya inserts automatically
    when a user repositions a pivot.

    Accepts either a plain string path or a MayaNode-like object.

    Args:
        node: Maya node name / fullpath, or a MayaNode-like object.

    Returns:
        True on success, False when an exception occurred (warning is emitted).

    Example:
        >>> reset_node_pivot("|rig|offset_grp|arm_grp")

        >>> import dw_maya.dw_maya_nodes as dwn
        >>> reset_node_pivot(dwn.MayaNode("|rig|offset_grp|arm_grp"))
    """
    node_path = _resolve_transform(node)
    try:
        with unlocked_attrs(node_path, _PIVOT_ATTRS):
            # Zero both rotate and scale pivots together
            cmds.xform(node_path, pivots=[0, 0, 0], worldSpace=False)
            # Explicitly zero the compensate translates which xform does not touch
            for attr in ("rptx", "rpty", "rptz", "sptx", "spty", "sptz"):
                path = f"{node_path}.{attr}"
                if cmds.objExists(path):
                    cmds.setAttr(path, 0.0)
        return True
    except Exception as exc:
        cmds.warning(f"reset_node_pivot failed on {node_path}: {exc}")
        return False


def fix_node(
    node: Union[str, Any],
    fix_matrix: bool = True,
    fix_pivot: bool = True,
) -> Dict[str, bool]:
    """
    Apply selected fixes to a single node.

    Accepts either a plain string path or a MayaNode-like object.

    Args:
        node: Maya node name / fullpath, or a MayaNode-like object.
        fix_matrix: When True, call freeze_node.
        fix_pivot: When True, call reset_node_pivot.

    Returns:
        dict with 'matrix' and 'pivot' keys, each True when the operation
        succeeded (or was not requested).

    Example:
        >>> result = fix_node("|rig|arm_grp", fix_matrix=True, fix_pivot=True)
        >>> print(result)  # {'matrix': True, 'pivot': True}

        >>> import dw_maya.dw_maya_nodes as dwn
        >>> fix_node(dwn.MayaNode("|rig|arm_grp"))
    """
    result: Dict[str, bool] = {"matrix": True, "pivot": True}

    if fix_matrix:
        result["matrix"] = freeze_node(node)

    if fix_pivot:
        result["pivot"] = reset_node_pivot(node)

    return result


def get_fixable_dirty(
    node: Union[str, Any],
    reasons: Dict[str, bool],
    tol: float = 1e-5,
) -> Dict[str, bool]:
    """
    For a constrained node, determine which dirty aspects can still be fixed.

    Standard Maya constraints (parent, point, orient, aim) drive translate
    and/or rotate channels.  They do NOT drive shear or pivot attributes.
    Scale constraints are checked separately per channel.

    Shear values on a constrained node are a common production issue: they
    often come from a parent with non-uniform scale + rotation, or from
    direct modelling edits.  They can always be zeroed safely.

    Args:
        node:    Node path or MayaNode-like object.
        reasons: Dirty-reasons dict from get_dirty_reasons.
        tol:     Tolerance for value checks.

    Returns:
        dict with boolean keys:
            shear – dirty shear that can be zeroed directly.
            pivot – dirty pivot / compensate-translate (always fixable).
            scale – dirty scale that is NOT driven by a scaleConstraint.

    Example:
        >>> flat, _ = build_dirty_cache("|rig")
        >>> for path, reasons in flat.items():
        ...     if reasons["dirty"] and is_constrained(path):
        ...         fixable = get_fixable_dirty(path, reasons)
        ...         if any(fixable.values()):
        ...             fix_constrained_node(path)
    """
    node_path = _resolve_transform(node)
    result: Dict[str, bool] = {"shear": False, "pivot": False, "scale": False}

    if not reasons["dirty"]:
        return result

    # Shear: check each component directly
    for attr in _SHEAR_ATTRS:
        try:
            if abs(cmds.getAttr(f"{node_path}.{attr}")) > tol:
                result["shear"] = True
                break
        except Exception:
            pass

    # Pivot: already computed by get_dirty_reasons
    result["pivot"] = reasons["pivot"]

    # Scale: dirty AND not driven by a scaleConstraint
    if reasons["matrix"]:
        scale_driven = any(
            cmds.listConnections(f"{node_path}.{a}", source=True, destination=False)
            for a in _SCALE_ATTRS
        )
        if not scale_driven:
            try:
                sv = cmds.getAttr(f"{node_path}.scale")
                vals = sv[0] if isinstance(sv, list) else sv
                result["scale"] = any(abs(v - 1.0) > tol for v in vals)
            except Exception:
                pass

    return result


def fix_constrained_node(
    node: Union[str, Any],
    fix_shear: bool = True,
    fix_pivot: bool = True,
    fix_scale: bool = False,
) -> Dict[str, bool]:
    """
    Partially fix a constrained node — only channels NOT driven by the constraint.

    Standard Maya constraints drive translate and/or rotate.  This function
    leaves those channels alone while safely zeroing shear, pivots and
    optionally scale (when not driven by a scaleConstraint).

    Shear is zeroed via direct setAttr rather than makeIdentity so that
    translate/rotate are guaranteed untouched.
    Scale uses makeIdentity(scale=True, translate=False, rotate=False).
    Pivots use the same reset_node_pivot path as the unconstrained fix.
    All operations honour the unlocked_attrs context manager so locked /
    hidden attributes are temporarily bypassed and then restored.

    Args:
        node:      Node path or MayaNode-like object.
        fix_shear: Zero shearXY / shearXZ / shearYZ.
        fix_pivot: Reset rotatePivot, scalePivot and their compensates.
        fix_scale: Freeze scale only (skipped automatically if scale is driven).
                   Defaults to False — enable explicitly when needed.

    Returns:
        dict {'shear': bool, 'pivot': bool, 'scale': bool}
        Values are True when the operation succeeded or was not requested.

    Example:
        >>> fix_constrained_node("|rig|arm_L_grp", fix_shear=True, fix_pivot=True)

        >>> import dw_maya.dw_maya_nodes as dwn
        >>> fix_constrained_node(dwn.MayaNode("|rig|arm_L_grp"))
    """
    node_path = _resolve_transform(node)
    result: Dict[str, bool] = {"shear": True, "pivot": True, "scale": True}

    # Zero shear via direct setAttr — guaranteed not to touch translate/rotate
    if fix_shear:
        try:
            with unlocked_attrs(node_path, _SHEAR_ATTRS):
                for attr in _SHEAR_ATTRS:
                    path = f"{node_path}.{attr}"
                    if cmds.objExists(path):
                        cmds.setAttr(path, 0.0)
        except Exception as exc:
            cmds.warning(f"fix_constrained_node shear failed on {node_path}: {exc}")
            result["shear"] = False

    # Reset pivots — safe on constrained nodes (pivots are never constraint targets)
    if fix_pivot:
        result["pivot"] = reset_node_pivot(node_path)

    # Scale — only when explicitly requested and not driven
    if fix_scale:
        scale_driven = any(
            cmds.listConnections(f"{node_path}.{a}", source=True, destination=False)
            for a in _SCALE_ATTRS
        )
        if scale_driven:
            cmds.warning(
                f"fix_constrained_node: scale is driven on '{node_path}', skipping."
            )
            result["scale"] = False
        else:
            try:
                with unlocked_attrs(node_path, _SCALE_ATTRS):
                    cmds.makeIdentity(
                        node_path,
                        apply=True,
                        translate=False,
                        rotate=False,
                        scale=True,
                        normal=False,
                        preserveNormals=True,
                    )
            except Exception as exc:
                cmds.warning(f"fix_constrained_node scale failed on {node_path}: {exc}")
                result["scale"] = False

    return result


def fix_hierarchy(
    root: Optional[Union[str, Any]] = None,
    fix_matrix: bool = True,
    fix_pivot: bool = True,
    skip_constrained: bool = True,
    tol: float = 1e-5,
) -> Dict[str, Dict[str, bool]]:
    """
    Scan a hierarchy and fix all dirty transform nodes in top-down order.

    Processes nodes depth-first (parent before child) so that a parent freeze
    does not invalidate the dirty state of already-processed children.
    Nodes with incoming connections on translate / rotate channels are skipped
    when skip_constrained is True (see is_constrained).

    Accepts either a plain string path or a MayaNode-like object as root.

    Args:
        root: DAG fullpath to start from.  When None the full scene is scanned.
              May be a plain string or a MayaNode-like object.
        fix_matrix: Apply freeze transforms on nodes with dirty matrix values.
        fix_pivot: Reset pivots on nodes with dirty pivot values.
        skip_constrained: Skip nodes whose transform channels are driven
                          externally (constraints, rigs, etc.).
        tol: Tolerance for dirty detection forwarded to build_dirty_cache.

    Returns:
        dict mapping fullpath -> {'matrix': bool, 'pivot': bool} for every
        node that was processed.  Skipped nodes are absent from the result.

    Example:
        >>> report = fix_hierarchy("|rig", skip_constrained=True)
        >>> failed = {n: r for n, r in report.items() if not all(r.values())}

        >>> import dw_maya.dw_maya_nodes as dwn
        >>> fix_hierarchy(dwn.MayaNode("|rig"))
    """
    root_path = _resolve_transform(root) if root is not None else None
    flat, _   = build_dirty_cache(root_path, tol)
    report: Dict[str, Dict[str, bool]] = {}

    # flat is ordered depth-first (parent before child) because MItDag is
    # kDepthFirst and Python 3.7+ dicts preserve insertion order.
    for fullpath, reasons in flat.items():
        if not reasons["dirty"]:
            continue

        if skip_constrained and is_constrained(fullpath):
            cmds.warning(f"fix_hierarchy: skipping constrained node '{fullpath}'")
            continue

        needs_matrix = fix_matrix and reasons["matrix"]
        needs_pivot  = fix_pivot  and reasons["pivot"]

        if needs_matrix or needs_pivot:
            report[fullpath] = fix_node(fullpath, needs_matrix, needs_pivot)

    return report

