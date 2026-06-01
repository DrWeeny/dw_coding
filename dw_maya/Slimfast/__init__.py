import dw_maya.Slimfast.main_ui

# force the registring calls for panels
import dw_maya.Slimfast.wgt_deformer_panel

def launch(docked:bool=False):
    if not docked:
        gui = dw_maya.Slimfast.main_ui.SlimfastWidget.show_window()
        return gui
    else:
        gui = dw_maya.Slimfast.main_ui.SlimfastWidget.show_docked()
        return gui

def _reload():
    """Reload all modules in the Slimfast package."""
    import importlib
    import dw_maya.Slimfast.wgt_signals
    import dw_maya.Slimfast.wgt_section
    import dw_maya.Slimfast.cmds
    import dw_maya.Slimfast.wgt_deformer_panel
    import dw_maya.Slimfast.main_ui

    importlib.reload(dw_maya.Slimfast.wgt_signals)
    importlib.reload(dw_maya.Slimfast.wgt_section)
    importlib.reload(dw_maya.Slimfast.cmds)
    importlib.reload(dw_maya.Slimfast.wgt_deformer_panel)
    importlib.reload(dw_maya.Slimfast.main_ui)
