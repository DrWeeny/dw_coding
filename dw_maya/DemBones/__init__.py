"""DemBones - Maya tool for SSDR skin decomposition via the DemBones CLI.

Bakes a deforming mesh (cloth sim, blendshape animation) into a joint cloud +
skinCluster by driving the bundled DemBones.exe (EA, BSD-3) over an Alembic
cache. The exe is multithreaded C++ and an order of magnitude faster than the
pure-Python binding, so this tool shells out to it via QProcess.

Launch from inside Maya:
    from dw_maya.DemBones import main_ui
    main_ui.launch()

Layout
------
    main_ui.py          core window + solve orchestration (wires panels)
    dem_cmds.py         scene discovery, validation, FBX export, exe args,
                        generation I/O, QProcess SolveRunner
    wgt_source.py       target mesh / abc / range / use-rig panel
    wgt_params.py       basic + advanced solve params
    wgt_generations.py  fbx + sidecar generations list
    compat.py           PySide2 / PySide6 shim
    bin/<OS>/DemBones   bundled executable (not in VCS by default)

The panels are plain QWidgets that talk to main_ui through getters and a couple
of Qt signals - no DataHub (kept for bigger multi-widget tools like DynEval).

Author:
    DrWeeny
"""

from dw_maya.DemBones import main_ui
from dw_maya.DemBones.main_ui import launch