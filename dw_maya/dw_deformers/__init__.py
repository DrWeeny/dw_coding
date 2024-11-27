import sys, os
# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

from .dw_create_wrap import createWrap
from .dw_core import is_deformer, editDeformer, editMembership, maya_edit_sets, paintWeights
from .dw_shrinkwrap import shrinkWrap
from .dw_stickies import createSticky