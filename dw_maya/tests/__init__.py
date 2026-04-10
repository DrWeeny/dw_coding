"""
dw_maya test suite — Maya integration tests.

All tests require an active Maya session (maya.cmds available).

Run from Maya Script Editor:
    import importlib
    import dw_maya.tests.test_weight_source as t
    importlib.reload(t)
    t.run_tests()

Run specific class only:
    t.run_tests(filter_class=t.TestDeformerWeightSource)
"""

