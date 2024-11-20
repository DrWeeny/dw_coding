import maya.cmds as cmds
from functools import wraps
from typing import Callable, Union, List, Any


def vtxAnimDetection(mesh_name: Union[str, List[str]]) -> Callable:
    """
    Decorator to detect vertex animation on a given mesh before applying deformers.
    Cancels the deformer command if vertex animation is detected.

    Args:
        mesh_name: Name of mesh(es) to check for vertex animation

    Example:
        @vtxAnimDetection('pSphere1')
        def apply_deformer(mesh):
            # Only executes if no vertex animation found
            cmds.nonLinear(mesh, type='bend')
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Normalize input to list
            meshes = [mesh_name] if isinstance(mesh_name, str) else mesh_name

            # Get shape nodes
            for mesh in meshes:
                base_name = mesh.split(".")[0]
                shapes = cmds.listRelatives(base_name, shapes=True)

                if not shapes:
                    raise ValueError(f"No valid shape node found for {base_name}")

                shape = shapes[0]

                # Check for direct point animation
                if cmds.ls(f"{shape}_pnts_*__pntx", fl=True):
                    _show_error("Vertex animation detected on points")
                    return None

                # Check for tweak node animation
                tweak_nodes = cmds.listConnections(shape, type='tweak')
                if tweak_nodes:
                    tweak_anims = cmds.ls(
                        f"{tweak_nodes[-1]}_vlist_*__xVertex",
                        fl=True
                    )
                    if tweak_anims:
                        _show_error("Vertex animation detected on tweak node")
                        return None

                # No vertex animation found, proceed with function
            return func(*args, **kwargs)

        return wrapper

    return decorator

def _show_error(message: str) -> None:
    """Display error message and window."""
    from dw_maya.dw_widgets import ErrorWin
    print(f"Error: {message}, canceling deformer command")
    ErrorWin()
