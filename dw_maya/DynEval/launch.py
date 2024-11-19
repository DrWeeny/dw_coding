import importlib

# Import UI modules
try:
    import dw_maya.DynEval.main_ui as simtool
    import dw_maya.DynEval.sim_cmds
    import dw_maya.DynEval.sim_widget
except ImportError as e:
    print(f"Error importing simulation tool modules: {e}")
    raise

try:
    dyneval.deleteLater()
except:
    pass
dyneval = simtool.DynEvalUI()
dyneval.show()
