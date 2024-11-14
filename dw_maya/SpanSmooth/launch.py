# built-in
import sys, os, re

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import dw_maya.SpanSmooth.main_ui as span_ui

try:
    anmw_ui.deleteLater()
except:
    pass
anmw_ui = span_ui.AnimWireSmooth()
anmw_ui.show()
