# built-in
import sys, os, re

import dw_maya.SpanSmooth.main_ui as span_ui

try:
    anmw_ui.deleteLater()
except:
    pass
anmw_ui = span_ui.AnimWireSmooth()
anmw_ui.show()
