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

def open_for(mesh: str,
             node: str = None,
             map_name: str = None):
    """Launch Slimfast focused on a mesh, optionally preselecting a map.

    External handoff entry point (DynEval "Paint in Slimfast"): selects the
    mesh in Maya, refreshes the source list, then points the UI at the row
    matching `node` / `map_name` when given.

    Args:
        mesh: Mesh transform (or shape) to resolve weight sources on.
        node: Source node to preselect, e.g. an nCloth shape.
        map_name: Map to preselect on that node, e.g. "inputAttract".

    Returns:
        The SlimfastWidget instance.
    """
    import maya.cmds as cmds
    gui = launch()
    if mesh and cmds.objExists(mesh):
        cmds.select(mesh, replace=True)
        gui.refresh_sources()
        if node:
            gui.focus_map(node, map_name)
    else:
        cmds.warning(f"Slimfast.open_for: mesh '{mesh}' not found.")
    return gui


def _reload():
    """Reload all modules in the Slimfast package."""
    import importlib
    import dw_maya.Slimfast.wgt_signals
    import dw_maya.Slimfast.wgt_section
    import dw_maya.Slimfast.cmds
    import dw_maya.Slimfast.type_colors
    import dw_maya.Slimfast.transfer_cmds
    import dw_maya.Slimfast.wgt_deformer_panel
    import dw_maya.Slimfast.main_ui
    import dw_maya.Slimfast.wgt_skin_panel
    import dw_maya.Slimfast.wgt_maya_transfer

    importlib.reload(dw_maya.Slimfast.wgt_signals)
    importlib.reload(dw_maya.Slimfast.wgt_section)
    importlib.reload(dw_maya.Slimfast.cmds)
    importlib.reload(dw_maya.Slimfast.type_colors)
    importlib.reload(dw_maya.Slimfast.transfer_cmds)
    importlib.reload(dw_maya.Slimfast.wgt_deformer_panel)
    importlib.reload(dw_maya.Slimfast.wgt_skin_panel)
    importlib.reload(dw_maya.Slimfast.main_ui)
    importlib.reload(dw_maya.Slimfast.wgt_maya_transfer)
