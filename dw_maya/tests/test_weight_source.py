"""Integration tests for the WeightSource protocol — cluster + nCloth backends.

Creates a real Maya scene (polySphere + cluster + nCloth) and validates:
- Deformer wrapping via make_deformer() / Cluster
- Nucleus wrapping via NClothMap
- resolve_weight_sources() with all three modes
- apply_operation() flood / smooth / mirror on both backends

Features:
    - Zero side-effects: each TestCase calls cmds.file(new=True) in setUp/tearDown.
    - nCloth tests are auto-skipped when the nCloth plugin is not loaded.
    - Runnable from the Maya Script Editor via run_tests().

Classes:
    TestSceneHelpers:         Sanity-check the scene-building helpers.
    TestDeformerWeightSource: Cluster via make_deformer() — identity, get/set weights.
    TestNClothMapWeightSource: NClothMap — identity, map_type promotion, get/set weights.
    TestResolveWeightSources: resolve_weight_sources() with mode deformer/nucleus/all.
    TestApplyOperation:       apply_operation() flood/smooth/mirror on both backends.

Functions:
    run_tests: Execute all suites and print results (call from Script Editor).

Example:
    # Inside Maya Script Editor
    import importlib
    import dw_maya.tests.test_weight_source as t
    importlib.reload(t)
    t.run_tests()

    # Run only one class
    t.run_tests(filter_class=t.TestApplyOperation)

TODO:
    - Add TestBlendShape once BlendShape.get_weights() is validated.
    - Add TestSkinCluster per-influence weight round-trip.

Author: DrWeeny
"""

from __future__ import annotations

import unittest
from typing import Optional, Tuple, Type

from maya import cmds, mel

import dw_maya.dw_deformers.dw_deformer_class as deformer_module
import dw_maya.dw_nucleus_utils.dw_ncloth_class as ncloth_module
import dw_maya.dw_nucleus_utils.dw_core as nucx_core
import dw_maya.dw_paint.weight_source as weight_source_module
from dw_maya.dw_paint.protocol import WeightSource


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# polySphere subdivisions — gives a reasonable vertex count (~66)
_SUBDIV_X = 8
_SUBDIV_Y = 8

# nCloth map name that always exists on a fresh cloth node
_CLOTH_MAP = 'thickness'


# ---------------------------------------------------------------------------
# Scene helpers
# ---------------------------------------------------------------------------

def _ensure_ncloth_plugin() -> bool:
    """Load the nCloth plugin if not already loaded.

    Returns:
        True if nCloth is available after this call, False otherwise.
    """
    try:
        if not cmds.pluginInfo('nCloth', query=True, loaded=True):
            cmds.loadPlugin('nCloth', quiet=True)
        return cmds.pluginInfo('nCloth', query=True, loaded=True)
    except Exception:
        return False


def _create_test_sphere(name: str = 'testSphere') -> str:
    """Create a polySphere and return its transform name.

    Args:
        name: Base transform name.

    Returns:
        Transform node name.
    """
    transform, _ = cmds.polySphere(
        name=name, subdivisionsX=_SUBDIV_X, subdivisionsY=_SUBDIV_Y
    )
    return transform


def _create_cluster(mesh: str) -> Tuple[str, str]:
    """Create a cluster on the given mesh.

    Args:
        mesh: Mesh transform name.

    Returns:
        Tuple (cluster_node_name, handle_transform_name).
    """
    cluster_node, handle = cmds.cluster(mesh)
    return cluster_node, handle


def _create_ncloth(mesh: str) -> Optional[str]:
    """Create an nCloth node on the given mesh.

    Requires the nCloth plugin to be loaded.

    Args:
        mesh: Mesh transform name.

    Returns:
        nCloth shape node name, or None if creation failed.
    """
    cmds.select(mesh, replace=True)
    try:
        mel.eval('createNCloth 0;')
    except Exception:
        return None
    return nucx_core.get_nucx_node(mesh)


