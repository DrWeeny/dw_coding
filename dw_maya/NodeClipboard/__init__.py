"""
NodeClipboard - copy a selection out of one Maya and paste it into another.

Built on the component preset system (``dw_presets_io.preset_components``) and
its cross-session clipboard folder: a copy writes one complete ``dw_preset``
entry, a paste shows that entry as a node x component checkbox tree so only
the checked slices (hierarchy / attributes / connections / keyframes /
geometry / network rebuild) are applied.

The window opens **simple**: two big buttons plus one checkbox per
component, pasting the newest entry. The Advanced button unfolds the entry
list, the per-node tree and the namespace options.

Both sessions must resolve the same clipboard folder - by default
``<system temp>/dw_preset_clipboard``; set ``DW_PRESET_CLIPBOARD`` to a
network share in both to pass entries between machines.

Kept import-light on purpose (no Maya side effects at import); the UI modules
are pulled in by :func:`launch`.

Launch from inside Maya::

    import dw_maya.NodeClipboard as node_clipboard
    node_clipboard.launch()

Layout
------
    main_ui.py            window: entry list, copy / paste, wiring
    clipboard_cmds.py     scene-side commands over preset_clipboard
    wgt_entry_tree.py     node x component checkbox tree (advanced)
    wgt_component_bar.py  flat per-component checkboxes (simple face)
    wgt_paste_options.py  target namespace, create flag, external ns remap
    compat.py             PySide2 / PySide6 shim

Author:
    DrWeeny
"""


def launch():
    """Open the NodeClipboard window."""
    from dw_maya.NodeClipboard import main_ui
    return main_ui.launch()


def _reload():
    """Reload every NodeClipboard module (dev helper - then call launch())."""
    import importlib
    from dw_maya.NodeClipboard import (compat, clipboard_cmds, wgt_entry_tree,
                                       wgt_component_bar, wgt_paste_options,
                                       main_ui)
    for module in (compat, clipboard_cmds, wgt_entry_tree, wgt_component_bar,
                   wgt_paste_options, main_ui):
        importlib.reload(module)
