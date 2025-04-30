"""
This module contains various commands for managing template assets and their metadata in Houdini.
The functions cover operations such as creating and saving JSON templates, safely deleting and moving files,
retrieving user data, handling backups, and managing versioning for template files.

Functions in this module include:
- create_json_templates: Initializes template JSON files if they do not already exist.
- safe_delete_on_disk: Safely deletes a file or directory, ensuring it's within the allowed template path.
- safe_move_on_disk: Moves a file or directory from one location to another with error handling.
- create_backup_folder: Creates a backup folder for a given asset category.
- get_user: Retrieves the current system user.
- get_current_time: Returns the current date and time formatted as a string.
- get_latest_approved_file: Finds the latest approved file for a given category, based on versioning.
- load_assets_from_json: Loads the asset data from the specified JSON file.
- save_assets_to_json: Saves updated asset data back to the JSON file, with optional full overwrite.
- get_archived_json_path: Returns the path to the archived template JSON file.
- get_archived_assets_data: Loads archived asset data, with an option to fetch full data or just template info.
- save_archived_entry: Saves a new entry to the archived JSON, appending it to the relevant category.
- get_iter: Returns the next version number based on existing versions in a category or the highest current version.

This module is integral to managing and maintaining template data in a structured way, supporting asset versioning, backup management, and ensuring data integrity during asset operations.

author : np-alexis
"""

import os
import shutil
import getpass
from datetime import datetime
import json
from typing import Optional, List, Dict, Any, Union, Set, Tuple
import re
from . import template_json_path, template_path, new_template_json, new_archived_template_json, template_json_archive_name
from .otl_io import make_dir

def create_json_templates():
    """
    Check if it is the first time the ui is launched, create both json
    Operations:
        - Creates the main template JSON file if it doesn't exist, writing the default template data.
        - Creates the archived template JSON file if it doesn't exist, writing the default archived template data.
    """
    if not os.path.isfile(template_json_path):
        with open(template_json_path, "w") as json_file:
            json.dump(new_template_json, json_file, indent=4)

    archived_path = get_archived_json_path()
    if not os.path.isfile(archived_path):
        with open(archived_path, "w") as json_file:
            json.dump(new_archived_template_json, json_file, indent=4)

def safe_delete_on_disk(file_path:str)->bool:
    """
    Safely delete a file or directory if it is inside the allowed template path.

    This function ensures that a file or directory is only deleted if it resides within
    the allowed `template_path` directory, preventing accidental deletion of files elsewhere.

    Args:
        file_path (str): The path to the file or directory to be deleted.

    Returns:
        bool: True if the file or directory was successfully deleted, False otherwise.
    """
    # Get the absolute path of the file to be deleted
    abs_file_path = os.path.abspath(file_path)

    # Check if the file is within the allowed mockup_path folder
    if not abs_file_path.startswith(template_path):
        print(f"Error: Attempted to delete a file outside of the allowed directory: {abs_file_path}")
        return False

    # Check if the file exists
    if os.path.exists(abs_file_path):
        try:
            # If it's a file, delete it
            if os.path.isfile(abs_file_path):
                os.remove(abs_file_path)
                print(f"File {abs_file_path} deleted successfully.")
                return True
            # If it's a directory, delete it
            elif os.path.isdir(abs_file_path):
                shutil.rmtree(abs_file_path)
                print(f"Directory {abs_file_path} deleted successfully.")
                return True
        except Exception as e:
            print(f"Error deleting {abs_file_path}: {e}")
            return False
    else:
        print(f"Error: File or directory does not exist: {abs_file_path}")
        return False

def safe_move_on_disk(source:str, destination:str):
    """
    Safely move a file or directory to a new destination.

    This function ensures that the destination directory exists and moves the specified
    file or directory from the source path to the destination. If the destination doesn't exist,
    it will be created.

    Args:
        source (str): The path to the file or directory to be moved.
        destination (str): The target path to move the file or directory to.

    Returns:
        None: The function performs the move operation without returning any value.
    """
    try:
        if not os.path.exists(destination):
            os.makedirs(destination)  # Ensure destination folder exists

        # Move the file or directory
        shutil.move(source, destination)
        print(f"Successfully moved {source} to {destination}")
    except FileNotFoundError as fnf_error:
        print(f"File not found: {fnf_error}")
    except PermissionError as perm_error:
        print(f"Permission denied: {perm_error}")
    except Exception as e:
        print(f"An error occurred: {e}")

