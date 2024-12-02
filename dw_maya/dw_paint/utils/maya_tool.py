from maya import cmds, mel

def open_tools_window():
    """Open Maya's tool property window"""
    mel.eval("toolPropertyWindow;")


def get_current_artisan_map():

    # Get current context to verify we're in Artisan
    current_ctx = cmds.currentCtx()

    # Check if we're in artAttrContext
    if current_ctx not in ["artAttrNClothContext",
                           "artAttrContext"]:
        return None, None, None

    # Get the attribute being painted
    painted_attr = cmds.artAttrCtx(current_ctx, query=True, attrSelected=True)
    node_type, painted_node, painted_map = painted_attr.split(".")

    return painted_node, painted_map, node_type