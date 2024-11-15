import sys
import os

# ----- Dynamic sys.path Adjustment -----
rdPath = os.path.join(os.path.dirname(__file__), "..", "dw_open_tools")
if rdPath not in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

try:
    from maya import cmds, mel
    print("Maya commands loaded successfully in dw_decorators.")
except ImportError as e:
    print("Warning: Maya commands not available. Error:", e)

# Explicit imports for frequently used decorators
from .dw_acceptString import acceptString
from .dw_benchmark import timeIt, printDate
from .dw_complete_sound import complete_sound
from .dw_disable_solvers import tmp_disable_solver
from .dw_load_plugin import load_plugin
from .dw_returnNodeDiff import returnNodeDiff
from .dw_undo import singleUndoChunk, repeatable
from .dw_viewportOff import viewportOff
from .dw_decorators_other import evalManager_DG, evalManagerState
