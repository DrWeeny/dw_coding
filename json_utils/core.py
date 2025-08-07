"""
JSON Utility Library
--------------------

This module provides safe, atomic, and lock-protected JSON file operations with
support for:

- Safe JSON loading with fallback encoding
- Atomic file saves to avoid corruption
- File locking to prevent concurrent write conflicts
- Recursive dictionary merging
- Managing collections of JSON files via JSONDatabase and JSONFileProxy
- Simple API to update/read individual keys safely

Usage Examples:

1. Load and save a JSON file safely:
    data = load_json("config.json")
    data["new_key"] = "value"
    save_json_atomic("config.json", data)

2. Update a JSON file safely using a lock:
    def update_fn(d):
        d["counter"] = d.get("counter", 0) + 1
    modify_json_locked("data.json", update_fn)

3. Use JSONDatabase to manage multiple JSON files in a folder:
    db = JSONDatabase("my_json_folder", make_folder=True)
    print(db._files)  # List of JSON filenames (without extension)
    db.save("settings", {"theme": "dark"})
    settings = db.load("settings")
    db.update_entry("settings", "volume", 80)

4. Use JSONFileProxy for file-specific operations:
    proxy = db["settings"]
    print(proxy.get_entry("theme"))  # "dark"
    proxy.update_entry("language", "en-US")
    proxy.save({"theme": "light", "language": "en-US"})

5. Merge JSON data with existing content:
    new_data = {"user": {"name": "Alice", "age": 30}}
    merge_json("user_profile.json", new_data)

6. Remove a key safely (recommended to use locked version):
    remove_entry_locked("data.json", "obsolete_key")

Note:
- All writes are atomic and protected with lock files.
- Locks have a timeout and polling mechanism to avoid deadlocks.
- Encoding is UTF-8 by default but can be configured per JSONDatabase.

"""

import json
import os, os.path
import os
import time
import open

def update_json_modification_timestamp(json_path:str):
    try:
        os.utime(json_path, None)  # Update modified time
        return True
    except Exception as e:
        logger.error(f"[touch_json] Could not update timestamp for {json_path}: {e}")
        return False

def load_json(path: str, encoding="utf-8") -> dict:
    try:
        with open(path, "r", encoding=encoding) as f:
            return json.load(f)
    except UnicodeDecodeError:
        if encoding == "utf-8":
            return load_json(path, encoding="cp932")
        raise
    except Exception as e:
        logger.error(f"[load_json] Failed to load {path}: {e}")
        return {}

def save_json(file_path: str, data: dict, indent=4) -> bool:
    try:
        folder = os.path.dirname(file_path)
        os.makedirs(folder, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
        return True
    except Exception as e:
        logger.error(f"[save_json] Failed to save {file_path}: {e}")
        return False

def save_json_atomic(file_path: str, data: dict, indent=2) -> bool:
    folder = os.path.dirname(file_path)
    os.makedirs(folder, exist_ok=True)
    temp_path = file_path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, file_path)  # atomic rename
        return True
    except Exception as e:
        logger.error(f"[save_json_atomic] Failed to save {file_path}: {e}")
        return False

def save_json_locked(json_path, new_data):
    locked_json = LockedJSON(json_path)
    try:
        with locked_json:
            logger.debug(f"Loading JSON for saving: {json_path}")
            # Load existing data if needed (optional)
            # existing_data = locked_json.load()  # If you want to merge instead of overwrite

            logger.debug(f"Saving new JSON data to: {json_path}")
            locked_json.save(new_data)
    except Exception as e:
        logger.error(f"[save_json_locked] Failed to save locked JSON to {json_path}: {e}")
        return False
    return True


def safe_update_root_field(json_path, updates):
    """Safely update top-level keys in the JSON file."""
    def _update(data):
        for key, value in updates.items():
            data[key] = value

    modify_json_locked(json_path, _update)

def remove_entry_locked(json_path: str, key: str) -> bool:
    def _remove(data):
        if key in data:
            del data[key]
    try:
        modify_json_locked(json_path, _remove)
        return True
    except Exception as e:
        logger.error(f"[remove_entry_locked] Failed to remove {key} from {json_path}: {e}")
        return False

def read_entry(path: str, key: str, default=None):
    try:
        data = load_json(path)
        return data.get(key, default)
    except Exception as e:
        logger.error(f"[read_entry] Failed to read {key} from {path}: {e}")
        return default

