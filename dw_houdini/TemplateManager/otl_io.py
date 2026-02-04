"""
Module for managing Houdini OTL (Houdini Digital Asset) operations, including:

- Writing OTL files
- Loading OTL/HIP files into the Houdini scene
- Merging .hip files
- Managing directories for saving/loading files
- Ensuring correct context for node selection in Houdini

Functions:
- make_dir(path: str) -> str
- get_hou_selection_length() -> int
- check_hou_context(isroot: str = "obj") -> bool
- write_otl(folder_path: str, filename: str, ext: str = '.otl', isroot: str = "obj") -> Optional[str]
- load_otl(fullpath: str) -> None
- merge_file(filepath: str) -> None

author : drweeny
"""

import os
import hou
from typing import Optional, Tuple

def make_dir(path: str) -> str:
    """Create all the path folder tree if it doesn't exist."""
    if not os.path.exists(path):
        os.makedirs(path)
    return path

def get_hou_selection_length() -> int:
    """Return the number of selected nodes in Houdini."""
    return len(hou.selectedNodes())


def check_hou_context(isroot: str = "obj") -> bool:
    """Check if the selected node is in the correct Houdini context."""
    selection = hou.selectedNodes()
    for node in selection:
        node_path = node.path()
        node_elem = node_path.split("/")
        if isroot not in node_elem[1] or len(node_elem) > 3:
            print(f"Node {node_path} is not in the correct context. Expected root: {isroot}")
            return False
    return True

def check_node_context(hou_node:hou.Node)->str:
    """
    Check the Houdini context category of a node.
    Returns:
        str: The context category name (e.g., 'Sop', 'Object', 'Dop', 'Vop').
    """
    return hou_node.type().category().name()

def get_current_network_context() -> Tuple[Optional[hou.Node], Optional[str]]:
    """
    Get the current network editor's parent node and its context.

    Returns:
        tuple: (parent_node, context_name) or (None, None) if no network editor found.
    """
    network_tabs = [t for t in hou.ui.paneTabs() if t.type() == hou.paneTabType.NetworkEditor]
    if network_tabs:
        for tab in network_tabs:
            if tab.isCurrentTab():
                parent = tab.pwd()
                # Get the child type context of this parent
                child_type = parent.childTypeCategory()
                if child_type:
                    return parent, child_type.name()
                return parent, None
    return None, None

def get_selection_context() -> Optional[str]:
    """
    Get the context category of the current selection.

    Returns:
        str: The context category name, or None if nothing selected.
    """
    nodes = hou.selectedNodes()
    if not nodes:
        return None
    return check_node_context(nodes[0])

def write_otl(folder_path: str,
              filename: str,
              ext: str = '.otl',
              isroot: Optional[str] = "obj",
              store_context: bool = False) -> Optional[Tuple[str, Optional[str]]]:
    """
    Write the selected nodes to an OTL file at the specified location.

    Args:
        folder_path: The folder where the OTL file will be saved.
        filename: The name of the OTL file to write.
        ext: The extension to use for the file. Defaults to '.otl'.
        isroot: Make sure the node selected is at the top level (None to skip check).
        store_context: If True, return the node context for metadata storage.

    Returns:
        tuple: (fullpath, context) if successful, or None if no nodes selected.
               context is the node category name (e.g., 'Sop', 'Object').
    """

    _ext = filename.split(".")[-1]
    if not _ext in ["hip", "otl"]:
        filename+=ext

    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

    nodes=hou.selectedNodes()

    if not nodes:
        hou.ui.displayMessage("Nothing selected!")
        return None

    fullpath = os.path.join(folder_path, filename)
    # Get the context of the selected nodes for metadata
    node_context = check_node_context(nodes[0]) if nodes else None

    if isroot:
        if not check_hou_context(isroot=isroot):
            hou.ui.displayMessage(f"Only node at /{isroot} root level can be saved.")
            raise Exception(f"Only node at /{isroot} root level can be saved")

        parent = nodes[0].parent()
        if not all(node.parent() == parent for node in nodes):
            raise Exception("Nodes must have the same parent.")

        parent.saveItemsToFile(nodes, fullpath)
    else:
        # For user snippets, save from any context
        parent = nodes[0].parent()
        if not all(node.parent() == parent for node in nodes):
            raise Exception("Nodes must have the same parent.")

        parent.saveItemsToFile(nodes, fullpath)


    print(f"OTL has been written to {fullpath} (context: {node_context})")

    if store_context:
        return fullpath, node_context
    return fullpath, None


def load_otl(fullpath: str, expected_context: str = None) -> bool:
    """
    Load an OTL or HIP file into the current Houdini scene.

    For user snippets, attempts to load into a matching context. If the current
    network context matches the expected context, loads there. Otherwise,
    prompts the user or loads at the default location.

    Args:
        fullpath: The full path to the OTL or HIP file to load.
        expected_context: The expected node context (e.g., 'Sop', 'Object').
                         If provided, validates against current network context.

    Returns:
        bool: True if loaded successfully, False otherwise.
    """
    _ext = fullpath.split(".")[-1]
    if _ext not in ["hip", "otl"]:
        print("Extension missing in the path, expecting 'hip' or 'otl'.")
        return False

    if not os.path.exists(fullpath):
        print(f"Error - file doesn't exist: {fullpath}")
        return False

    # Get current network context
    current_parent, current_context = get_current_network_context()

    if current_parent is None:
        hou.ui.displayMessage("No active Network Editor found.")
        return False

    # If we have an expected context, validate it matches
    if expected_context:
        if current_context and current_context != expected_context:
            result = hou.ui.displayMessage(
                f"This snippet was saved in a {expected_context} context, "
                f"but you're currently in a {current_context} context.\n\n"
                f"Do you want to load it anyway?",
                buttons=("Load Anyway", "Cancel"),
                default_choice=1,
                close_choice=1
            )
            if result == 1:  # Cancel
                return False

    # Load items into the current network parent
    try:
        current_parent.loadItemsFromFile(fullpath)
        print(f"Loaded {fullpath} into {current_parent.path()}")
        return True
    except hou.OperationFailed as e:
        hou.ui.displayMessage(f"Failed to load file: {e}")
        return False

def merge_file(filepath:str):
    """
    Merges a Houdini (.hip) file into the current Houdini session.

    Args:
        filepath (str): The path to the .hip file to merge.

    Returns:
        None: The function does not return anything. It merges the .hip file into the current session.
    """
    if filepath.endswith('.hip'):
        hou.hipFile.merge(filepath, ignore_load_warnings=True)
    else:
        print("Invalid file format. Expected .hip file.")