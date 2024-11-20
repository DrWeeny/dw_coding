import os
import getpass
from maya import cmds

def get_folder(custom_path=None):
    """
    Returns a folder path for storing files. If a custom path is provided, it returns that path.
    If no custom path is provided and a Maya scene is open, it defaults to a subfolder in the Maya scene directory.

    Args:
        custom_path (str, optional): If provided, returns this as the folder path. Must start with '/'.

    Returns:
        str or bool: A valid folder path as a string, or False if no valid path is found.
    """

    # Check if the current Maya file is saved (exists in the file system)
    fullpath = cmds.file(q=1, loc=1)
    is_in_file = fullpath != 'unknown'

    user = getpass.getuser()

    # If no custom path is provided, return a default folder in the scene directory
    if not custom_path and is_in_file:
        # Default folder structure in the current scene's directory
        scene_dir = os.path.dirname(fullpath)
        rig_data = os.path.join(scene_dir, 'json', user)

        # Create the folder if it doesn't exist
        if not os.path.exists(rig_data):
            os.makedirs(rig_data)

        return rig_data

    # If a custom path is provided, ensure it starts and ends with '/'
    elif custom_path:
        if custom_path.startswith('/'):
            if not custom_path.endswith('/'):
                custom_path += '/'
            return custom_path
        else:
            return False

    # If no valid scene is open and no custom path is provided
    return False


# create the folder tree
def make_dir(path=str):
    """
    create all the path folder tree
    :return: path string
    """
    if not os.path.exists(path):
        os.makedirs(path)
    return path