def safe_update_asset_field(json_path, asset_name, updates):
    """Updates multiple fields on a given asset safely."""
    def _update(data):
        for key, value in updates.items():
            data[asset_name][key] = value

    modify_json_locked(json_path, _update)

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
        logger.error(f"[merge_json] Error merging JSON at {file_path}: {e}")
        return False

def ensure_json_exists(path: str, default: dict = None) -> bool:
    """Ensure a JSON file exists. If not, create it with default content."""
    if not os.path.exists(path):
        return save_json(path, default or {})
    return True


def acquire_lock(lock_path, timeout=30, poll_interval=0.5):
    """
    Attempt to acquire a lock by creating a lock file.
    Waits and retries if it already exists.
    """
    start_time = time.time()
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            logger.debug(f"Lock acquired: {lock_path}")
            return
        except FileExistsError:
            if (time.time() - start_time) > timeout:
                raise TimeoutError(f"Timeout waiting for lock: {lock_path}")
            logger.error(f"Waiting for lock: {lock_path}")
            time.sleep(poll_interval)

def release_lock(lock_path):
    """Release the lock by removing the lock file."""
    try:
        os.remove(lock_path)
        logger.debug(f"Lock released: {lock_path}")
    except FileNotFoundError:
        logger.error(f"Lock already released: {lock_path}")

def modify_json_locked(json_path, modify_fn):
    locked_json = LockedJSON(json_path)
    try:
        locked_json.acquire_lock()
        if not os.path.exists(json_path):
            save_json_atomic(json_path, {})
        data = locked_json.load()
        modify_fn(data)
        save_json_atomic(json_path, data)
    except Exception as e:
        logger.error(f"[modify_json_locked] Error modifying JSON {json_path}: {e}")
    finally:
        locked_json.release_lock()

class JSONDatabase:
    _files = []

    def __init__(self, folder_base_path: str, make_folder=False, extension="json"):
        self._cache = {}
        self.encoding = "utf-8"
        self.extension = extension
        if os.path.isdir(folder_base_path):
            self._register_jsons(folder_base_path)
        elif self.is_full_valid_file(folder_base_path):
            json_file, _ = os.path.splitext(os.path.basename(folder_base_path))
            folder_base_path = os.path.dirname(folder_base_path)
            self._register_jsons(folder_base_path)
            if len(self._files) > 1:
                index = self._files.index(json_file)
                if index > 0:
                    self._files.pop(index)
                    self._files.insert(0, json_file)

        self.folder_base_path = folder_base_path

        if make_folder:
            os.makedirs(self.folder_base_path, exist_ok=True)

    @classmethod
    def from_file(cls, file_path):
        db = cls(file_path)
        if db._files:
            return JSONFileProxy(db, db._files[0])
        raise FileNotFoundError("No JSON files found to proxy.")

    def __getitem__(self, index):
        try:
            filename = self._files[index].split(".")[0]
            self.file = filename
        except IndexError:
            raise IndexError("Invalid index for JSONDatabase")
        return JSONFileProxy(self, filename)

    def _get_path(self, name):
        return os.path.join(self.folder_base_path, f"{name}.json")

    def is_full_valid_file(self, path):
        return os.path.isabs(path) and os.path.isfile(path)

    def _register_jsons(self, folder_base_path):
        _items = os.listdir(folder_base_path)
        json_list = [i.split(".")[0] for i in _items if os.path.splitext(i)[-1] == f".{self.extension}"]
        if not json_list:
            logger.debug(f"no json files in : {folder_base_path}")
        else:
            self._files = json_list
            _files_print = ', '.join(json_list)
            logger.debug(f"JSONDatabase has {len(json_list)} {self.extension} registered: {_files_print}")

    def exists(self, name):
        return os.path.exists(self._get_path(name))

    def load(self, name, cache=False):
        if cache and name in self._cache:
            return self._cache[name]

        path = self._get_path(name)
        if not os.path.exists(path):
            return {}

        with open(path, "r", encoding=self.encoding) as f:
            data = json.load(f)
            if cache:
                self._cache[name] = data
            return data

    def save(self, name, data):
        path = self._get_path(name)
        locked_json = LockedJSON(path)
        try:
            locked_json.acquire_lock()
            # Use atomic save inside lock
            folder = os.path.dirname(path)
            os.makedirs(folder, exist_ok=True)
            temp_path = path + ".tmp"
            with open(temp_path, "w", encoding=self.encoding) as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
            self._cache[name] = data  # Update cache
        except Exception as e:
            logger.error(f"[JSONDatabase.save] Failed to save {path}: {e}")
            return False
        finally:
            locked_json.release_lock()
        return True

    def update_entry(self, name, key, value):
        def _update(data):
            data[key] = value
        path = self._get_path(name)
        modify_json_locked(path, _update)
        self._cache.pop(name, None)  # Clear cache after update

    def get_entry(self, name, key, default=None, cache=True):
        return self.load(name, cache=cache).get(key, default)

    def clear_cache(self):
        self._cache.clear()

    def _load_index_file(self):
        index_path = self._get_path("__index__")
        if os.path.exists(index_path):
            return load_json(index_path).get("order", [])
        return []

    def _save_index_file(self):
        index_path = self._get_path("__index__")
        save_json(index_path, {"order": self._files})

    def set_encoding(self, encoding: str):
        self.encoding = encoding

    def get_encoding(self):
        return self.encoding


