import dw_maya.PresetTool.main_ui as pmuiMain
try:
    pmui.deleteLater()
except:
    pass
presetMan = pmuiMain.PresetManager()
presetMan.show()
