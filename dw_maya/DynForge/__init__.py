"""
DynForge - install secondary deformation setups (guides) on costumes/cloth.

DynForge is the build/install counterpart of DynEval (which evaluates and caches
sims): an artist installs "guides" (joint chains today, nHair curves or
constraint setups later) that drive secondary deformation, then transfers the
skinning from the base rig onto the new chain.

Guide types are plugins: each is a GuideBackend subclass that self-registers on
import. To make the registry usable, import the backends package once:

    from dw_maya.DynForge import backends   # noqa: F401  registers all backends
    from dw_maya.DynForge import guide_registry

    guide_registry.available_backends()
    guide_registry.discover_all()

The package __init__ stays import-light on purpose (no maya side effects at
import time); the caller / UI pulls in `backends` when it needs the registry
populated, mirroring how DynEval's main_ui imports `systems`.
"""


def _reload():
    """
    Reload every DynForge module in dependency order (low-level first).

    Dev helper: after editing the package, run this then `launch()` again to
    pick up the changes without restarting Maya.
    """
    import importlib

    import dw_maya.dw_rigging.dw_chain_guide
    import dw_maya.DynForge.forge_cmds.compat
    import dw_maya.DynForge.forge_cmds.icons
    import dw_maya.DynForge.hub_keys
    import dw_maya.DynForge.wgt_base
    import dw_maya.DynForge.guide_registry
    import dw_maya.DynForge.backends.chain_joint_guide
    import dw_maya.DynForge.backends
    import dw_maya.DynForge.wgt_naming_panel
    import dw_maya.DynForge.wgt_attr_editor
    import dw_maya.DynForge.wgt_guide_list
    import dw_maya.DynForge.wgt_load_dialog
    import dw_maya.DynForge.main_ui

    for module in (
        dw_maya.dw_rigging.dw_chain_guide,
        dw_maya.DynForge.forge_cmds.compat,
        dw_maya.DynForge.forge_cmds.icons,
        dw_maya.DynForge.hub_keys,
        dw_maya.DynForge.wgt_base,
        dw_maya.DynForge.guide_registry,
        dw_maya.DynForge.backends.chain_joint_guide,
        dw_maya.DynForge.backends,
        dw_maya.DynForge.wgt_naming_panel,
        dw_maya.DynForge.wgt_attr_editor,
        dw_maya.DynForge.wgt_guide_list,
        dw_maya.DynForge.wgt_load_dialog,
        dw_maya.DynForge.main_ui,
    ):
        importlib.reload(module)


def launch():
    """Convenience wrapper: reload nothing, just open the DynForge window."""
    from dw_maya.DynForge import main_ui
    return main_ui.launch()