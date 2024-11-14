import sys
# ----- Edit sysPath -----#
rdPath = '/people/ptorrevillas/public/py_scripts'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

import xg_description_share as xds

# To Export
xds.export_ui()

#To Install
xds.install_ui()
