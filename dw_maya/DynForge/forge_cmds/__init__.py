"""
forge_cmds - DynForge UI commands and Maya API calls.

This package holds the glue between the DynForge UI and the scene: thin command
functions the widgets call, plus the PySide2/PySide6 compatibility layer
(compat.py). Keep Maya/Qt specifics here so the UI widgets stay declarative.
"""