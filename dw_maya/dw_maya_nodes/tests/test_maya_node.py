"""Maya in-session test suite for MayaNode and MAttr.

Designed to be run INSIDE Maya (Script Editor or via maya.standalone).
Does NOT require pytest — uses a minimal self-contained runner so it works
even without a test framework installed in Maya's Python environment.

Usage (Script Editor):
    import importlib
    import dw_maya.dw_maya_nodes.tests.test_maya_node as t
    importlib.reload(t)
    t.run()

Each test function:
    - Creates its own nodes in a dedicated namespace / group.
    - Cleans up after itself (even on failure).
    - Prints PASS / FAIL with a short description.
"""

from __future__ import annotations

import traceback
from contextlib import contextmanager
from typing import Callable, List, Tuple

from maya import cmds

from dw_maya.dw_maya_nodes import MayaNode
from dw_maya.dw_maya_nodes.attr import MAttr

# ---------------------------------------------------------------------------
# Minimal in-Maya test runner
# ---------------------------------------------------------------------------

_RESULTS: List[Tuple[str, bool, str]] = []


def _assert(condition: bool, msg: str = "") -> None:
    if not condition:
        raise AssertionError(msg or "Assertion failed")


@contextmanager
def _tmp_nodes(*node_creators):
    """Context manager that creates nodes and deletes them on exit."""
    created = []
    try:
        for creator in node_creators:
            result = creator()
            if isinstance(result, (list, tuple)):
                created.extend(result)
            elif result:
                created.append(result)
        yield created
    finally:
        existing = [n for n in created if cmds.objExists(n)]
        if existing:
            cmds.delete(existing)


def _test(fn: Callable) -> Callable:
    """Decorator: registers a test function."""
    _RESULTS  # ensure module-level list is used
    return fn


def _run_test(name: str, fn: Callable) -> bool:
    try:
        fn()
        print(f"  [PASS]  {name}")
        _RESULTS.append((name, True, ""))
        return True
    except Exception as e:
        tb = traceback.format_exc().strip().splitlines()[-1]
        print(f"  [FAIL]  {name}")
        print(f"          {tb}")
        _RESULTS.append((name, False, str(e)))
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cube(name="dw_test_cube"):
    result = cmds.polyCube(name=name)
    return result[0]  # transform name


def _make_sphere(name="dw_test_sphere"):
    result = cmds.polySphere(name=name)
    return result[0]


def _make_cluster(mesh):
    cluster, handle = cmds.cluster(mesh)
    return cluster, handle


# ---------------------------------------------------------------------------
# ── MayaNode Tests ──────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

def test_tr_sh_resolution():
    """node[0] = transform, node[1] = shape."""
    with _tmp_nodes(lambda: _make_cube("dw_trsh_cube")) as nodes:
        cube_tr = nodes[0]
        mn = MayaNode(cube_tr)
        _assert(mn[0].node == cube_tr, f"Expected transform '{cube_tr}', got '{mn[0].node}'")
        # .sh resolves to a full DAG path on purpose (unambiguous); compare leaf names.
        expected_sh = cmds.listRelatives(cube_tr, shapes=True, ni=True)[0]
        got_sh = mn[1].node.split('|')[-1]
        _assert(got_sh == expected_sh, f"Expected shape '{expected_sh}', got '{got_sh}'")


def test_shortname_attr_access():
    """cube.tx should resolve to the transform's translateX."""
    with _tmp_nodes(lambda: _make_cube("dw_tx_cube")) as nodes:
        mn = MayaNode(nodes[0])
        attr = mn.tx
        _assert(isinstance(attr, MAttr), f"Expected MAttr, got {type(attr)}")
        # After auto-switch, node should be the transform
        _assert(mn.node == nodes[0], f"Node should have switched to transform, got '{mn.node}'")


def test_longname_attr_access():
    """cube.translateX should work the same as cube.tx."""
    with _tmp_nodes(lambda: _make_cube("dw_longname_cube")) as nodes:
        mn = MayaNode(nodes[0])
        attr = mn.translateX
        _assert(isinstance(attr, MAttr), f"Expected MAttr, got {type(attr)}")


def test_setattr_numeric():
    """cube.tx = 5 should set translateX to 5.0."""
    with _tmp_nodes(lambda: _make_cube("dw_set_cube")) as nodes:
        mn = MayaNode(nodes[0])
        mn.tx = 5
        result = cmds.getAttr(f"{nodes[0]}.translateX")
        _assert(abs(result - 5.0) < 1e-5, f"Expected 5.0, got {result}")


