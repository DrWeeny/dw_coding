"""Maya in-session test suite for the component-based preset API (v2).

Exercises MayaNode.createPreset / applyPreset / savePreset / loadPreset, the
AttributeComponent round-trip, numeric blending, and registry-driven rebuild
via node_from_preset. Mirrors test_maya_node.py: no pytest, self-contained
runner, every test cleans up after itself.

Usage (Script Editor):
    import importlib
    import dw_maya.dw_maya_nodes.tests.test_preset_components as t
    importlib.reload(t)
    t.run()

Author:
    DrWeeny
"""

from __future__ import annotations

import os
import tempfile
import traceback
from contextlib import contextmanager
from typing import Callable, List, Tuple

from maya import cmds

from dw_maya.dw_maya_nodes import MayaNode
from dw_maya.dw_maya_utils.mesh_class import Mesh
import dw_maya.dw_presets_io.preset_components as pcomp

# ---------------------------------------------------------------------------
# Minimal in-Maya test runner
# ---------------------------------------------------------------------------

_RESULTS: List[Tuple[str, bool, str]] = []


def _assert(condition: bool, msg: str = "") -> None:
    if not condition:
        raise AssertionError(msg or "Assertion failed")


def _close(a: float, b: float, tol: float = 1e-4) -> bool:
    return abs(a - b) <= tol


@contextmanager
def _tmp_nodes(*node_creators):
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


@contextmanager
def _tmp_file(suffix=".json"):
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="dw_preset_")
    os.close(fd)
    try:
        yield path
    finally:
        if os.path.exists(path):
            os.remove(path)


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

def _make_cube(name="dw_preset_cube"):
    return cmds.polyCube(name=name)[0]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_preset_shape():
    """createPreset returns {identity: {nodeType, attributes:{transform, shape}}}."""
    with _tmp_nodes(lambda: _make_cube("dw_cp_cube")) as nodes:
        mn = MayaNode(nodes[0])
        preset = mn.createPreset()
        _assert(set(preset.keys()) == {"dw_cp_cube"}, f"bad identity: {list(preset)}")
        body = preset["dw_cp_cube"]
        _assert(body["nodeType"] == "mesh", f"nodeType should be shape type, got {body['nodeType']}")
        attrs = body["attributes"]
        _assert("transform" in attrs and "shape" in attrs,
                f"expected transform+shape roles, got {list(attrs)}")
        _assert("translateX" in attrs["transform"] or "tx" in attrs["transform"],
                "transform attrs missing translateX")


def test_apply_preset_roundtrip():
    """Capture, change the node, re-apply: the value is restored."""
    with _tmp_nodes(lambda: _make_cube("dw_rt_cube")) as nodes:
        mn = MayaNode(nodes[0])
        cmds.setAttr(f"{nodes[0]}.translateX", 7.5)
        preset = mn.createPreset()

        cmds.setAttr(f"{nodes[0]}.translateX", 0.0)
        mn.applyPreset(preset)
        _assert(_close(cmds.getAttr(f"{nodes[0]}.translateX"), 7.5),
                f"expected 7.5, got {cmds.getAttr(f'{nodes[0]}.translateX')}")


def test_blend_half():
    """blend=0.5 lerps between current and stored value."""
    with _tmp_nodes(lambda: _make_cube("dw_blend_cube")) as nodes:
        mn = MayaNode(nodes[0])
        cmds.setAttr(f"{nodes[0]}.translateX", 10.0)
        preset = mn.createPreset()

        cmds.setAttr(f"{nodes[0]}.translateX", 0.0)
        mn.applyPreset(preset, ctx=pcomp.PresetContext(blend=0.5))
        # 10 * 0.5 + 0 * 0.5 = 5
        _assert(_close(cmds.getAttr(f"{nodes[0]}.translateX"), 5.0),
                f"expected 5.0, got {cmds.getAttr(f'{nodes[0]}.translateX')}")