# ---------------------------------------------------------------------------
# TestSceneHelpers
# ---------------------------------------------------------------------------

class TestSceneHelpers(unittest.TestCase):
    """Sanity-check that the scene helpers produce valid Maya nodes."""

    def setUp(self):
        cmds.file(new=True, force=True)

    def tearDown(self):
        cmds.file(new=True, force=True)

    def test_sphere_exists(self):
        mesh = _create_test_sphere()
        self.assertTrue(cmds.objExists(mesh), f"Sphere '{mesh}' not found in scene")

    def test_sphere_is_transform(self):
        mesh = _create_test_sphere()
        self.assertEqual(cmds.objectType(mesh), 'transform')

    def test_cluster_exists(self):
        mesh = _create_test_sphere()
        cluster_node, _ = _create_cluster(mesh)
        self.assertTrue(cmds.objExists(cluster_node))

    def test_cluster_type(self):
        mesh = _create_test_sphere()
        cluster_node, _ = _create_cluster(mesh)
        self.assertEqual(cmds.nodeType(cluster_node), 'cluster')

    def test_ncloth_exists(self):
        mesh = _create_test_sphere()
        ncloth = _create_ncloth(mesh)
        self.assertIsNotNone(ncloth, 'get_nucx_node returned None after createNCloth')
        self.assertTrue(cmds.objExists(ncloth))

    def test_ncloth_type(self):
        mesh = _create_test_sphere()
        ncloth = _create_ncloth(mesh)
        if ncloth is None:
            self.skipTest('nCloth node not created')
        self.assertIn(cmds.nodeType(ncloth), ('nCloth', 'nRigid'))


# ---------------------------------------------------------------------------
# TestDeformerWeightSource
# ---------------------------------------------------------------------------

class TestDeformerWeightSource(unittest.TestCase):
    """Cluster wrapped as WeightSource — identity, weights round-trip, errors."""

    def setUp(self):
        cmds.file(new=True, force=True)
        self.mesh = _create_test_sphere()
        self.cluster_node, self.handle = _create_cluster(self.mesh)
        self.source = deformer_module.make_deformer(self.cluster_node)

    def tearDown(self):
        cmds.file(new=True, force=True)

    # --- identity ---

    def test_node_name_matches_cluster(self):
        self.assertEqual(self.source.node_name, self.cluster_node)

    def test_mesh_name_exists_in_scene(self):
        mesh = self.source.mesh_name
        self.assertTrue(cmds.objExists(mesh),
                        f"mesh_name '{mesh}' does not exist in the scene")

    def test_vtx_count_positive(self):
        self.assertGreater(self.source.vtx_count, 0)

    def test_vtx_count_stable(self):
        # Two calls should return the same value
        self.assertEqual(self.source.vtx_count, self.source.vtx_count)

    # --- protocol ---

    def test_isinstance_weight_source(self):
        self.assertIsInstance(self.source, WeightSource)

    # --- get_weights ---

    def test_get_weights_returns_list(self):
        self.assertIsInstance(self.source.get_weights(), list)

    def test_get_weights_length_matches_vtx_count(self):
        self.assertEqual(len(self.source.get_weights()), self.source.vtx_count)

    def test_get_weights_fresh_cluster_all_ones(self):
        # A freshly created cluster defaults to full influence (1.0)
        for w in self.source.get_weights():
            self.assertAlmostEqual(w, 1.0, places=4,
                                   msg=f"Expected 1.0 on fresh cluster, got {w}")

    # --- set_weights ---

    def test_set_weights_round_trip_gradient(self):
        n = self.source.vtx_count
        target = [i / float(n) for i in range(n)]
        self.source.set_weights(target)
        result = self.source.get_weights()
        self.assertEqual(len(result), n)
        for i, (a, b) in enumerate(zip(target, result)):
            self.assertAlmostEqual(a, b, places=4,
                                   msg=f"Vertex {i}: wrote {a}, read back {b}")

    def test_set_weights_all_zero(self):
        n = self.source.vtx_count
        self.source.set_weights([0.0] * n)
        for w in self.source.get_weights():
            self.assertAlmostEqual(w, 0.0, places=4)

    def test_set_weights_all_one(self):
        n = self.source.vtx_count
        self.source.set_weights([1.0] * n)
        for w in self.source.get_weights():
            self.assertAlmostEqual(w, 1.0, places=4)

    def test_set_weights_alternating(self):
        n = self.source.vtx_count
        target = [1.0 if i % 2 == 0 else 0.0 for i in range(n)]
        self.source.set_weights(target)
        result = self.source.get_weights()
        for i, (a, b) in enumerate(zip(target, result)):
            self.assertAlmostEqual(a, b, places=4)

    # --- error cases ---

    def test_set_weights_too_short_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.source.set_weights([0.5])

    def test_set_weights_too_long_raises_value_error(self):
        n = self.source.vtx_count
        with self.assertRaises(ValueError):
            self.source.set_weights([0.5] * (n + 10))

    def test_make_deformer_invalid_node_raises(self):
        try:
            deformer_module.make_deformer('doesNotExist_cluster1')
            self.fail('Expected ValueError or RuntimeError — got nothing')
        except (ValueError, RuntimeError):
            pass


