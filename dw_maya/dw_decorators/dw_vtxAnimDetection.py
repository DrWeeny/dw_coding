import maya.cmds as cmds
import sys, os
from functools import wraps

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)


def vtxAnimDetection(argument):
    """
    Decorator to detect vertex animation on a given mesh.

    If vertex animation is detected, it cancels the deformer command.

    Args:
        argument (str): The name of the mesh you want to detect vertex animation on.

    Returns:
        function: The wrapped function, if no vertex animation is detected.
    """

    def decorator(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            msg_error = "Vertex animation detected, canceling deformer command"

            # Check if the argument has a valid shape node
            mesh_shape = cmds.listRelatives([a.split(".")[0] for a in argument], s=True)
            if not mesh_shape:
                print(f"Error: {argument} does not have a valid shape node.")
                return
            mesh_shape = mesh_shape[0]

            vtx_component  = cmds.ls(f"{mesh_shape}_pnts_*__pntx", fl=1)
            # check on tweak level too because you could be evil
            tweak_node = cmds.listConnections(mesh_shape, type='tweak')

            # delay import to avoid circular call
            from dw_maya.dw_widgets import ErrorWin

            if vtx_component:
                print(msg_error)
                err = ErrorWin()
                return

                cmds.error()
            elif tweak_node:
                tweak_vtx_component = cmds.ls(f"{tweak_node[-1]}_vlist_*__xVertex", fl=1)
                if tweak_vtx_component:
                    print(msg_error)
                    err = ErrorWin()
                    return

            return function(*args, **kwargs)
        return wrapper
    return decorator
