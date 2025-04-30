from cfx_houdini.TemplateManager import main_ui

def launch():
    hou_win = main_ui.getHoudiniWindow()
    tiui = main_ui.Template_Importer(hou_win)
    tiui.show()