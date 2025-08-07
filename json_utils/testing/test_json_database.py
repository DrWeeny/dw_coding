"""
Test JSONDatabase and JSONFileProxy usage.
"""

import os
import sys
sys.path.insert(0, "..")

from cfx_utils.json_utils.core import JSONDatabase  # replace with your actual module name

def test_json_database():
    folder = "db_test"
    os.makedirs(folder, exist_ok=True)
    filename = "testdb"

    db = JSONDatabase(folder, make_folder=True)

    data = {"alpha": 1, "beta": 2}
    print(f"[TEST] Saving data to {filename}.json")
    success = db.save(filename, data)
    print("Save success:", success)

    print("[TEST] Loading data back...")
    loaded = db.load(filename)
    print("Loaded data:", loaded)

    assert loaded == data, "Database load/save mismatch"

    print("[TEST] Updating entry...")
    db.update_entry(filename, "alpha", 42)
    updated = db.get_entry(filename, "alpha")
    print("Updated 'alpha':", updated)
    assert updated == 42

    # Clean up
    os.remove(os.path.join(folder, filename + ".json"))
    os.rmdir(folder)
    print("[TEST] Cleaned up database files")

if __name__ == "__main__":
    test_json_database()
