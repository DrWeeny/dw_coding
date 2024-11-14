import sys
# ----- Edit sysPath -----#
rdPath = '/people/acportillo/public/py_scripts/local_render'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)
import renderlocal


renderlocal.start()
