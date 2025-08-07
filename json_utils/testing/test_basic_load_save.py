"""
Test basic JSON load and save functions.
"""

import os
import sys
sys.path.insert(0, "..")  # Adjust as needed to import your main module

from cfx_utils.json_utils.core import load_json, save_json  # replace with your actual module name

def test_basic_load_save():
    test_path = "test_data.json"
    test_data = {"name": "Test", "value": 123}

    print("[TEST] Saving JSON...")
    if save_json(test_path, test_data):
        print("[PASS] JSON saved")

    print("[TEST] Loading JSON...")
    loaded = load_json(test_path)
    print("Loaded data:", loaded)

    assert loaded == test_data, "Loaded data does not match saved data"

    os.remove(test_path)
    print("[TEST] Cleaned up test file")

if __name__ == "__main__":
    test_basic_load_save()
