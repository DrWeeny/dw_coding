import sys
import importlib
from typing import List, Set
import maya.cmds as cmds


def reload_dyneval():
    """
    Reload all DynEval modules for development.
    Properly handles submodules and cleans up any existing UI instances.
    """
    # First, close any existing DynEval windows
    for window in get_dyneval_windows():
        try:
            window.close()
            window.deleteLater()
        except Exception as e:
            print(f"Failed to close window: {e}")

    # List of all DynEval modules to reload
    modules_to_reload = [
        # Core modules
        'dw_maya.DynEval',
        'dw_maya.DynEval.launch',
        'dw_maya.DynEval.main_beta',
        'dw_maya.DynEval.main_ui',

        # Widget modules
        'dw_maya.DynEval.sim_widget',
        'dw_maya.DynEval.sim_widget.wgt_cache_operation',
        'dw_maya.DynEval.sim_widget.wgt_preset_manager',
        'dw_maya.DynEval.sim_widget.wgt_cache_tree',
        'dw_maya.DynEval.sim_widget.wgt_state_recovery',
        'dw_maya.DynEval.sim_widget.wgt_tree_progress',
        'dw_maya.DynEval.sim_widget.wgt_colortextbutton',
        'dw_maya.DynEval.sim_widget.wgt_commentary',
        'dw_maya.DynEval.sim_widget.wgt_maps_tree',
        'dw_maya.DynEval.sim_widget.wgt_paint_map',
        'dw_maya.DynEval.sim_widget.wgt_treewidget_toggle',

        # Command modules
        'dw_maya.DynEval.sim_cmds',
        'dw_maya.DynEval.sim_cmds.cache_management',
        'dw_maya.DynEval.sim_cmds.info_management',
        'dw_maya.DynEval.sim_cmds.preset_management',
        'dw_maya.DynEval.sim_cmds.vtx_management',
        'dw_maya.DynEval.sim_cmds.ziva_cmds',

        # Tree related modules
        'dw_maya.DynEval.dendrology',
        'dw_maya.DynEval.dendrology.ziva_leaf',
        'dw_maya.DynEval.dendrology.cache_leaf',
        'dw_maya.DynEval.dendrology.tree_toggle_button',
        'dw_maya.DynEval.dendrology.nucleus_leaf',
        'dw_maya.DynEval.dendrology.nucleus_leaf.base_standarditem',
        'dw_maya.DynEval.dendrology.nucleus_leaf.cloth_standard_item',
        'dw_maya.DynEval.dendrology.nucleus_leaf.hair_standard_item',
        'dw_maya.DynEval.dendrology.nucleus_leaf.map_standarditem',
        'dw_maya.DynEval.dendrology.nucleus_leaf.nrigid_standarditem',
        'dw_maya.DynEval.dendrology.nucleus_leaf.nucleus_standarditem',
        'dw_maya.DynEval.dendrology.nucleus_leaf.rig_treeitem'
    ]

    # Track reloaded modules to avoid duplicates
    reloaded: Set[str] = set()

    def reload_module(module_name: str) -> None:
        """Recursively reload a module and its submodules."""
        if module_name in reloaded:
            return

        try:
            # Remove the module if it exists
            if module_name in sys.modules:
                module = sys.modules[module_name]
                importlib.reload(module)
                print(f"Reloaded: {module_name}")
            else:
                importlib.import_module(module_name)
                print(f"Imported: {module_name}")

            reloaded.add(module_name)

        except Exception as e:
            print(f"Failed to reload {module_name}: {e}")

    # Reload all modules
    for module_name in modules_to_reload:
        reload_module(module_name)

    print("\nDynEval modules reloaded successfully!")


def get_dyneval_windows() -> List:
    """Get all existing DynEval UI windows."""
    import maya.OpenMayaUI as omui
    from shiboken6 import wrapInstance
    from PySide6 import QtWidgets

    dyneval_windows = []

    # Get Maya's main window
    main_window = wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)

    # Find all DynEval windows
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if (isinstance(widget, QtWidgets.QMainWindow) and
                widget.windowTitle() == 'Dynamic Systems Manager' and
                widget.parent() == main_window):
            dyneval_windows.append(widget)

    return dyneval_windows


def reload_and_launch():
    """Reload all modules and launch a new instance of DynEval."""
    reload_dyneval()

    # Import and launch DynEval
    try:
        import DynEval.launch as launcher
        importlib.reload(launcher)
        launcher.launch()
        print("DynEval launched successfully!")
    except Exception as e:
        print(f"Failed to launch DynEval: {e}")


# Create a button in Maya's current shelf
def create_reload_button():
    """Create a shelf button for reloading DynEval."""
    current_shelf = cmds.tabLayout('ShelfLayout', query=True, selectTab=True)

    cmds.shelfButton(
        parent=current_shelf,
        image='pythonFamily.png',
        label='Reload DynEval',
        command='''
import importlib
import DynEval.reload_script as reloader
importlib.reload(reloader)
reloader.reload_and_launch()
''',
        sourceType='python',
        annotation='Reload and Launch DynEval'
    )
    print("Reload button created on current shelf!")


# Import UI modules
try:
    import dw_maya.DynEval.main_ui_beta as simtool
    import dw_maya.DynEval.sim_cmds
    import dw_maya.DynEval.sim_widget
except ImportError as e:
    print(f"Error importing simulation tool modules: {e}")
    raise

try:
    dyneval.deleteLater()
except:
    pass
reload_dyneval()
dyneval = simtool.DynEvalUI()
dyneval.show()
