# built-in
import sys, os

# ----- Edit sysPath -----#
rdPath = '/user_data/AMJB/coding/dw_tools/maya/DNEG2'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

from .dw_maya_attrs import *
from .dw_maya_components import *
from .dw_maya_data import *
from .dw_maya_time import *
from .dw_maya_gui import *
from .dw_maya_message import *
from .dw_maya_object import *
from .dw_maya_prefs import *
from .dw_maya_raycast import *