# ---------------------------------------------------------------------------
# TestNClothMapWeightSource
# ---------------------------------------------------------------------------

class TestNClothMapWeightSource(unittest.TestCase):
    """NClothMap — construction guards, map_type promotion, get/set weights."""

    def setUp(self):
        cmds.file(new=True, force=True)
        self.mesh = _create_test_sphere()
        self.ncloth = _create_ncloth(self.mesh)
        if self.ncloth is None:
            self.skipTest('nCloth node not created — skipping nucleus tests')
        self.source = ncloth_module.NClothMap(self.ncloth, _CLOTH_MAP, self.mesh)

    def tearDown(self):
        cmds.file(new=True, force=True)

    # --- construction guards ---

    def test_invalid_node_raises_value_error(self):
        with self.assertRaises(ValueError):
            ncloth_module.NClothMap('nonExistentNodeXYZ', _CLOTH_MAP, self.mesh)

    def test_wrong_node_type_raises_value_error(self):
        # Pass the mesh transform as the nucleus_node — wrong type
        with self.assertRaises(ValueError):
            ncloth_module.NClothMap(self.mesh, _CLOTH_MAP, self.mesh)

    # --- identity ---

    def test_node_name(self):
        self.assertEqual(self.source.node_name, self.ncloth)

    def test_map_name(self):
        self.assertEqual(self.source.map_name, _CLOTH_MAP)

    def test_mesh_name(self):
        self.assertEqual(self.source.mesh_name, self.mesh)

    def test_vtx_count_positive(self):
        self.assertGreater(self.source.vtx_count, 0)

    # --- protocol ---

    def test_isinstance_weight_source(self):
        self.assertIsInstance(self.source, WeightSource)

    # --- map_type ---

    def test_map_type_default_is_zero(self):
        # Fresh nCloth: thickness is MapType=0 (None / disabled)
        self.assertEqual(self.source.map_type, 0,
                         'Fresh nCloth thickness map should start at MapType=0')

    def test_map_type_setter_to_vertex(self):
        self.source.map_type = 1
        self.assertEqual(self.source.map_type, 1)

    def test_map_type_setter_round_trip(self):
        self.source.map_type = 1
        self.source.map_type = 0
        self.assertEqual(self.source.map_type, 0)

    # --- get_weights ---

    def test_get_weights_returns_list(self):
        self.assertIsInstance(self.source.get_weights(), list)

    def test_get_weights_length_matches_vtx_count(self):
        n = self.source.vtx_count
        self.assertEqual(len(self.source.get_weights()), n)

    def test_get_weights_all_zero_by_default(self):
        # MapType=0 → no per-vertex data → all zeros
        for w in self.source.get_weights():
            self.assertAlmostEqual(w, 0.0, places=4)

    # --- set_weights ---

    def test_set_weights_auto_promotes_map_type(self):
        # map_type=0 before; set_weights should auto-promote to 1
        self.assertEqual(self.source.map_type, 0)
        n = self.source.vtx_count
        self.source.set_weights([0.5] * n)
        self.assertEqual(self.source.map_type, 1,
                         'set_weights should auto-promote MapType from 0 to 1')

    def test_set_weights_round_trip_uniform(self):
        n = self.source.vtx_count
        self.source.set_weights([0.75] * n)
        result = self.source.get_weights()
        self.assertEqual(len(result), n)
        for w in result:
            self.assertAlmostEqual(w, 0.75, places=4)

    def test_set_weights_round_trip_gradient(self):
        n = self.source.vtx_count
        target = [i / float(n) for i in range(n)]
        self.source.set_weights(target)
        result = self.source.get_weights()
        self.assertEqual(len(result), n)
        for i, (a, b) in enumerate(zip(target, result)):
            self.assertAlmostEqual(a, b, places=4,
                                   msg=f"Vertex {i}: wrote {a}, read back {b}")

    def test_set_weights_does_not_alter_other_maps(self):
        # Setting 'thickness' should not touch 'bounce'
        bounce_src = ncloth_module.NClothMap(self.ncloth, 'bounce', self.mesh)
        initial_bounce_type = bounce_src.map_type

        n = self.source.vtx_count
        self.source.set_weights([0.3] * n)

        self.assertEqual(bounce_src.map_type, initial_bounce_type,
                         'Setting thickness should not change bounce MapType')

    # --- error cases ---

    def test_set_weights_too_short_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.source.set_weights([0.5, 0.5])

    def test_set_weights_too_long_raises_value_error(self):
        n = self.source.vtx_count
        with self.assertRaises(ValueError):
            self.source.set_weights([0.5] * (n + 5))