def test_save_load_file():
    """savePreset writes a versioned envelope; loadPreset restores it."""
    with _tmp_nodes(lambda: _make_cube("dw_io_cube")) as nodes, _tmp_file() as path:
        mn = MayaNode(nodes[0])
        cmds.setAttr(f"{nodes[0]}.rotateY", 33.0)
        _assert(mn.savePreset(path) is True, "savePreset returned False")

        import json
        with open(path) as fp:
            raw = json.load(fp)
        _assert(raw.get("format") == pcomp.PRESET_FORMAT, "format key missing/wrong")
        _assert(raw.get("version") == pcomp.PRESET_VERSION, "version key missing/wrong")
        _assert("dw_io_cube" in raw["nodes"], "node entry missing")

        cmds.setAttr(f"{nodes[0]}.rotateY", 0.0)
        mn.loadPreset(path)
        _assert(_close(cmds.getAttr(f"{nodes[0]}.rotateY"), 33.0),
                f"expected 33.0, got {cmds.getAttr(f'{nodes[0]}.rotateY')}")


def test_only_skip_filters():
    """only/skip restrict which component slices are captured."""
    with _tmp_nodes(lambda: _make_cube("dw_filt_cube")) as nodes:
        mn = MayaNode(nodes[0])
        only = mn.createPreset(only=["attributes"])
        _assert("attributes" in only["dw_filt_cube"], "attributes missing under only=")
        skip = mn.createPreset(skip=["attributes"])
        _assert("attributes" not in skip["dw_filt_cube"], "attributes present despite skip=")


def test_node_from_preset_rebuild():
    """node_from_preset recreates a node from a stored entry via the registry."""
    src = _make_cube("dw_src_cube")
    try:
        cmds.setAttr(f"{src}.translateZ", 4.0)
        preset = MayaNode(src).createPreset()
        cmds.delete(src)
        _assert(not cmds.objExists(src), "source not deleted")

        identity, body = next(iter(preset.items()))
        node = pcomp.node_from_preset(identity, body)
        _assert(cmds.objExists(node.node), "rebuilt node does not exist")
        _assert(_close(cmds.getAttr(f"{node.tr}.translateZ"), 4.0),
                f"expected tz 4.0, got {cmds.getAttr(f'{node.tr}.translateZ')}")
    finally:
        for n in (src, "dw_src_cube"):
            if cmds.objExists(n):
                cmds.delete(n)


def test_connection_capture_restore():
    """ConnectionComponent captures an incoming link and reconnects it."""
    src = cmds.createNode("transform", name="dw_conn_src")
    dst = cmds.createNode("transform", name="dw_conn_dst")
    try:
        # Drive dst.translateX from src.translateX, then snapshot dst.
        cmds.connectAttr(f"{src}.translateX", f"{dst}.translateX", force=True)
        preset = MayaNode(dst).createPreset(only=["connections"])
        body = preset["dw_conn_dst"]
        _assert("connections" in body, f"no connections slice: {list(body)}")
        pairs = body["connections"]["pairs"]
        _assert(["dw_conn_src.translateX", "dw_conn_dst.translateX"] in pairs,
                f"expected src->dst pair, got {pairs}")

        # Break it, then re-apply: the connection comes back.
        cmds.disconnectAttr(f"{src}.translateX", f"{dst}.translateX")
        _assert(not cmds.isConnected(f"{src}.translateX", f"{dst}.translateX"),
                "disconnect failed")
        MayaNode(dst).applyPreset(preset, only=["connections"])
        _assert(cmds.isConnected(f"{src}.translateX", f"{dst}.translateX"),
                "connection not restored")
    finally:
        for n in (src, dst):
            if cmds.objExists(n):
                cmds.delete(n)


