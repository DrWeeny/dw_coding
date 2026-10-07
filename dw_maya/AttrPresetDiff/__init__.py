"""
AttrPresetDiff - diff and edit attribute values between presets, scene nodes and Maya defaults.

Summary:
    Two sources side by side - a dw_preset file entry, a scene node, or a node
    type's Maya default - with the default always shown as a reference
    column, so "what was changed" reads at a glance. Values can be edited in
    place (a file in memory until saved, a node directly, one undo) and copied
    across per row. Maya defaults come from a throwaway createNode, captured
    with the same code as presets and cached as json per node type.

    Separate from PresetTool / DynForge on purpose: they can open it with a
    preset preloaded (launch(a=path, b=node)).

Modules:
    diff_cmds - sources, defaults cache, diff rows, edits. No Qt.
    wgt_source - one side's picker.
    main_ui - the window.
    compat - PySide6 / PySide2.

Example:
    import dw_maya.AttrPresetDiff as apd
    apd.launch()                                      # empty
    apd.launch(a="D:/presets/hood_soft.json", b="nClothShape1")

Author:
    DrWeeny
"""


def launch(a: str = "",
           b: str = ""):
    """Open the AttrPresetDiff window; `a` / `b` preload a preset path or a node name."""
    from dw_maya.AttrPresetDiff import main_ui
    return main_ui.launch(a, b)


def _reload():
    """Reload the package's modules, low-level first, then launch() again."""
    import importlib

    import dw_maya.AttrPresetDiff.compat
    import dw_maya.AttrPresetDiff.diff_cmds
    import dw_maya.AttrPresetDiff.wgt_source
    import dw_maya.AttrPresetDiff.main_ui

    for module in (dw_maya.AttrPresetDiff.compat,
                   dw_maya.AttrPresetDiff.diff_cmds,
                   dw_maya.AttrPresetDiff.wgt_source,
                   dw_maya.AttrPresetDiff.main_ui):
        importlib.reload(module)