# ---------------------------------------------------------------------------
# TestResolveWeightSources
# ---------------------------------------------------------------------------

class TestResolveWeightSources(unittest.TestCase):
    """resolve_weight_sources() — mode filtering, correctness, empty mesh."""

    def setUp(self):


        cmds.file(new=True, force=True)
        self.mesh = _create_test_sphere()
        self.cluster_node, _ = _create_cluster(self.mesh)

        self.ncloth = _create_ncloth(self.mesh)
        self._has_ncloth = self.ncloth is not None


    def tearDown(self):
        cmds.file(new=True, force=True)

    # --- mode='deformer' ---

    def test_mode_deformer_returns_list(self):
        sources = weight_source_module.resolve_weight_sources(self.mesh, mode='deformer')
        self.assertIsInstance(sources, list)

    def test_mode_deformer_contains_cluster(self):
        sources = weight_source_module.resolve_weight_sources(self.mesh, mode='deformer')
        node_names = [s.node_name for s in sources]
        self.assertIn(self.cluster_node, node_names,
                      f"Cluster '{self.cluster_node}' not found in {node_names}")

    def test_mode_deformer_no_ncloth_maps(self):
        sources = weight_source_module.resolve_weight_sources(self.mesh, mode='deformer')
        for s in sources:
            self.assertNotIsInstance(
                s, ncloth_module.NClothMap,
                f"NClothMap unexpectedly found with mode='deformer': {s}"
            )

    def test_mode_deformer_all_are_deformers(self):
        sources = weight_source_module.resolve_weight_sources(self.mesh, mode='deformer')
        for s in sources:
            self.assertIsInstance(s, deformer_module.Deformer)

    # --- mode='nucleus' ---

    def test_mode_nucleus_returns_list(self):
        if not self._has_ncloth:
            self.skipTest('nCloth not available')
        sources = weight_source_module.resolve_weight_sources(self.mesh, mode='nucleus')
        self.assertIsInstance(sources, list)

    def test_mode_nucleus_all_are_ncloth_maps(self):
        if not self._has_ncloth:
            self.skipTest('nCloth not available')
        sources = weight_source_module.resolve_weight_sources(self.mesh, mode='nucleus')
        for s in sources:
            self.assertIsInstance(s, ncloth_module.NClothMap)

    def test_mode_nucleus_no_deformers(self):
        if not self._has_ncloth:
            self.skipTest('nCloth not available')
        sources = weight_source_module.resolve_weight_sources(self.mesh, mode='nucleus')
        for s in sources:
            self.assertNotIsInstance(s, deformer_module.Deformer)

    def test_mode_nucleus_thickness_map_present(self):
        if not self._has_ncloth:
            self.skipTest('nCloth not available')
        sources = weight_source_module.resolve_weight_sources(self.mesh, mode='nucleus')
        map_names = [s.map_name for s in sources  # type: ignore[attr-defined]
                     if isinstance(s, ncloth_module.NClothMap)]
        self.assertIn(_CLOTH_MAP, map_names,
                      f"'{_CLOTH_MAP}' not found in nucleus maps: {map_names}")

    # --- mode='all' ---

    def test_mode_all_returns_both_backends(self):
        if not self._has_ncloth:
            self.skipTest('nCloth not available')
        sources = weight_source_module.resolve_weight_sources(self.mesh, mode='all')
        has_deformer = any(isinstance(s, deformer_module.Deformer) for s in sources)
        has_nucleus = any(isinstance(s, ncloth_module.NClothMap) for s in sources)
        self.assertTrue(has_deformer, 'mode=all: no Deformer found')
        self.assertTrue(has_nucleus, 'mode=all: no NClothMap found')

    def test_mode_all_deformers_come_first(self):
        if not self._has_ncloth:
            self.skipTest('nCloth not available')
        sources = weight_source_module.resolve_weight_sources(self.mesh, mode='all')
        # Find index of first NClothMap and last Deformer
        first_nucleus = next(
            (i for i, s in enumerate(sources) if isinstance(s, ncloth_module.NClothMap)),
            None
        )
        last_deformer = next(
            (i for i, s in reversed(list(enumerate(sources)))
             if isinstance(s, deformer_module.Deformer)),
            None
        )
        if first_nucleus is not None and last_deformer is not None:
            self.assertLess(last_deformer, first_nucleus,
                            'Deformers should appear before NClothMaps in mode=all')

    # --- protocol ---

    def test_all_sources_implement_weight_source(self):
        sources = weight_source_module.resolve_weight_sources(self.mesh, mode='all')
        for s in sources:
            self.assertIsInstance(s, WeightSource,
                                  f"{type(s).__name__} does not implement WeightSource")

    # --- plain mesh with no deformers ---

    def test_plain_mesh_deformer_mode_empty(self):
        plain = _create_test_sphere('plainMesh')
        sources = weight_source_module.resolve_weight_sources(plain, mode='deformer')
        self.assertEqual(sources, [],
                         f"Expected [] for plain mesh, got {sources}")

    def test_plain_mesh_nucleus_mode_empty(self):
        plain = _create_test_sphere('plainMesh2')
        sources = weight_source_module.resolve_weight_sources(plain, mode='nucleus')
        self.assertEqual(sources, [])


