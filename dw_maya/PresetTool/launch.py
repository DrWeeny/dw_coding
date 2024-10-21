import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import .main_ui as pmuiMain
pmuiMain.reload()
try:
    pmui.deleteLater()
except:
    pass
presetMan = pmuiMain.PresetManager()
presetMan.show()
