# built-in
import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from .dw_acceptString import acceptString
from .dw_benchmark import timeIt
from .dw_disable_solvers import tmp_disable_solver
from .dw_load_plugin import load_plugin
from .dw_returnNodeDiff import returnNodeDiff
from .dw_undo import singleUndoChunk
from .dw_viewportOff import viewportOff