def test_setattr_via_MAttr():
    """cube.tx.setAttr(7) should set translateX to 7.0."""
    with _tmp_nodes(lambda: _make_cube("dw_mattr_set_cube")) as nodes:
        mn = MayaNode(nodes[0])
        mn.tx.setAttr(7)
        result = cmds.getAttr(f"{nodes[0]}.translateX")
        _assert(abs(result - 7.0) < 1e-5, f"Expected 7.0, got {result}")


def test_getattr_via_MAttr():
    """cube.tx.getAttr() should return the current translateX value."""
    with _tmp_nodes(lambda: _make_cube("dw_mattr_get_cube")) as nodes:
        cmds.setAttr(f"{nodes[0]}.translateX", 3.5)
        mn = MayaNode(nodes[0])
        value = mn.tx.getAttr()
        _assert(abs(value - 3.5) < 1e-5, f"Expected 3.5, got {value}")


def test_shape_priority_visibility():
    """cube.visibility — exists on both tr and sh; default (item=1) should use shape."""
    with _tmp_nodes(lambda: _make_cube("dw_vis_cube")) as nodes:
        mn = MayaNode(nodes[0])
        attr = mn.visibility
        _assert(isinstance(attr, MAttr), "visibility should return MAttr")
        # The node could be either tr or sh since visibility lives on both; just ensure no crash


def test_force_transform_index():
    """cube[0].visibility should target the transform explicitly."""
    with _tmp_nodes(lambda: _make_cube("dw_idx0_cube")) as nodes:
        mn = MayaNode(nodes[0])
        attr = mn[0].visibility
        _assert(isinstance(attr, MAttr), "visibility via index 0 should return MAttr")
        _assert(mn.node == nodes[0], f"Expected transform after [0], got '{mn.node}'")


def test_connect_attrs():
    """cube.tx >> sphere.tx should create a connection."""
    with _tmp_nodes(
        lambda: _make_cube("dw_conn_cube"),
        lambda: _make_sphere("dw_conn_sphere"),
    ) as nodes:
        cube_tr, sphere_tr = nodes[0], nodes[1]
        mn_cube = MayaNode(cube_tr)
        mn_sphere = MayaNode(sphere_tr)
        mn_cube.tx >> mn_sphere.tx
        conn = cmds.listConnections(f"{sphere_tr}.translateX", source=True, plugs=True)
        _assert(conn and f"{cube_tr}.translateX" in conn,
                f"Connection not found. Got: {conn}")


def test_listattr_positional():
    """listAttr('tx') positional should find tx on the transform."""
    with _tmp_nodes(lambda: _make_cube("dw_listattr_cube")) as nodes:
        mn = MayaNode(nodes[0])
        result = mn.listAttr("tx")
        _assert("tx" in result, f"Expected 'tx' in listAttr result, got: {result}")


def test_listattr_keyword():
    """listAttr(attr='tx') keyword should find tx on the transform."""
    with _tmp_nodes(lambda: _make_cube("dw_listattr_kw_cube")) as nodes:
        mn = MayaNode(nodes[0])
        result = mn.listAttr(attr="tx")
        _assert("tx" in result, f"Expected 'tx' in listAttr result, got: {result}")


def test_listattr_node_index_0():
    """listAttr(node_index=0) should return transform attributes."""
    with _tmp_nodes(lambda: _make_cube("dw_ni0_cube")) as nodes:
        mn = MayaNode(nodes[0])
        result = mn.listAttr(node_index=0)
        _assert("tx" in result or "translateX" in result,
                "'tx'/'translateX' should be in transform attr list")


def test_listattr_node_index_1():
    """listAttr(node_index=1) should return shape attributes."""
    with _tmp_nodes(lambda: _make_cube("dw_ni1_cube")) as nodes:
        mn = MayaNode(nodes[0])
        result = mn.listAttr(node_index=1)
        # 'outMesh' is a shape-only attribute
        _assert("outMesh" in result or "o" in result,
                "'outMesh' should be in shape attr list")


def test_nonexistent_attr_returns_none():
    """Accessing a non-existent attr should warn and return None (not crash)."""
    with _tmp_nodes(lambda: _make_cube("dw_nonexist_cube")) as nodes:
        mn = MayaNode(nodes[0])
        result = mn.thisAttrDefinitelyDoesNotExist123
        _assert(result is None, f"Expected None for missing attr, got {result}")


