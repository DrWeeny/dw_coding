"""
hub_keys.py - DataHub key constants for DynForge cross-widget communication.

Mirrors DynEval's hub_keys. Widgets publish/subscribe to these keys rather than
holding direct references to each other.
"""


class DynForgeKeys:
    """Keys used on the DynForge DataHub."""

    # A guide row was selected in the guide list. Value: GuideBackend instance.
    GUIDE_SELECTED         = "dynforge.guide_selected"

    # The active creation mode changed in the editor. Value: str mode.
    CREATION_MODE          = "dynforge.creation_mode"