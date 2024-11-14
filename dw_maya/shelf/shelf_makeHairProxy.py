import sys, os

# ----- Edit sysPath -----#
rdPath = ['/home/abtidona/private/PycharmProjects/RND/dw_tools/maya/RFX']
if not os.path.isdir(rdPath):
    rdPath = ['/people/abtidona/public/dw_tools/maya/']
rdPath.append("/people/ptorrevillas/public/py_scripts/create_proxy_hair")
for rd in rdPath:
    if not rd in sys.path:
        print "Add %r to sysPath" % rd
        sys.path.insert(0, rd)

import xg_proxy
import dw_decorators as dwdeco
reload(xg_proxy)

@dwdeco.complete_sound
@dwdeco.viewportOff
def make_proxy_hair():
    xg_proxy.create_all()


make_proxy_hair()