# ---------------------------------------------------------------------------
# ── Joint / Group / Multi-shape Tests ───────────────────────────────────────
# ---------------------------------------------------------------------------

def test_tr_joint_direct():
    """A standalone joint: mn.tr must return the joint itself, not None or a parent.

    Joints have nodeType 'joint', not 'transform', but they ARE transforms.
    The tr property must treat them as such.
    """
    jnt = None
    try:
        cmds.select(clear=True)
        jnt = cmds.joint(name="dw_single_joint")
        mn = MayaNode(jnt)
        result = mn.tr
        _assert(result is not None, "standalone joint: tr must not return None")
        leaf = result.split('|')[-1].split(':')[-1]
        _assert(leaf == jnt,
                f"Expected '{jnt}', tr returned '{result}' (leaf='{leaf}')")
    finally:
        if jnt and cmds.objExists(jnt):
            cmds.delete(jnt)


def test_tr_joint_in_hierarchy():
    """EX_ joint parented under GH_ joint: tr must return EX_, not GH_ or any ancestor."""
    gh = None
    try:
        cmds.select(clear=True)
        gh = cmds.joint(name="dw_GH_jnt")
        cmds.select(clear=True)
        ex = cmds.joint(name="dw_EX_jnt")
        cmds.parent(ex, gh)

        mn = MayaNode(ex)
        result = mn.tr
        _assert(result is not None, "child joint: tr must not return None")
        leaf = result.split('|')[-1].split(':')[-1]
        _assert(leaf == ex,
                f"Expected '{ex}', tr returned '{result}' (leaf='{leaf}')")
    finally:
        if gh and cmds.objExists(gh):
            cmds.delete(gh)  # also removes ex


def test_tr_group_no_shape():
    """Empty group (transform with no shape): tr must return the group itself."""
    grp = None
    try:
        grp = cmds.group(empty=True, name="dw_empty_grp")
        mn = MayaNode(grp)
        result = mn.tr
        _assert(result is not None, "empty group: tr must not return None")
        leaf = result.split('|')[-1].split(':')[-1]
        _assert(leaf == grp,
                f"Expected '{grp}', tr returned '{result}' (leaf='{leaf}')")
    finally:
        if grp and cmds.objExists(grp):
            cmds.delete(grp)


def test_tr_curve_multi_shape():
    """Transform owning two curve shapes: tr returns the transform, sh a valid shape."""
    crv1 = crv2 = None
    try:
        crv1 = cmds.curve(d=1, p=[(0, 0, 0), (1, 0, 0)], name="dw_multi_crv1")
        crv2 = cmds.curve(d=1, p=[(0, 0, 0), (0, 1, 0)], name="dw_multi_crv2")
        sh2 = cmds.listRelatives(crv2, shapes=True)[0]
        cmds.parent(sh2, crv1, add=True, shape=True)
        cmds.delete(crv2)
        crv2 = None

        mn = MayaNode(crv1)
        result_tr = mn.tr
        result_sh = mn.sh

        _assert(result_tr is not None, "multi-shape curve: tr must not be None")
        leaf_tr = result_tr.split('|')[-1].split(':')[-1]
        _assert(leaf_tr == crv1,
                f"Expected transform '{crv1}', tr returned '{result_tr}'")

        _assert(result_sh is not None, "multi-shape curve: sh must not be None")
        all_shapes = cmds.listRelatives(crv1, shapes=True, ni=True) or []
        sh_leaves = {s.split('|')[-1].split(':')[-1] for s in all_shapes}
        result_sh_leaf = result_sh.split('|')[-1].split(':')[-1]
        _assert(result_sh_leaf in sh_leaves,
                f"sh '{result_sh}' not among shapes {all_shapes}")
    finally:
        for n in [crv1, crv2]:
            if n and cmds.objExists(n):
                cmds.delete(n)


