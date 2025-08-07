"""
Test merge_json and nested dict merging.
"""

import os
import sys
sys.path.insert(0, "..")

from cfx_utils.json_utils.core import merge_json, load_json

def test_merge_json():
    path = "merge_test.json"
    initial = {"a": 1, "b": {"c": 2, "d": 3}}
    new_data = {"b": {"c": 20, "e": 5}, "f": 100}

    # Save initial
    merge_json(path, initial)
    print(f"[TEST] Initial data saved: {initial}")

    # Merge new_data
    merge_json(path, new_data)
    print(f"[TEST] Merged data: {new_data}")

    merged = load_json(path)
    print("Resulting merged dict:", merged)

    expected = {"a": 1, "b": {"c": 20, "d": 3, "e": 5}, "f": 100}
    assert merged == expected, "Merge result incorrect"

    os.remove(path)
    print("[TEST] Cleaned up merge test file")

if __name__ == "__main__":
    test_merge_json()
