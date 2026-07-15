"""CfxForge recipe editor UI.

Summary:
    PySide6-only (deliberate exception to the repo PySide2-fallback rule).
    The UI is an *editor of the recipe document*: the json stays the single
    source of truth, the graph view and panels only mutate Recipe.nodes.
    Runs outside any DCC (plain python + PySide6) since the CfxForge core
    is import-light; inside Maya the dry-run additionally resolves the
    maya_ops backends.

Example:
    from CfxForge.ui import launch
    launch()                      # or: python CfxForge/ui/main_ui.py

Author:
    DrWeeny
"""


def launch(path: str = None):
    from CfxForge.ui import main_ui
    return main_ui.launch(path)

if __name__ == "__main__":
    cfxforge_ui = launch()