def test_multi_shape_indexing():
    """Transform with two shapes: node[1]=first, node[2]=second, shapes() lists both."""
    crv1 = crv2 = None
    try:
        crv1 = cmds.curve(d=1, p=[(0, 0, 0), (1, 0, 0)], name="dw_idx_crv1")
        crv2 = cmds.curve(d=1, p=[(0, 0, 0), (0, 1, 0)], name="dw_idx_crv2")
        sh2 = cmds.listRelatives(crv2, shapes=True)[0]
        cmds.parent(sh2, crv1, add=True, shape=True)
        cmds.delete(crv2)
        crv2 = None

        expected = cmds.listRelatives(crv1, shapes=True, ni=True, fullPath=True) or []
        _assert(len(expected) == 2, f"setup: expected 2 shapes, got {expected}")

        mn = MayaNode(crv1)

        # shapes() / list_shapes() return every shape, in Maya order.
        shapes = mn.shapes()
        _assert(shapes == expected, f"shapes() = {shapes}, expected {expected}")
        _assert(mn.list_shapes() == expected, "list_shapes() must alias shapes()")

        # node[1] = first shape (== .sh), node[2] = second shape.
        first = mn[1].node.split('|')[-1]
        second = mn[2].node.split('|')[-1]
        _assert(first == expected[0].split('|')[-1],
                f"node[1] = '{first}', expected '{expected[0]}'")
        _assert(second == expected[1].split('|')[-1],
                f"node[2] = '{second}', expected '{expected[1]}'")
        _assert(first != second, "node[1] and node[2] must differ")

        # .sh stays the first shape regardless of index history.
        _assert(mn.sh.split('|')[-1] == expected[0].split('|')[-1],
                f".sh = '{mn.sh}', expected first shape '{expected[0]}'")
    finally:
        for n in [crv1, crv2]:
            if n and cmds.objExists(n):
                cmds.delete(n)


def test_multi_shape_index_out_of_range():
    """An out-of-range shape index falls back to the first shape (no crash)."""
    with _tmp_nodes(lambda: _make_cube("dw_oor_cube")) as nodes:
        mn = MayaNode(nodes[0])
        first_sh = cmds.listRelatives(nodes[0], shapes=True, ni=True, fullPath=True)[0]
        # only one shape exists; node[5] must not raise, falls back to first shape
        result = mn[5].node
        _assert(result.split('|')[-1] == first_sh.split('|')[-1],
                f"out-of-range index should fall back to first shape, got '{result}'")


def test_tr_joint_under_shaped_parent_regression():
    """Regression: joint.tr must NOT walk up to a shaped ancestor.

    Before the fix, nodeType('joint') != 'transform' caused the tr property to
    fall into the shape-walking path.  It would walk up the DAG until it found a
    parent *with a shape* and return THAT parent — e.g. EXO_DYN — instead of the
    joint.  This caused the assembly node to be added to the skin cluster as an
    influence (the CHECK SKIN INFLUENCES error).

    Simulated hierarchy:
        dw_exo_loc  (locator = transform + shape)
          └─ dw_reg_GH_jnt  (joint)
               └─ dw_reg_EX_jnt  (joint)  ← mn.tr must return this
    """
    exo = None
    try:
        exo = cmds.spaceLocator(name="dw_exo_loc")[0]
        cmds.select(clear=True)
        gh = cmds.joint(name="dw_reg_GH_jnt")
        cmds.parent(gh, exo)
        cmds.select(clear=True)
        ex = cmds.joint(name="dw_reg_EX_jnt")
        cmds.parent(ex, gh)

        mn = MayaNode(ex)
        result = mn.tr
        _assert(result is not None, "EX joint.tr must not return None")
        leaf = result.split('|')[-1].split(':')[-1]
        _assert(leaf == ex,
                f"REGRESSION (EXO_DYN bug): joint.tr returned '{result}' "
                f"(leaf='{leaf}') instead of '{ex}'. The shaped ancestor "
                f"'{exo}' was incorrectly returned.")
    finally:
        if exo and cmds.objExists(exo):
            cmds.delete(exo)  # also removes gh and ex


# ---------------------------------------------------------------------------
# ── MAttr Tests ─────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

def test_mattr_compound_indexing():
    """cluster.weightList[0].weights should be accessible without crash."""
    with _tmp_nodes(
        lambda: _make_cube("dw_cluster_cube"),
    ) as nodes:
        cube_tr = nodes[0]
        cluster, handle = _make_cluster(cube_tr)
        try:
            mn = MayaNode(cluster)
            wl = mn.weightList[0].weights
            _assert(isinstance(wl, MAttr), f"Expected MAttr for weightList[0].weights, got {type(wl)}")
        finally:
            if cmds.objExists(cluster): cmds.delete(cluster)
            if cmds.objExists(handle): cmds.delete(handle)


