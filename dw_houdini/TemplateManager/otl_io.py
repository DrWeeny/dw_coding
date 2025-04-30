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

author : np-alexis
"""

import os
import hou
from typing import Optional

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

def write_otl(folder_path: str,
              filename: str,
              ext: str = '.otl',
              isroot: str = "obj") -> Optional[str]:
    """
    Write the selected nodes to an OTL file at the specified location.

    Args:
        folder_path (str): The folder where the OTL file will be saved.
        filename (str): The name of the OTL file to write.
        ext (str, optional): The extension to use for the file. Defaults to '.otl'.
        isroot (str, optional): make sure the node selected is at the top level

    Returns:
        Optional[str]: The full file path if the operation was successful, or None if no nodes were selected.
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

    if not check_hou_context(isroot=isroot):
        hou.ui.displayMessage(f"Only node at /{isroot} root level can be saved.")
        raise Exception(f"Only node at /{isroot} root level can be saved")

    fullpath = os.path.join(folder_path, filename)

    # Write files.
    parent = nodes[0].parent()
    if not all(node.parent() == parent for node in nodes):
        raise Exception("Nodes must have the same parent.")

    parent.saveItemsToFile(nodes, fullpath)
    print(f"otl has been written to {fullpath}")
    return fullpath


def load_otl(fullpath: str):
    """
    Loads an OTL or HIP file into the current Houdini scene. The function checks for the correct file
    extension (.otl or .hip) and ensures the file exists before loading it.

    Args:
        fullpath (str): The full path to the OTL or HIP file to load.

    Returns:
        None: The function does not return anything. It loads the items from the file into the scene.
    """
    _ext = fullpath.split(".")[-1]
    if _ext not in ["hip", "otl"]:
        print("Extension missing in the path, expecting 'hip' or 'otl'.")
        return

    if not os.path.exists(fullpath):
        print(f"Error - file doesnt exists: {fullpath}")
        return None

    # READ
    def get_current_network_tab():
        network_tabs = [t for t in hou.ui.paneTabs() if t.type() == hou.paneTabType.NetworkEditor]
        if network_tabs:
            for tab in network_tabs:
                if tab.isCurrentTab():
                    return tab
        return None


    exec_network = get_current_network_tab() # Grab parent.

    parent = exec_network.pwd()

    # Load from selected file.
    parent.loadItemsFromFile(fullpath)

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