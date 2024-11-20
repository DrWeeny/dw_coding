"""
Maya Scene Cleaning Utilities

Tools for cleaning and maintaining Maya scenes, including:
- Removing unused nodes
- Cleaning up unknown/broken nodes
- Managing render layers
- Scene optimization

Common Usage:
    >>> # Clean all unused nodes
    >>> clean_unused_nodes()

    >>> # Remove broken nodes
    >>> delete_unknown_nodes()

    >>> # Clean render layers
    >>> delete_phantom_render_layers()
"""

from maya import cmds, mel
from typing import List, Optional
from ..dw_decorators import returnNodeDiff


@returnNodeDiff
def clean_unused_nodes() -> None:
    """
    Delete unused nodes in the Maya scene.
    Equivalent to 'Delete Unused Nodes' in Hypershade.

    Returns:
        Tuple[None, List[str]]: (None, list of deleted nodes)

    Example:
        >>> result, deleted = clean_unused_nodes()
        >>> print(f"Cleaned {len(deleted)} unused nodes")
    """
    try:
        mel.eval('MLdeleteUnused;')
    except Exception as e:
        raise RuntimeError(f"Failed to delete unused nodes: {str(e)}")


@returnNodeDiff
def delete_unknown_nodes(types: Optional[List[str]] = None) -> None:
    """
    Delete unknown/broken nodes in Maya scene.

    Args:
        types: Node types to delete (default: unknown, unknownDag, unknownTransform)

    Returns:
        Tuple[None, List[str]]: (None, list of deleted nodes)

    Example:
        >>> result, deleted = delete_unknown_nodes()
        >>> print(f"Removed {len(deleted)} unknown nodes")
    """
    # Default unknown types
    unknown_types = types or ["unknown", "unknownDag", "unknownTransform"]

    # Get unknown nodes
    unknown_nodes = cmds.ls(type=unknown_types) or []

    if not unknown_nodes:
        print("No unknown nodes found")
        return

    # Delete nodes individually for better error handling
    for node in unknown_nodes:
        try:
            cmds.delete(node)
            print(f"Deleted unknown node: {node}")

        except Exception as e:
            print(f"Failed to delete {node}: {str(e)}")


@returnNodeDiff
def delete_phantom_render_layers(pattern: str = "defaultRenderLayer*") -> None:
    """
    Delete phantom/duplicate render layers.

    Args:
        pattern: Name pattern for identifying phantom layers

    Returns:
        Tuple[None, List[str]]: (None, list of deleted layers)

    Example:
        >>> result, deleted = delete_phantom_render_layers()
        >>> print(f"Cleaned {len(deleted)} phantom layers")
    """
    # Find render layers matching pattern
    render_layers = cmds.ls(pattern, r=True, type='renderLayer') or []

    if not render_layers:
        print("No phantom render layers found")
        return

    # Delete layers individually
    for layer in render_layers:
        try:
            # Skip default render layer
            if layer == "defaultRenderLayer":
                continue

            cmds.delete(layer)
            print(f"Deleted render layer: {layer}")

        except Exception as e:
            print(f"Failed to delete layer {layer}: {str(e)}")
