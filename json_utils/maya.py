import maya.utils as mu
from .core import save_json, merge_nested_dict, load_json
import os, os.path

def save_json_deferred(file_path, data, indent=4):
    mu.executeDeferred(save_json, file_path, data, indent)

def merge_json(file_path: str, new_data: dict, indent=4, defer=False) -> bool:
    if defer:
        mu.executeDeferred(_merge_and_save_json, file_path, new_data, indent)
        return True
    return _merge_and_save_json(file_path, new_data, indent)

def _merge_and_save_json(file_path: str, new_data: dict, indent=4) -> bool:
    try:
        if os.path.exists(file_path):
            current_data = load_json(file_path) or {}
        else:
            folder = os.path.dirname(file_path)
            os.makedirs(folder, exist_ok=True)
            current_data = {}

        merged_data = merge_nested_dict(current_data, new_data)
        return save_json(file_path, merged_data, indent)
    except Exception as e:
        print(f"[merge_json] Error merging JSON at {file_path}: {e}")
        return False