# ---------------------------------------------------------------------------
# TestApplyOperation
# ---------------------------------------------------------------------------

class TestApplyOperation(unittest.TestCase):
    """apply_operation() — flood/smooth/mirror on cluster and nCloth backends."""

    def setUp(self):
        cmds.file(new=True, force=True)
        self.mesh = _create_test_sphere()

        cluster_node, _ = _create_cluster(self.mesh)
        self.cluster_src = deformer_module.make_deformer(cluster_node)

        self._has_ncloth = _ensure_ncloth_plugin()
        if self._has_ncloth:
            ncloth = _create_ncloth(self.mesh)
            if ncloth:
                self.ncloth_src = ncloth_module.NClothMap(ncloth, _CLOTH_MAP, self.mesh)
            else:
                self._has_ncloth = False
                self.ncloth_src = None
        else:
            self.ncloth_src = None

    def tearDown(self):
        cmds.file(new=True, force=True)

    # --- flood / replace ---

    def test_flood_replace_cluster(self):
        weight_source_module.apply_operation(self.cluster_src, 'flood', value=0.42)
        for w in self.cluster_src.get_weights():
            self.assertAlmostEqual(w, 0.42, places=4)

    def test_flood_replace_ncloth(self):
        if not self._has_ncloth:
            self.skipTest('nCloth not available')
        weight_source_module.apply_operation(self.ncloth_src, 'flood', value=0.75)
        for w in self.ncloth_src.get_weights():
            self.assertAlmostEqual(w, 0.75, places=4)

    # --- flood / add ---

    def test_flood_add_cluster(self):
        n = self.cluster_src.vtx_count
        self.cluster_src.set_weights([0.5] * n)
        weight_source_module.apply_operation(
            self.cluster_src, 'flood', value=0.2, op='add'
        )
        for w in self.cluster_src.get_weights():
            self.assertAlmostEqual(w, 0.7, places=3)

    def test_flood_add_ncloth(self):
        if not self._has_ncloth:
            self.skipTest('nCloth not available')
        n = self.ncloth_src.vtx_count
        self.ncloth_src.set_weights([0.3] * n)
        weight_source_module.apply_operation(
            self.ncloth_src, 'flood', value=0.2, op='add'
        )
        for w in self.ncloth_src.get_weights():
            self.assertAlmostEqual(w, 0.5, places=3)

    # --- flood / clamp ---

    def test_flood_clamp_max_cluster(self):
        n = self.cluster_src.vtx_count
        self.cluster_src.set_weights([0.5] * n)
        weight_source_module.apply_operation(
            self.cluster_src, 'flood', value=2.0, clamp_max=0.8
        )
        for w in self.cluster_src.get_weights():
            self.assertLessEqual(w, 0.8 + 1e-5,
                                 f"Weight {w} exceeds clamp_max=0.8")

    def test_flood_clamp_min_cluster(self):
        n = self.cluster_src.vtx_count
        self.cluster_src.set_weights([0.5] * n)
        weight_source_module.apply_operation(
            self.cluster_src, 'flood', value=-1.0, clamp_min=0.2
        )
        for w in self.cluster_src.get_weights():
            self.assertGreaterEqual(w, 0.2 - 1e-5,
                                    f"Weight {w} is below clamp_min=0.2")

    # --- flood zero / full coverage ---

    def test_flood_zero_cluster(self):
        weight_source_module.apply_operation(self.cluster_src, 'flood', value=0.0)
        for w in self.cluster_src.get_weights():
            self.assertAlmostEqual(w, 0.0, places=4)

    def test_flood_one_cluster(self):
        # First set to 0, then flood to 1
        n = self.cluster_src.vtx_count
        self.cluster_src.set_weights([0.0] * n)
        weight_source_module.apply_operation(self.cluster_src, 'flood', value=1.0)
        for w in self.cluster_src.get_weights():
            self.assertAlmostEqual(w, 1.0, places=4)

    # --- smooth ---

    def test_smooth_cluster_output_length(self):
        n = self.cluster_src.vtx_count
        checkerboard = [1.0 if i % 2 == 0 else 0.0 for i in range(n)]
        self.cluster_src.set_weights(checkerboard)
        weight_source_module.apply_operation(self.cluster_src, 'smooth', iterations=1)
        result = self.cluster_src.get_weights()
        self.assertEqual(len(result), n)

    def test_smooth_cluster_values_in_range(self):
        n = self.cluster_src.vtx_count
        checkerboard = [1.0 if i % 2 == 0 else 0.0 for i in range(n)]
        self.cluster_src.set_weights(checkerboard)
        weight_source_module.apply_operation(self.cluster_src, 'smooth', iterations=2)
        for w in self.cluster_src.get_weights():
            self.assertGreaterEqual(w, -1e-5)
            self.assertLessEqual(w, 1.0 + 1e-5)

    def test_smooth_cluster_reduces_variance(self):
        # After smoothing a checkerboard the spread should decrease
        n = self.cluster_src.vtx_count
        checkerboard = [1.0 if i % 2 == 0 else 0.0 for i in range(n)]
        self.cluster_src.set_weights(checkerboard)

        before = self.cluster_src.get_weights()
        variance_before = sum((w - 0.5) ** 2 for w in before) / len(before)

        weight_source_module.apply_operation(self.cluster_src, 'smooth', iterations=3)

        after = self.cluster_src.get_weights()
        variance_after = sum((w - 0.5) ** 2 for w in after) / len(after)

        self.assertLess(variance_after, variance_before,
                        'Smoothing should reduce weight variance on a checkerboard')

    def test_smooth_ncloth_output_length(self):
        if not self._has_ncloth:
            self.skipTest('nCloth not available')
        n = self.ncloth_src.vtx_count
        initial = [1.0 if i % 2 == 0 else 0.0 for i in range(n)]
        self.ncloth_src.set_weights(initial)
        weight_source_module.apply_operation(self.ncloth_src, 'smooth', iterations=1)
        result = self.ncloth_src.get_weights()
        self.assertEqual(len(result), n)

    # --- mirror ---

    def test_mirror_cluster_output_length(self):
        n = self.cluster_src.vtx_count
        self.cluster_src.set_weights([1.0] * n)
        weight_source_module.apply_operation(self.cluster_src, 'mirror', axis='x')
        self.assertEqual(len(self.cluster_src.get_weights()), n)

    def test_mirror_cluster_values_in_range(self):
        n = self.cluster_src.vtx_count
        target = [i / float(n) for i in range(n)]
        self.cluster_src.set_weights(target)
        weight_source_module.apply_operation(self.cluster_src, 'mirror', axis='x')
        for w in self.cluster_src.get_weights():
            self.assertGreaterEqual(w, -1e-5)
            self.assertLessEqual(w, 1.0 + 1e-5)

    # --- error cases ---

    def test_unknown_operation_raises_value_error(self):
        with self.assertRaises(ValueError):
            weight_source_module.apply_operation(
                self.cluster_src, str('nonexistent_operation')  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_tests(verbosity: int = 2,
              filter_class: Optional[Type[unittest.TestCase]] = None
              ) -> unittest.TestResult:
    """Run all weight-source integration tests inside Maya.

    Designed to be called from the Maya Script Editor or a Maya batch session.

    Args:
        verbosity:    2 = verbose (default), 1 = dots only, 0 = silent.
        filter_class: Optional single TestCase class to run instead of all.

    Returns:
        unittest.TestResult with all pass/fail details.

    Example:
        import dw_maya.tests.test_weight_source as t
        t.run_tests()
        # Run only one class:
        t.run_tests(filter_class=t.TestApplyOperation)
    """
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    all_classes = [
        TestSceneHelpers,
        TestDeformerWeightSource,
        TestNClothMapWeightSource,
        TestResolveWeightSources,
        TestApplyOperation,
    ]

    if filter_class is not None:
        suite.addTests(loader.loadTestsFromTestCase(filter_class))
    else:
        for cls in all_classes:
            suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=verbosity)
    return runner.run(suite)


if __name__ == '__main__':
    run_tests()