def create_backup_folder(category_name: str) -> str:
    """
    Create a backup folder for a given category.

    This function creates a `.backup` folder inside the specified category's folder
    within the `template_path`. If the folder already exists, it simply returns the path.

    Args:
        category_name (str): The name of the category for which the backup folder is created.

    Returns:
        str: The path to the newly created or existing backup folder.
    """
    # Construct the backup folder path
    fullpath = os.path.join(template_path, category_name, ".backup")
    # create directory
    path = make_dir(fullpath)
    return path

def get_user() -> str:
    """
    Get the current system user.
    Returns:
        str: The username of the current user.
    """
    return getpass.getuser()

def get_current_time() -> str:
    """
    This function retrieves the current date and time in the format "YYYY-MM-DD HH:MM:SS".

    Returns:
        str: The current date and time as a string.
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_latest_approved_file(category_name: str, json_data: Optional[dict] = None) -> Optional[dict]:
    """
    Retrieve the latest approved file for a given category.

    This function filters through the files of the given category and returns the most
    recent approved file (based on versioning). If no approved files are found, it returns
    the newest file in the list.

    Args:
        category_name (str): The name of the category for which the approved file is fetched.
        json_data (dict, optional): The data containing the files, if provided. If not,
                                    it loads the data from the main template JSON file.

    Returns:
        dict or None: The latest approved file as a dictionary, or `None` if no files are found.
    """

    if not json_data:
        json_data = load_assets_from_json(template_json_path)

    # Get the files for the selected category
    files = json_data[0].get(category_name, {}).get("files", [])

    # Filter out approved files
    approved_files = [file for file in files if file.get("approved")]

    # Define a function to check if a file exists
    def file_exists(file_name):
        # Assuming all files are in a directory related to the category name
        category_path = os.path.join(template_path, category_name)
        file_path = os.path.join(category_path, file_name)
        return os.path.exists(file_path)

    # Sort files by version number (e.g., v001, v002, etc.)
    def extract_version(file_name):
        match = re.search(r'v(\d+)', file_name)  # Match v001, v002, etc.
        return int(match.group(1)) if match else 0  # Return version number as integer

    # Sort approved files by version number, descending order (latest version first)
    approved_files.sort(key=lambda x: extract_version(x["name"]), reverse=True)

    # Find the first approved file that exists
    for file in approved_files:
        if file_exists(file["name"]):
            return file

    # Return the newest file if no approved file exists
    return files[0] if files else None


def load_assets_from_json(file_path: str) -> Tuple[List[dict], int, list]:
    """
    Load assets data from a JSON file.

    This function loads the asset data from the specified JSON file and returns the templates
    and version information. The JSON file should contain the necessary structure for Houdini
    CFX templates.

    Args:
        file_path (str): The path to the JSON file to load.

    Returns:
        Tuple[List[dict], int]: A tuple containing two values:
            - A list of dictionaries representing the Houdini CFX templates.
            - An integer representing the version of the assets.
            - A list of user
    """
    try:
        with open(file_path, "r") as file:
            data = json.load(file)
        return data["houdini_cfx_templates"], data["version"], data["user_list"]

    except FileNotFoundError:
        print(f"File not found: {file_path}")
        raise  # Re-raise exception after logging it

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {file_path}: {e}")
        raise  # Re-raise exception after logging it

    except KeyError as e:
        print(f"Missing key {e} in JSON data from {file_path}")
        raise  # Re-raise exception after logging it

    except Exception as e:
        print(f"An unexpected error occurred while loading {file_path}: {e}")
        raise  # Re-raise exception after logging it


def save_assets_to_json(file_path:str,
                        folders: Union[Dict, List[Dict]],
                        version: int=None,
                        user_registration:str=None,
                        fulldata: bool = False) -> None:
    """
    Save assets data to a JSON file.

    This function saves the provided assets data (folders and version) to the specified JSON file.
    If `fulldata` is `False`, it only updates the templates and increments the version. If `fulldata`
    is `True`, it overwrites the entire data in the JSON file with the provided `folders`.

    Args:
        file_path (str): The path to the JSON file where the data will be saved.
        folders (Dict[dict]): A dict containing all the category dictionnaries.
        version (int): The version number to be saved. used to see if two persons access the json at same time
        fulldata (bool, optional): If `True`, overwrites the entire data. Defaults to `False`.

    Returns:
        None
    """
    try:
        with open(file_path, "r+") as file:
            data = json.load(file)  # Load existing data
            if not fulldata:
                # Ensure the updated folders are written back
                data["houdini_cfx_templates"] = folders
                data["version"] += 1  # Increment version
                if user_registration and user_registration not in data["user_list"]:
                    data["user_list"].append(user_registration)

            else:
                data=folders

            file.seek(0)  # Move to the beginning of the file to overwrite

            # Write the updated data to the file
            json.dump(data, file, indent=4)
            file.truncate()  # Ensure any leftover data after the new content is removed

    except FileNotFoundError:
        print(f"File not found: {file_path}")
        raise
    except PermissionError:
        print(f"Permission denied when writing to {file_path}")
        raise
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {file_path}: {e}")
        raise
    except Exception as e:
        print(f"Error saving to JSON: {e}")

def get_archived_json_path() -> str:
    """
    This function constructs and returns the absolute path to the archived template JSON file,
    using the global `template_path` and the predefined `template_json_archive_name`.

    Returns:
        str: The absolute path to the archived template JSON file.
    """
    archived_json = os.path.join(template_path, template_json_archive_name)
    return archived_json

def get_archived_assets_data(fulldata:bool=False)-> Union[Tuple[Any, Any], Dict[Any, Any]]:
    """
    Load the archived assets data from the archived template JSON file.

    This function loads the archived assets data from the archived template JSON file, returning
    either the "houdini_cfx_templates" and version as a tuple, or the full data if `fulldata` is `True`.

    Args:
        fulldata (bool, optional): If `True`, returns the entire data. Defaults to `False`,
                                    returning only the templates and version.

    Returns:
        Union[Tuple[List[dict], int], Dict[Any, Any]]:
            - If `fulldata` is `False`: a tuple containing the list of templates and version.
            - If `fulldata` is `True`: the entire data dictionary from the JSON file.
    """
    try:
        archived_json = os.path.join(template_path, template_json_archive_name)
        with open(archived_json, "r") as file:
            data = json.load(file)

        if fulldata:
            return data
        else:
            return data["houdini_cfx_templates"], data["version"]

    except FileNotFoundError:
        print(f"Archived JSON file not found: {archived_json}")
        raise

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {archived_json}: {e}")
        raise

    except KeyError as e:
        print(f"Missing key {e} in archived JSON data from {archived_json}")
        raise

    except Exception as e:
        print(f"An unexpected error occurred while loading archived assets data: {e}")
        raise

def save_archived_entry(category_name: str, entry: dict) -> None:
    """
    Save a new entry to the archived template JSON file.

    This function adds a new entry to the "files" list under the specified category in the archived
    template JSON file. If the category doesn't exist, it is created. The function then saves the updated
    data back to the archived JSON file.

    Args:
        category_name (str): The name of the category to which the entry will be added.
        entry (dict): The entry (file metadata) to be added to the category.

    Returns:
        None
    """
    archived_json = os.path.join(template_path, template_json_archive_name)
    try:
        with open(archived_json, "r+") as file:
            data = json.load(file)  # Load existing data

            # Ensure the category exists in the data structure
            if category_name not in data["houdini_cfx_templates"]:
                data["houdini_cfx_templates"][category_name] = {"files": []}

            # Append the new entry to the "files" list
            data["houdini_cfx_templates"][category_name]["files"].append(entry)

            # Move to the beginning of the file to overwrite the old content
            file.seek(0)

            # Write the updated data to the file
            json.dump(data, file, indent=4)
            # Truncate the file in case the new data is smaller than the previous data
            file.truncate()
    except FileNotFoundError:
        print(f"Archived JSON file not found: {archived_json}")
        raise

    except PermissionError:
        print(f"Permission denied when writing to {archived_json}")
        raise

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON from {archived_json}: {e}")
        raise

    except Exception as e:
        print(f"An unexpected error occurred while saving the archived entry: {e}")
        raise


def get_iter(category_name: str, next: bool = True) -> int:
    """
    Get the next available version number for a given category.

    This function retrieves the highest version number for the specified category from the archived
    template JSON file, and returns the next available version number. If `next` is set to `False`,
    it will return the highest version number found instead.

    Args:
        category_name (str): The name of the category to retrieve the version for.
        next (bool, optional): If `True`, returns the next available version number.
                                If `False`, returns the highest existing version number. Defaults to `True`.

    Returns:
        int: The next available version number if `next` is `True`, or the highest version number if `next` is `False`.
    """

    # Regex pattern for extracting _v### (e.g., _v001, _v002, etc.)
    version_pattern = re.compile(r"_v(\d{3})")

    max_version = 0

    json_data = load_assets_from_json(template_json_path)

    # Get the files for the selected category
    files = json_data[0][category_name]["files"]
    for f in files:
        # Search for version pattern
        match = version_pattern.search(f["name"].rsplit(".")[0])
        if match:
            version_number = int(match.group(1))  # Extract the version number as integer
            max_version = max(max_version, version_number)

    # Return the next version number (if `next` is True) or the max version found
    return max_version + 1 if next else max_version