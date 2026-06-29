import dw_maya.Slimfast.main_ui
# force the registring calls for panels
import dw_maya.Slimfast.wgt_deformer_panel # noqa: F401
import dw_maya.Slimfast.wgt_skin_panel # noqa: F401

# Colour palette per backend type
_SOURCE_COLORS = {
    'nCloth': '#4ecdc4',
    'nRigid': '#4ecdc4',
    'blendShape': '#e8a838',
    'skinCluster': '#a0c8ff',
    'cluster': '#cccccc',
    'softMod': '#cccccc',
    'wire': '#cccccc',
    'VertexColorAlpha': '#cc88dd',
    'vtxColor': '#cc88dd',
}

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
    import dw_maya.Slimfast.transfer_cmds
    import dw_maya.Slimfast.wgt_deformer_panel
    import dw_maya.Slimfast.main_ui
    import dw_maya.Slimfast.wgt_skin_panel
    import dw_maya.Slimfast.wgt_maya_transfer

    importlib.reload(dw_maya.Slimfast.wgt_signals)
    importlib.reload(dw_maya.Slimfast.wgt_section)
    importlib.reload(dw_maya.Slimfast.cmds)
    importlib.reload(dw_maya.Slimfast.transfer_cmds)
    importlib.reload(dw_maya.Slimfast.wgt_deformer_panel)
    importlib.reload(dw_maya.Slimfast.wgt_skin_panel)
    importlib.reload(dw_maya.Slimfast.main_ui)
    importlib.reload(dw_maya.Slimfast.wgt_maya_transfer)
