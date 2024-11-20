from pathlib import Path
import maya.utils as mu
from typing import Any, Dict, Optional, List
import json



def save_json(file_path: str, data: Dict[str, Any], indent=4, defer=False) -> bool:
    """
    Save data to a JSON file, optionally deferring to run when Maya is idle.

    Args:
        file_path (str): Path where the JSON file will be saved.
        data (dict): Dictionary to be stored in JSON format.
        indent (int): JSON indentation level.
        defer (bool): If True, save the JSON file when Maya is idle.
    Returns:
        bool: True if successful, False otherwise.
    """
    if defer:
        mu.executeDeferred(_write_json, file_path, data, indent)
        return True
    return _write_json(file_path, data, indent)

def _write_json(file_path: str, data: dict, indent=4) -> bool:
    """Helper function to write JSON data to file."""
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w') as json_file:
            json.dump(data, json_file, indent=indent)
        return True
    except Exception as e:
        print(f"Error saving JSON to {file_path}: {e}")
        return False


def load_json(path: str) -> Optional[Dict[str, Any]]:
    """
    Load and return data from a JSON file.

    Args:
        path (str): Path to the JSON file.
    Returns:
        Optional[Dict[str, Any]]: Loaded dictionary from the JSON file, or None if loading fails.
    """
    path = Path(path)
    if not path.exists():
        print(f"Error: File {path} does not exist.")
        return None

    try:
        with path.open('r') as fp:
            return json.load(fp)
    except Exception as e:
        print(f"Error loading JSON from {path}: {e}")
        return None


def update_json(key: str, value: Any, path: str) -> bool:
    """
    Add or update a key-value pair in an existing JSON file.

    Args:
        key (str): Key to add or update in the JSON file.
        value (Any): Value to associate with the key.
        path (str): Path to the JSON file.
    Returns:
        bool: True if the update was successful, False otherwise.
    """
    path = Path(path)
    if not path.exists():
        print(f"Error: File {path} does not exist.")
        return False

    try:
        data = load_json(path) or {}
        data[key] = value
        return save_json(str(path), data)
    except Exception as e:
        print(f"Error updating JSON at {path}: {e}")
        return False


def save_json_safely(file_path: str, data: dict, indent=4):
    """
    Write JSON data to a file in a thread-safe manner for Maya.

    Args:
        data (dict): Data to write to JSON.
        file_path (str): Path to the JSON file.
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure directory exists

    with file_path.open('w') as json_file:
        json.dump(data, json_file, indent=indent)

def merge_nested_dict(dict1, dict2):
    """
    Recursively merge two dictionaries, where values from `dict2` override those in `dict1`.
    If a value is a dictionary in both `dict1` and `dict2`, it will be merged recursively.
    Otherwise, values from `dict2` overwrite `dict1`.

    Args:
        dict1 (dict): Base dictionary to merge into.
        dict2 (dict): Dictionary to merge, overriding or adding to `dict1`.

    Returns:
        dict: A new dictionary with merged values.
    """
    merged = dict1.copy()  # Make a copy of dict1 to avoid modifying it directly

    for key in dict2:
        if key in merged:
            if isinstance(merged[key], dict) and isinstance(dict2[key], dict):
                # Recursively merge if both are dictionaries
                merged[key] = merge_nested_dict(merged[key], dict2[key])
            else:
                # If one of the values is not a dict, replace the existing value
                merged[key] = dict2[key]
        else:
            # Key only exists in dict2, add it to the result
            merged[key] = dict2[key]

    return merged

def merge_json(file_path: str, new_data: dict, indent=4, defer=False) -> bool:
    """
    Merge new data into an existing JSON file.

    Args:
        file_path (str): Path to the JSON file.
        new_data (dict): Dictionary to merge with the existing data.
        indent (int): JSON indentation level.
        defer (bool): If True, merge and save JSON when Maya is idle.
    Returns:
        bool: True if successful, False otherwise.
    """
    if defer:
        mu.executeDeferred(_merge_and_save_json, file_path, new_data, indent)
        return True
    return _merge_and_save_json(file_path, new_data, indent)

def _merge_and_save_json(file_path: str, new_data: dict, indent=4) -> bool:
    """Helper function to merge data into an existing JSON file and save it."""
    path = Path(file_path)
    try:
        if path.exists():
            current_data = load_json(str(path)) or {}
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            current_data = {}

        # Merge and save
        merged_data = merge_nested_dict(current_data, new_data)
        return save_json(str(path), merged_data, indent)
    except Exception as e:
        print(f"Error merging JSON at {file_path}: {e}")
        return False