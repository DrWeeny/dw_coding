"""
SkinMatch - skin weight transfer with an explicit, visible influence mapping.

Kept import-light on purpose (no Maya side effects at import); the UI modules
are pulled in by :func:`launch`.

Usage::

    from dw_maya.dw_deformers import SkinMatch
    SkinMatch.launch()
"""


def launch():
    """Open the SkinMatch window."""
    from dw_maya.dw_deformers.SkinMatch import main_ui
    return main_ui.launch()