def test_geometry_roundtrip():
    """GeometryComponent restores moved vertices on matching topology."""
    tr = cmds.polySphere(name="dw_geo_sphere", sx=20, sy=20)[0]
    cmds.delete(tr, constructionHistory=True)  # so setPoints sticks
    try:
        m = Mesh(tr)
        preset = m.createPreset(only=["geometry"])
        geo = preset["dw_geo_sphere"]["geometry"]
        _assert(geo["count"] == cmds.polyEvaluate(tr, vertex=True),
                f"count {geo['count']} != {cmds.polyEvaluate(tr, vertex=True)}")
        _assert(geo["space"] == "object", f"expected object space, got {geo['space']}")
        pts_before = [list(p) for p in geo["points"]]

        cmds.move(5, 0, 0, f"{tr}.vtx[0]", relative=True)
        moved = m.createPreset(only=["geometry"])["dw_geo_sphere"]["geometry"]["points"]
        _assert(moved != pts_before, "vertex move had no measurable effect")

        m.applyPreset(preset, only=["geometry"])
        restored = m.createPreset(only=["geometry"])["dw_geo_sphere"]["geometry"]["points"]
        _assert(restored == pts_before, "geometry not restored after applyPreset")
    finally:
        for n in (tr, "dw_geo_sphere"):
            if cmds.objExists(n):
                cmds.delete(n)


def test_geometry_blend_half():
    """blend=0.5 moves a vertex halfway back toward the stored position."""
    tr = cmds.polySphere(name="dw_geob_sphere", sx=8, sy=8)[0]
    cmds.delete(tr, constructionHistory=True)
    try:
        m = Mesh(tr)
        stored = cmds.pointPosition(f"{tr}.vtx[0]", world=True)
        preset = m.createPreset(only=["geometry"])

        cmds.move(10, 0, 0, f"{tr}.vtx[0]", relative=True)
        moved = cmds.pointPosition(f"{tr}.vtx[0]", world=True)
        m.applyPreset(preset, only=["geometry"], ctx=pcomp.PresetContext(blend=0.5))
        half = cmds.pointPosition(f"{tr}.vtx[0]", world=True)
        expected_x = stored[0] * 0.5 + moved[0] * 0.5
        _assert(_close(half[0], expected_x, 1e-3),
                f"expected x~{expected_x}, got {half[0]}")
    finally:
        for n in (tr, "dw_geob_sphere"):
            if cmds.objExists(n):
                cmds.delete(n)


def test_geometry_file_stress():
    """Dense mesh survives a JSON save/load points round-trip."""
    tr = cmds.polySphere(name="dw_geos_sphere", sx=40, sy=40)[0]
    cmds.delete(tr, constructionHistory=True)
    try:
        m = Mesh(tr)
        before = m.createPreset(only=["geometry"])["dw_geos_sphere"]["geometry"]["points"]
        with _tmp_file() as path:
            m.savePreset(path, only=["geometry"])
            _assert(os.path.getsize(path) > 0, "preset file is empty")
            cmds.move(3, 1, -2, f"{tr}.vtx[5]", relative=True)
            m.loadPreset(path, only=["geometry"])
        after = m.createPreset(only=["geometry"])["dw_geos_sphere"]["geometry"]["points"]
        _assert(after == before, "dense geometry not restored from file")
    finally:
        for n in (tr, "dw_geos_sphere"):
            if cmds.objExists(n):
                cmds.delete(n)


def test_geometry_count_mismatch_skips():
    """Applying points onto a different topology warns and leaves it untouched."""
    src = cmds.polySphere(name="dw_geomm_src", sx=10, sy=10)[0]
    dst = cmds.polyCube(name="dw_geomm_dst")[0]
    cmds.delete(src, constructionHistory=True)
    cmds.delete(dst, constructionHistory=True)
    try:
        preset = Mesh(src).createPreset(only=["geometry"])
        # Reassign the captured points onto the cube entry and apply.
        body = next(iter(preset.values()))
        dst_preset = {"dw_geomm_dst": body}
        cube_before = Mesh(dst).createPreset(only=["geometry"])["dw_geomm_dst"]["geometry"]["points"]
        Mesh(dst).applyPreset(dst_preset, only=["geometry"])
        cube_after = Mesh(dst).createPreset(only=["geometry"])["dw_geomm_dst"]["geometry"]["points"]
        _assert(cube_after == cube_before, "cube geometry should be untouched on count mismatch")
    finally:
        for n in (src, dst, "dw_geomm_src", "dw_geomm_dst"):
            if cmds.objExists(n):
                cmds.delete(n)


