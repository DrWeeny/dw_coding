from maya import mel

def open_tools_window():
    """Open Maya's tool property window"""
    mel.eval("toolPropertyWindow;")