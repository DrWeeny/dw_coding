"""
Test LockedJSON class locking, loading, saving.
"""

import os
import sys
sys.path.insert(0, "..")

from cfx_utils.json_utils.core import LockedJSON  # replace with your actual module name

def test_locked_json():
    path = "locked_test.json"
    data = {"locked": True}

    lj = LockedJSON(path)

    print("[TEST] Acquiring lock and saving...")
    lj.acquire_lock()
    try:
        lj.save(data)
        print("[PASS] Saved with lock")
    finally:
        lj.release_lock()

    print("[TEST] Loading locked JSON...")
    loaded = lj.load()
    print("Loaded:", loaded)

    assert loaded == data, "LockedJSON load/save mismatch"

    os.remove(path)
    print("[TEST] Cleaned up test file")

if __name__ == "__main__":
    test_locked_json()