def test_geometry_rebuild_from_empty():
    """Topology + points rebuild a full mesh onto an empty shape."""
    src = cmds.polySphere(name="dw_geor_src", sx=6, sy=6)[0]
    cmds.delete(src, constructionHistory=True)
    empty = None
    try:
        body = next(iter(Mesh(src).createPreset(only=["geometry"]).values()))
        src_count = body["geometry"]["count"]
        _assert("poly_counts" in body["geometry"], "topology not captured")

        # Build an empty mesh and rebuild the geometry onto it.
        empty = cmds.createNode("transform", name="dw_geor_dst")
        cmds.createNode("mesh", parent=empty, name="dw_geor_dstShape")
        _assert(cmds.polyEvaluate(empty, vertex=True) == 0, "target should start empty")

        Mesh(empty).applyPreset({"dw_geor_dst": body}, only=["geometry"])
        _assert(cmds.polyEvaluate(empty, vertex=True) == src_count,
                f"rebuilt {cmds.polyEvaluate(empty, vertex=True)} vtx != {src_count}")
        _assert(cmds.polyEvaluate(empty, face=True) == cmds.polyEvaluate(src, face=True),
                "rebuilt face count mismatch")
    finally:
        for n in (src, empty, "dw_geor_src", "dw_geor_dst"):
            if n and cmds.objExists(n):
                cmds.delete(n)


def test_keyframe_roundtrip():
    """KeyframeComponent is opt-in and round-trips keys + values."""
    tr = cmds.polyCube(name="dw_anim_cube")[0]
    try:
        plug = f"{tr}.translateX"
        cmds.setKeyframe(plug, time=1, value=0.0)
        cmds.setKeyframe(plug, time=10, value=5.0)
        cmds.setKeyframe(plug, time=20, value=-3.0)
        m = MayaNode(tr)

        # Opt-in: absent from a default preset.
        _assert("keyframes" not in m.createPreset()["dw_anim_cube"],
                "keyframes should be off by default")

        preset = m.createPreset(only=["keyframes"])
        anim = preset["dw_anim_cube"]["keyframes"]
        _assert("transform" in anim and "translateX" in anim["transform"],
                f"translateX keys not captured: {anim}")
        _assert(len(anim["transform"]["translateX"]["keys"]) == 3,
                "expected 3 keys captured")

        cmds.cutKey(plug, clear=True)
        _assert(cmds.keyframe(plug, query=True, keyframeCount=True) == 0,
                "keys not cleared")
        m.applyPreset(preset, only=["keyframes"])
        _assert(cmds.keyframe(plug, query=True, keyframeCount=True) == 3,
                "keys not restored")
        cmds.currentTime(10)
        _assert(_close(cmds.getAttr(plug), 5.0),
                f"value at frame 10 wrong: {cmds.getAttr(plug)}")
    finally:
        if cmds.objExists(tr):
            cmds.delete(tr)


# ---------------------------------------------------------------------------
# Cross-namespace connections (asset vs external)
# ---------------------------------------------------------------------------

def _ensure_ns(path: str) -> None:
    """Create a (possibly nested) namespace if missing."""
    current = ""
    for part in path.split(":"):
        full = f"{current}:{part}" if current else part
        if not cmds.namespace(exists=f":{full}"):
            cmds.namespace(add=part, parent=f":{current}" if current else ":")
        current = full