def test_mattr_rshift_connection():
    """MAttr >> MAttr should connect the attributes."""
    with _tmp_nodes(
        lambda: _make_cube("dw_mattr_conn_cube"),
        lambda: _make_sphere("dw_mattr_conn_sphere"),
    ) as nodes:
        cube_tr, sphere_tr = nodes[0], nodes[1]
        src = MAttr(cube_tr, "translateX")
        dst = MAttr(sphere_tr, "translateX")
        src >> dst
        conn = cmds.listConnections(f"{sphere_tr}.translateX", source=True, plugs=True)
        _assert(conn and f"{cube_tr}.translateX" in conn, f"Connection not found. Got: {conn}")


def test_mattr_eq_operator():
    """MAttr == value should compare the current attribute value."""
    with _tmp_nodes(lambda: _make_cube("dw_eq_cube")) as nodes:
        cmds.setAttr(f"{nodes[0]}.translateX", 42.0)
        attr = MAttr(nodes[0], "translateX")
        _assert(attr == 42.0, f"Expected attr == 42.0, got {attr.getAttr()}")


def test_mattr_bool_zero():
    """MAttr on a zero-value numeric should evaluate to False."""
    with _tmp_nodes(lambda: _make_cube("dw_bool_cube")) as nodes:
        cmds.setAttr(f"{nodes[0]}.translateX", 0.0)
        attr = MAttr(nodes[0], "translateX")
        _assert(not bool(attr), "Zero translateX should be falsy")


def test_mattr_bool_nonzero():
    """MAttr on a non-zero-value numeric should evaluate to True."""
    with _tmp_nodes(lambda: _make_cube("dw_bool_nz_cube")) as nodes:
        cmds.setAttr(f"{nodes[0]}.translateX", 1.0)
        attr = MAttr(nodes[0], "translateX")
        _assert(bool(attr), "Non-zero translateX should be truthy")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_ALL_TESTS = [
    ("tr/sh resolution",                  test_tr_sh_resolution),
    ("short name attr access (tx)",        test_shortname_attr_access),
    ("long name attr access (translateX)", test_longname_attr_access),
    ("setattr numeric (cube.tx = 5)",      test_setattr_numeric),
    ("setattr via MAttr.setAttr(7)",       test_setattr_via_MAttr),
    ("getattr via MAttr.getAttr()",        test_getattr_via_MAttr),
    ("visibility shape priority",          test_shape_priority_visibility),
    ("force transform via [0]",            test_force_transform_index),
    ("connect attrs (>>)",                 test_connect_attrs),
    ("listAttr positional ('tx')",         test_listattr_positional),
    ("listAttr keyword (attr='tx')",       test_listattr_keyword),
    ("listAttr node_index=0 (transform)",  test_listattr_node_index_0),
    ("listAttr node_index=1 (shape)",      test_listattr_node_index_1),
    ("nonexistent attr returns None",                      test_nonexistent_attr_returns_none),
    # --- joint / group / multi-shape ---
    ("joint tr — standalone",                             test_tr_joint_direct),
    ("joint tr — child under parent joint",               test_tr_joint_in_hierarchy),
    ("group tr — empty transform (no shape)",             test_tr_group_no_shape),
    ("curve tr/sh — multi-shape transform",               test_tr_curve_multi_shape),
    ("multi-shape indexing (node[1]/node[2]/shapes())",   test_multi_shape_indexing),
    ("multi-shape index out of range fallback",           test_multi_shape_index_out_of_range),
    ("joint tr — regression: shaped ancestor (EXO_DYN)", test_tr_joint_under_shaped_parent_regression),
    ("MAttr compound indexing",            test_mattr_compound_indexing),
    ("MAttr >> connection",                test_mattr_rshift_connection),
    ("MAttr == operator",                  test_mattr_eq_operator),
    ("MAttr bool (zero = False)",          test_mattr_bool_zero),
    ("MAttr bool (nonzero = True)",        test_mattr_bool_nonzero),
]


def run():
    """Run all MayaNode / MAttr tests and print a summary."""
    _RESULTS.clear()
    print("\n" + "=" * 60)
    print("  MayaNode / MAttr Test Suite")
    print("=" * 60)

    passed = 0
    for name, fn in _ALL_TESTS:
        if _run_test(name, fn):
            passed += 1

    total = len(_ALL_TESTS)
    failed = total - passed
    print("=" * 60)
    print(f"  Result: {passed}/{total} passed", end="")
    print(f"  |  {failed} FAILED" if failed else "  |  All good!")
    print("=" * 60 + "\n")
    return failed == 0