# Proxy class to interact with a specific file
class JSONFileProxy:
    def __init__(self, db: JSONDatabase, filename: str):
        self.db = db
        self.filename = filename
        self._cache = None

    def exists(self):
        return self.db.exists(self.filename)

    def fullpath(self):
        return self.db._get_path(self.filename)

    def load(self, cache=False):
        if cache and self._cache is not None:
            return self._cache

        data = self.db.load(self.filename, cache=cache)
        if cache:
            self._cache = data
        return data

    def reload(self):
        self._cache = None
        return self.load(cache=True)

    def save(self, data):
        path = self.fullpath()
        locked_json = LockedJSON(path)
        try:
            locked_json.acquire_lock()
            folder = os.path.dirname(path)
            os.makedirs(folder, exist_ok=True)
            temp_path = path + ".tmp"
            with open(temp_path, "w", encoding=self.db.encoding) as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
            self._cache = data
        except Exception as e:
            logger.error(f"[JSONFileProxy.save] Failed to save {path}: {e}")
            return False
        finally:
            locked_json.release_lock()
        return True

    def update_entry(self, key, value):
        def _update(data):
            data[key] = value
        path = self.fullpath()
        modify_json_locked(path, _update)
        self._cache = None  # Clear cache after update

    def get_entry(self, key, default=None):
        return self.load(cache=True).get(key, default)

    def clear_cache(self):
        self._cache = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        logger.debug(f"{self.filename} JSON access complete.")
        self.clear_cache()

class LockedJSON:
    def __init__(self, json_path, lock_timeout=30, poll_interval=0.1):
        self.json_path = json_path
        self.lock_path = json_path + ".lock"
        self.lock_timeout = lock_timeout
        self.poll_interval = poll_interval
        self.lock_acquired = False

    def acquire_lock(self):
        start_time = time.time()
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                self.lock_acquired = True
                logger.debug(f"Lock acquired: {self.lock_path}")
                break
            except FileExistsError:
                if (time.time() - start_time) > self.lock_timeout:
                    raise TimeoutError(f"Timeout waiting for lock: {self.lock_path}")
                logger.debug(f"Waiting for lock: {self.lock_path}")
                time.sleep(self.poll_interval)

    def release_lock(self):
        if self.lock_acquired:
            try:
                os.remove(self.lock_path)
                logger.debug(f"Lock released: {self.lock_path}")
                self.lock_acquired = False
            except Exception as e:
                logger.warning(f"Failed to release lock: {e}")

    def __enter__(self):
        self.acquire_lock()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.release_lock()

    def load(self):
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.debug(f"Loaded JSON from {self.json_path}")
            return data
        except FileNotFoundError:
            logger.debug(f"JSON file not found, returning empty dict: {self.json_path}")
            return {}
        except Exception as e:
            logger.error(f"Failed to load JSON from {self.json_path}: {e}")
            raise

    def save(self, data):
        return save_json_atomic(self.json_path, data)

    def modify(self, modify_fn):
        with self:
            data = self.load()
            modify_fn(data)
            self.save(data)