def _remove_ns(ns: str) -> None:
    if cmds.namespace(exists=f":{ns}"):
        cmds.namespace(removeNamespace=f":{ns}", deleteNamespaceContent=True)


def test_connection_external_namespace():
    """Foreign-namespace links survive verbatim; ext_ns_map / apply_external work."""
    for ns in ("man_01", "man_02", "alien_999", "alien_01"):
        _ensure_ns(ns)
    shot = None
    try:
        drv = cmds.createNode("transform", name="man_01:dw_xns_driver")
        dst = cmds.createNode("transform", name="man_01:dw_xns_node")
        alien = cmds.createNode("transform", name="alien_999:dw_xns_collider")
        shot = cmds.createNode("transform", name="dw_xns_shotsphere")
        cmds.connectAttr(f"{drv}.translateX", f"{dst}.translateX")
        cmds.connectAttr(f"{alien}.translateY", f"{dst}.translateY")
        cmds.connectAttr(f"{shot}.translateZ", f"{dst}.translateZ")

        preset = MayaNode(dst).createPreset(only=["connections"])
        conn = preset["dw_xns_node"]["connections"]
        pairs = conn["pairs"]
        _assert(["dw_xns_driver.translateX", "dw_xns_node.translateX"] in pairs,
                f"internal pair should be ns-stripped: {pairs}")
        _assert(["alien_999:dw_xns_collider.translateY",
                 "dw_xns_node.translateY"] in pairs,
                f"external pair should keep its namespace: {pairs}")
        _assert([":dw_xns_shotsphere.translateZ",
                 "dw_xns_node.translateZ"] in pairs,
                f"root external should carry an explicit ':' : {pairs}")
        _assert(conn["asset_ns"] == "man_01", f"asset_ns wrong: {conn['asset_ns']}")
        _assert(set(conn["external_ns"]) == {"alien_999", ":"},
                f"external_ns wrong: {conn['external_ns']}")
        summary = pcomp.collect_preset_namespaces(preset)
        _assert(summary == {"asset": ["man_01"],
                            "external": [":", "alien_999"]},
                f"namespace summary wrong: {summary}")

        # Apply onto man_02 with the alien remapped alien_999 -> alien_01.
        drv2 = cmds.createNode("transform", name="man_02:dw_xns_driver")
        dst2 = cmds.createNode("transform", name="man_02:dw_xns_node")
        alien2 = cmds.createNode("transform", name="alien_01:dw_xns_collider")
        ctx = pcomp.PresetContext(target_ns="man_02",
                                  ext_ns_map={"alien_999": "alien_01"})
        MayaNode(dst2).applyPreset(preset, ctx, only=["connections"])
        _assert(cmds.isConnected(f"{drv2}.translateX", f"{dst2}.translateX"),
                "internal connection not retargeted to man_02")
        _assert(cmds.isConnected(f"{alien2}.translateY", f"{dst2}.translateY"),
                "external connection not remapped alien_999 -> alien_01")
        _assert(cmds.isConnected(f"{shot}.translateZ", f"{dst2}.translateZ"),
                "root external connection not restored as-is")

        # apply_external=False: internal restored, externals left alone.
        for plug in ("translateX", "translateY", "translateZ"):
            conns = cmds.listConnections(f"{dst2}.{plug}", source=True,
                                         destination=False, plugs=True) or []
            for s in conns:
                cmds.disconnectAttr(s, f"{dst2}.{plug}")
        ctx = pcomp.PresetContext(target_ns="man_02", apply_external=False)
        MayaNode(dst2).applyPreset(preset, ctx, only=["connections"])
        _assert(cmds.isConnected(f"{drv2}.translateX", f"{dst2}.translateX"),
                "internal connection should still apply")
        _assert(not cmds.listConnections(f"{dst2}.translateY", source=True,
                                         destination=False),
                "external connection applied despite apply_external=False")
        _assert(not cmds.listConnections(f"{dst2}.translateZ", source=True,
                                         destination=False),
                "root external applied despite apply_external=False")
    finally:
        if shot and cmds.objExists(shot):
            cmds.delete(shot)
        for ns in ("man_01", "man_02", "alien_999", "alien_01"):
            _remove_ns(ns)


