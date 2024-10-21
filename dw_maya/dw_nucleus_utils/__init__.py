# built-in
import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from .dw_create_nucleus import create_nucleus
from .dw_nconstraint_preset import saveNConstraintRig
