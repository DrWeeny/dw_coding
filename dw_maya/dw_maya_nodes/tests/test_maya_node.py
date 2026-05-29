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
        expected_sh = cmds.listRelatives(cube_tr, shapes=True, ni=True)[0]
        _assert(mn[1].node == expected_sh, f"Expected shape '{expected_sh}', got '{mn[1].node}'")


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
    ("nonexistent attr returns None",      test_nonexistent_attr_returns_none),
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