def test_connection_recursive_namespace():
    """recursive_namespace=True keeps sibling categories asset-relative."""
    for ns in ("man_01:cfx", "man_01:anm", "man_02:cfx", "man_02:anm"):
        _ensure_ns(ns)
    try:
        drv = cmds.createNode("transform", name="man_01:anm:dw_rns_drv")
        dst = cmds.createNode("transform", name="man_01:cfx:dw_rns_node")
        cmds.connectAttr(f"{drv}.translateX", f"{dst}.translateX")

        # Default (recursive off): the sibling category is another namespace,
        # so it is captured as external and kept verbatim.
        flat = pcomp.ConnectionComponent(io=(True, False)) \
            .capture(MayaNode(dst), pcomp.PresetContext())
        _assert(["man_01:anm:dw_rns_drv.translateX",
                 "dw_rns_node.translateX"] in flat["pairs"],
                f"non-recursive capture wrong: {flat['pairs']}")
        _assert(flat["external_ns"] == ["man_01"],
                f"sibling category should be external by default: {flat}")

        # Recursive: the whole man_01 root is the asset, names go relative.
        comp = pcomp.ConnectionComponent(io=(True, False),
                                         recursive_namespace=True)
        data = comp.capture(MayaNode(dst), pcomp.PresetContext())
        _assert(["anm:dw_rns_drv.translateX",
                 "cfx:dw_rns_node.translateX"] in data["pairs"],
                f"recursive capture wrong: {data['pairs']}")
        _assert(data["external_ns"] == [],
                f"recursive capture should have no external ns: {data}")

        # Relative names re-qualify under the new asset root.
        drv2 = cmds.createNode("transform", name="man_02:anm:dw_rns_drv")
        dst2 = cmds.createNode("transform", name="man_02:cfx:dw_rns_node")
        comp.apply(MayaNode(dst2), data, pcomp.PresetContext(target_ns="man_02"))
        _assert(cmds.isConnected(f"{drv2}.translateX", f"{dst2}.translateX"),
                "recursive pair not retargeted onto man_02 categories")
    finally:
        for ns in ("man_01", "man_02"):
            _remove_ns(ns)


_ALL_TESTS = [
    ("createPreset shape (transform+shape roles)", test_create_preset_shape),
    ("applyPreset round-trip",                     test_apply_preset_roundtrip),
    ("blend = 0.5 lerp",                           test_blend_half),
    ("savePreset / loadPreset file round-trip",    test_save_load_file),
    ("only / skip component filters",              test_only_skip_filters),
    ("node_from_preset registry rebuild",          test_node_from_preset_rebuild),
    ("ConnectionComponent capture / restore",      test_connection_capture_restore),
    ("GeometryComponent point round-trip",         test_geometry_roundtrip),
    ("GeometryComponent blend = 0.5",              test_geometry_blend_half),
    ("GeometryComponent dense file stress",        test_geometry_file_stress),
    ("GeometryComponent count-mismatch skip",      test_geometry_count_mismatch_skips),
    ("GeometryComponent rebuild from empty",       test_geometry_rebuild_from_empty),
    ("KeyframeComponent opt-in + key round-trip",  test_keyframe_roundtrip),
    ("Connection external-namespace handling",     test_connection_external_namespace),
    ("Connection recursive_namespace mode",        test_connection_recursive_namespace),
]


def run():
    """Run all preset-component tests and print a summary."""
    _RESULTS.clear()
    print("\n" + "=" * 60)
    print("  Preset Components (v2) Test Suite")
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