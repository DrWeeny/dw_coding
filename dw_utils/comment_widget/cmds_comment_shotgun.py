import json
import os
import os.path
from PySide6 import QtGui
import getpass
import re
from datetime import datetime
import random

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

try:
    from dw_utils.threading_utils import thread_safe_lru_cache
except ImportError:
    # Fallback: plain lru_cache when threading_utils is not available
    from functools import lru_cache, wraps
    def thread_safe_lru_cache(maxsize=128):
        def decorator(fn):
            return lru_cache(maxsize=maxsize)(fn)
        return decorator

from .wgt_text_edit_comment import KeywordRegistry

# ---------------------------------------------------------------------------
# Configuration – override these before first use to adapt to your pipeline.
# ---------------------------------------------------------------------------

class CommentWidgetConfig:
    """
    Central configuration object.  Modify attributes **before** creating any
    USER / CurrentUser instances or calling cache functions.

    Example::

        from dw_utils.comment_widget.cmds_comment_shotgun import CommentWidgetConfig
        CommentWidgetConfig.PROXY = {"http": "http://myproxy:8080",
                                     "https": "http://myproxy:8080"}
        CommentWidgetConfig.USER_BACKEND = "json"   # no ShotGrid at all
    """

    # Network proxy used by ``cache_image_from_url``.
    # Set to ``None`` (default) for direct connections, or provide a dict
    # like ``{"http": "http://host:port", "https": "http://host:port"}``.
    PROXY: dict | None = None

    # Where local JSON databases and user thumbnails are stored.
    METADATA_PATH: str = os.environ.get(
        "DW_COMMENT_METADATA_PATH",
        os.path.join(os.path.dirname(os.path.dirname(__file__)),
                     ".local_data", "takes_comments"),
    )

    # ``"shotgrid"`` – register unknown users via ShotGrid (requires *sgops*).
    # ``"json"``     – never call ShotGrid; users are created from local data.
    USER_BACKEND: str = "json"

    # Optional callable ``(os_user_name) -> dict`` that returns user info when
    # ``USER_BACKEND`` is set to a custom value.  The returned dict should
    # contain at least: name, email, thumbnail_cache_path, role, id.
    CUSTOM_USER_RESOLVER = None  # type: callable | None


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

dir_path = os.path.dirname(__file__)
JSON_COMMENT = os.path.join(dir_path, "take_comment.json")

# Resolve the pic_files folder via dw_ressources (preferred), otherwise
# fall back to a sibling ``icon/`` directory next to dw_utils/.
try:
    from dw_ressources import get_resource_path as _get_resource_path
    _pic_path = str(_get_resource_path("pic_files"))
except Exception:
    _pic_path = None

if _pic_path and os.path.isdir(_pic_path):
    ICON_FOLDER = _pic_path
else:
    _legacy = os.path.join(os.path.dirname(dir_path), "icon")
    ICON_FOLDER = _legacy if os.path.isdir(_legacy) else None

# Sub-folder containing random fictional user avatars
RANDOM_USER_FOLDER = (
    os.path.join(ICON_FOLDER, "random_user")
    if ICON_FOLDER else None
)


def random_user_icon():
    """Return a random avatar path from ``ressources/pic_files/random_user/``."""
    if not RANDOM_USER_FOLDER or not os.path.isdir(RANDOM_USER_FOLDER):
        return None
    files = [
        os.path.join(RANDOM_USER_FOLDER, f)
        for f in os.listdir(RANDOM_USER_FOLDER)
        if os.path.isfile(os.path.join(RANDOM_USER_FOLDER, f))
        and f.lower().endswith((".jpg", ".jpeg", ".png"))
    ]
    if not files:
        return None
    return random.choice(files)

def create_empty_conv_dic():
    return {"take":"", "comments":[]}

def get_user_database_folder_name():
    return "database"

def get_user_metadata_path():
    """
    Returns: path where we cache ui data, in case we want to relocate the path.
             Created on first access if it does not exist.
    """
    path = os.path.join(CommentWidgetConfig.METADATA_PATH, get_user_database_folder_name())
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
    return path

def get_user_thumbnail_folder_name():
    return "user_pic"

def get_user_thumbnail_folder_path():
    path = os.path.join(CommentWidgetConfig.METADATA_PATH, get_user_thumbnail_folder_name())
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
    return path

def get_conversation_from_path(folder_path: str):
    db = JSONDatabase(folder_path)[3]
    if db.exists():
        data = db.load()
    else:
        data = {}

    # Ensure all entries are dictionaries (we now have a dictionary of takes)
    if not isinstance(data, dict):
        print("Warning: Data is not in expected dictionary format:", data)
        return {}

    _dir_list = [f for f in os.listdir(folder_path) if os.path.isdir(os.path.join(folder_path, f))]
    take_list = sorted(_dir_list, reverse=True)

    # Ensure every take has an entry in the data
    for tk in take_list:
        _key = f"Take_{tk}"
        if _key not in data:
            data[_key] = {"comments": []}  # Create an empty comments list for the new take

    return data

def save_thumbnail_qt(image_data: bytes, save_path: str, size=(100, 100)):
    pixmap = QtGui.QPixmap()
    pixmap.loadFromData(image_data)
    thumbnail = pixmap.scaled(*size)
    thumbnail.save(save_path, "JPEG")

def cache_image_from_url(url:str, destination:str, do_resize:bool=False, size:int=100):
    if not _HAS_REQUESTS:
        print("requests library is not installed — cannot download image from URL")
        return

    kwargs = {}
    if CommentWidgetConfig.PROXY:
        kwargs["proxies"] = CommentWidgetConfig.PROXY

    response = requests.get(url, **kwargs)

    if response.status_code == 200:
        if not do_resize:
            with open(destination, "wb") as f:
                f.write(response.content)
            print("cached image saved to {}".format(destination))
        else:
            save_thumbnail_qt(response.content, destination, (size, size))
    else:
        print("error code {} when connecting to url : \n{}".format(response.status_code, url))

def cache_user_from_sg_to_json(name:str=None, sg_connection=None, do_resize:bool=False):
    """
    Cache user info from ShotGrid to the local JSON database.

    Requires ``CommentWidgetConfig.USER_BACKEND == "shotgrid"`` **and**
    the ``sgops`` package to be importable.

    Args:
        name: os_login style np-(c-)name
        sg_connection: if there was a connection already established, lets use this one instead
        do_resize: whether to resize the thumbnail

    Returns:
        dict with user info or empty dict when ShotGrid is unavailable.
    """
    try:
        import sgops
    except ImportError:
        print("sgops is not installed — ShotGrid user caching is disabled")
        return {}

    if not name:
        name = CurrentUser().os_user_name

    if not sg_connection:
        sg_connection = sgops.Connection()
        print("Connected to shotgrid")

    # get user infos ["email", "id", "login", "name", "type"]
    user_sg_info = sg_connection.get_user(name)

    # we need a bit more infos to display such as job-role and thumbnail
    user_info = sg_connection.find_one("HumanUser", [["id", "is", user_sg_info["id"]]], ["permission_rule_set", "image"])
    user_sg_info["thumbnail_url"]= user_info["image"]
    user_sg_info["user_role"] = user_info["permission_rule_set"]["name"]

    thumbnail_destination = os.path.join(get_user_thumbnail_folder_path(), f"{name}.jpeg")
    cache_image_from_url(user_info["image"], thumbnail_destination, do_resize=do_resize)
    user_sg_info["thumbnail_cache_path"] = thumbnail_destination

    # store the user_sg_info with the new entries in my database of cache
    db = JSONDatabase()
    # index 0 is the user data json file
    db[0].update_entry(name, user_sg_info)

    return user_sg_info

def get_user() -> str:
    """
    Get the current system user.
    Returns:
        str: The username of the current user.
    """
    return getpass.getuser()

def is_user_in_db(userlogin:str=None)->bool:
    if not userlogin:
        userlogin = CurrentUser().os_user_name


    db_users = JSONDatabase()[0]
    user_cached = db_users.get_entry(userlogin)
    if user_cached:
        return user_cached["name"]
    else:
        return None

def get_user_info_from_db(userlogin=None, key_list=("name", "email", "thumbnail_cache_path", "user_role"))->list:
    """
    deprecated, shoud use User("login_name")
    """
    result = []
    if not userlogin:
        userlogin = CurrentUser().os_user_name

    db_users = JSONDatabase()[0]
    user_cached = db_users.load()
    if user_cached.get(userlogin, None):
        for key in key_list:
            value = user_cached[userlogin].get(key, None)
            result.append(value)

        return result

def extract_number_from_take_name(take_name: str):
    # Extracts the numeric part of the take name (e.g., 'Take_t001' -> 1, 'Take_v002' -> 2)
    match = re.search(r'Take_[tv](\d+)', take_name)
    if match:
        return int(match.group(1))  # Return the numeric part as integer
    return 0  # If no match, treat it as 0 (or handle this case as you need)

def new_comment_data_to_db(comment_data: dict):
    # Convert timestamp to string (ISO format)
    serializable_comment = dict(comment_data)

    if isinstance(serializable_comment["timestamp"], datetime):
        serializable_comment["timestamp"] = serializable_comment["timestamp"].isoformat()

    # Remove the QPixmap (non-serializable) from the data
    if "user_image_pixmap" in serializable_comment:
        serializable_comment.pop("user_image_pixmap")

    return serializable_comment

def save_new_comment(folder_path: str, comment_data: dict)->dict:
    # Access the take_comment.json file
    db = JSONDatabase(folder_path)[3]  # Access the take_comment.json
    if db.exists():
        data = db.load()  # Load existing data (indexed by take_name)
    else:
        data = {}

    take_name = comment_data["take"]  # Extract the take name from comment_data

    # Convert datetime to a serializable format and remove the unwanted key
    new_comment = new_comment_data_to_db(comment_data)

    # Check if the 'take' already exists in the data (using dict lookup)
    if take_name in data:
        data[take_name]["comments"].append(new_comment)  # Append to the comments list
    else:
        data[take_name] = {"comments": [new_comment]}  # Create a new entry for the take

    # Save the updated data back to the file
    db.save(data)
    return data

def delete_old_comment(folder_path: str, comment_data: dict) -> dict:
    """
    Deletes a comment from the JSON database.

    Args:
        folder_path (str): Path to the folder containing the JSON file.
        comment_data (dict): The comment data to delete.

    Returns:
        dict: Updated data after deletion.
    """
    # Validate the input data
    if not comment_data or "take" not in comment_data:
        print("Error: 'take' key is missing in comment_data:", comment_data)
        return {}

    db = JSONDatabase(folder_path)[3]  # Access the take_comment.json
    if not db.exists():
        return {}

    data = db.load()
    take_name = comment_data["take"]

    # Check if the take exists in the data
    if take_name in data:
        comments = data[take_name].get("comments", [])
        # Remove the comment matching the timestamp and text
        for x, c in enumerate(comments):
            json_text = c.get("text", "")
            json_text_html = c.get("text_html", "")
            json_user = c.get("user_name", {})
            json_timestamp = c.get("timestamp", None)
            if (json_text == comment_data["comment"] or json_text_html == comment_data["comment"]) and json_user == comment_data["user"] and json_timestamp == comment_data["timestamp"].isoformat():
                comments.pop(x)

                # If no comments remain for the take, remove the take entry
                if not data[take_name]["comments"]:
                    del data[take_name]

                db.save(data)
                return data
    return data

def remove_mentions_on_comment(folder_path: str, comment_data: dict):
    """
    Removes mentions associated with a deleted comment.

    Args:
        folder_path (str): Path to the folder containing the mentions JSON file.
        comment_data (dict): The comment data to remove mentions for.
    """
    db = JSONDatabase(folder_path)[1]  # Access the dw_mentions.json
    if not db.exists():
        return

    data = db.load()
    mentions_to_remove = extract_mentions(comment_data["text"])

    for mentioned_user in mentions_to_remove:
        if mentioned_user in data["mentions"]:
            data["mentions"][mentioned_user] = [
                m for m in data["mentions"][mentioned_user]
                if not (m["timestamp"] == comment_data["timestamp"].isoformat() and m["text"] == comment_data["text"])
            ]
            # Remove the user entry if no mentions remain
            if not data["mentions"][mentioned_user]:
                del data["mentions"][mentioned_user]

    db.save(data)

def update_subscriptions_on_comment(folder_path:str,
                                    scope_key:str,
                                    user_name:str,
                                    timestamp:datetime)->bool:
    db = JSONDatabase(folder_path)[2]  # Index 2 = dw_subscriptions.json
    if db.exists():
        data = db.load()
    else:
        data = {"users": {}, "scopes": {}}

    users = data.setdefault("users", {})
    scopes = data.setdefault("scopes", {})

    # Ensure scope exists
    scope = scopes.setdefault(scope_key, {
        "subscribers": [],
        "last_comment_timestamp": "",
        "last_comment_user": "",
        "comment_file": os.path.join(folder_path, "take_comment.json")
    })

    # Add the user to the subscriber list if not already
    if user_name not in scope["subscribers"]:
        scope["subscribers"].append(user_name)

    # Update scope-wide metadata
    scope["last_comment_timestamp"] = timestamp.isoformat()
    scope["last_comment_user"] = user_name

    # Ensure the user entry exists
    user_entry = users.setdefault(user_name, {"subscriptions": {}})
    sub = user_entry["subscriptions"].setdefault(scope_key, {
        "last_read": timestamp.isoformat(),
        "last_written": timestamp.isoformat()
    })

    # Update the user's last_written timestamp
    sub["last_written"] = timestamp.isoformat()

    db.save(data)

    return True

def get_unread_count(user_name):
    db = JSONDatabase()[2]
    if not db.exists():
        return 0

    data = db.load()
    users = data.get("users", {})
    scopes = data.get("scopes", {})

    user_subs = users.get(user_name, {}).get("subscriptions", {})
    unread_count = 0

    for scope_key, meta in scopes.items():
        last_post = meta.get("last_comment_timestamp")
        last_user = meta.get("last_comment_user")

        if scope_key not in user_subs:
            continue

        user_data = user_subs[scope_key]
        last_read = user_data.get("last_read", "1970-01-01T00:00:00")

        if last_post and last_post > last_read and last_user != user_name:
            unread_count += 1

    return unread_count

def mark_conversation_as_read(user_name, scope_key, read_time:datetime=None):
    """
    Update the last_read timestamp for a user's subscription to a conversation.
    ``user_name`` may be a string or a USER instance.
    """
    db = JSONDatabase()[2]  # Index 2 = dw_subscriptions.json

    if db.exists():
        data = db.load()
    else:
        return  # No subscription data to update

    # Accept both a USER instance and a plain string
    if isinstance(user_name, USER):
        _name = user_name.os_user_name
    else:
        _name = str(user_name)

    users = data.setdefault("users", {})
    user_entry = users.setdefault(_name, {"subscriptions": {}})
    subscriptions = user_entry.setdefault("subscriptions", {})

    if scope_key not in subscriptions:
        # User is not subscribed to this scope; optionally auto-subscribe
        subscriptions[scope_key] = {
            "last_read": datetime.now().isoformat(),
            "last_written": ""
        }

    # Update the read time
    timestamp = read_time or datetime.now()
    subscriptions[scope_key]["last_read"] = timestamp.isoformat()

    db.save(data)

def extract_mentions(text: str) -> list[str]:
    """
    Extracts @mentions from the text.
    """
    return list(set(re.findall(r'@([^\s@]*)', text)))

def highlight_mentions(text_html, roles=None, names=None)->str:
    if not roles:
        roles = KeywordRegistry().get_roles()
    if not names:
        names = KeywordRegistry().get_names()

    for role in roles:
        pattern = re.compile(rf"@{re.escape(role)}\b", re.IGNORECASE)
        text_html = pattern.sub(f'<span style="color:#FFD700; font-weight:bold">@{role}</span>', text_html)

    for name in names:
        pattern = re.compile(rf"@{re.escape(name)}\b", re.IGNORECASE)
        text_html = pattern.sub(f'<span style="color:#00FFFF; font-style:italic">@{name}</span>', text_html)

    return text_html


def extract_mentions_from_html(text_html:str)->list[str]:
    # This regex captures content like @Name or @Name Surname inside HTML tags
    mentions = re.findall(r'">@([a-zA-ZÀ-ÿ\'\-]+(?: [a-zA-ZÀ-ÿ\'\-]+)?)<', text_html, re.DOTALL)
    return mentions


def update_mentions_on_comment(folder_path: str,
                               scope_key: str,
                               timestamp: datetime,
                               text: str,
                               text_html:str=None,
                               mentions: list = None) -> bool:
    """
    Updates the mention database when someone is mentioned in a comment.
    """

    db = JSONDatabase()[1]  # Index 1 = dw_mentions.json
    if db.exists():
        data = db.load()
    else:
        data = {"mentions": {}}

    if text_html and not mentions:
        mentions = extract_mentions_from_html(text_html)

    # Use the singleton for the current user
    user = CurrentUser()

    for mentioned_user in mentions:
        user_mentions = data["mentions"].setdefault(mentioned_user, [])
        user_mentions.append({
            "scope_key": scope_key,
            "timestamp": timestamp.isoformat(),
            "from": user.name,
            "from_user_image": user.avatar_path,
            "from_user_role": user.role,
            "from_user_id": user.id,
            "text": text,
            "comment_file": os.path.join(folder_path, "take_comment.json")
        })
        if text_html:
            user_mentions.append({"text_html": text_html})

    db.save(data)
    return True

class JSONDatabase:
    """
    allow me to edit json within the folder database
    it support to have an index like so : db = JSONDatabase()[0]
    """
    _files = ["dw_users.json", "dw_mentions.json", "dw_subscriptions.json", "take_comment.json"]

    def __init__(self, base_path=get_user_metadata_path(), make_folder=False):
        self.base_path = base_path
        if make_folder:
            os.makedirs(self.base_path, exist_ok=True)

    def __getitem__(self, index):
        try:
            filename = self._files[index].split(".")[0]
            self.file = filename
        except IndexError:
            raise IndexError("Invalid index for JSONDatabase")
        return JSONFileProxy(self, filename)

    def _get_path(self, name):
        return os.path.join(self.base_path, f"{name}.json")

    def exists(self, name):
        return os.path.exists(self._get_path(name))

    def load(self, name):
        path = self._get_path(name)
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, name, data):
        path = self._get_path(name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def update_entry(self, name, key, value):
        data = self.load(name)
        data[key] = value
        self.save(name, data)

    def get_entry(self, name, key, default=None):
        data = self.load(name)
        return data.get(key, default)

# Proxy class to interact with a specific file
class JSONFileProxy():
    def __init__(self, db: JSONDatabase, filename: str):
        self.db = db
        self.filename = filename

    def exists(self):
        return self.db.exists(self.filename)

    def fullpath(self):
        return self.db._get_path(self.filename)

    def load(self):
        if self.exists():
            return self.db.load(self.filename)

    def save(self, data):
        self.db.save(self.filename, data)

    def update_entry(self, key, value):
        data = self.load()
        data[key] = value
        self.save(data)

    def get_entry(self, key, default=None):
        data = self.load()
        if data is None:
            return default
        return data.get(key, default)

class USER:
    def __init__(self, os_user_name=None):
        self.os_user_name = os_user_name or get_user()
        self._avatar_pixmap_cache = {}  # in __init__

        # Try to get from DB cache
        try:
            if self._is_in_db():
                self._load_from_db()
            else:
                self._register_and_cache()
        except Exception as e:
            print(e)
            print(f"Warning: could not fully resolve user info for {self.os_user_name}")
            self._set_local_fallback()

    def _is_in_db(self):
        db = JSONDatabase()[0]  # dw_users.json
        return db.get_entry(self.os_user_name) is not None

    def unread_count(self):
        db = JSONDatabase()[2]  # dw_subscriptions.json
        if not db.exists():
            return 0

        data = db.load()
        user_subs = data.get("users", {}).get(self.name, {}).get("subscriptions", {})
        scopes = data.get("scopes", {})

        return sum(
            1
            for key, scope in scopes.items()
            if scope.get("last_comment_timestamp", "1970-01-01T00:00:00") >
            user_subs.get(key, {}).get("last_read", "1970-01-01T00:00:00") and
            scope.get("last_comment_user") != self.name
        )

    def mark_scope_as_read(self, scope_key: str, read_time=None):
        mark_conversation_as_read(user_name=self.name,
                                  scope_key=scope_key,
                                  read_time=read_time)

    def subscribe_to_scope(self, scope_key: str, folder_path: str, timestamp: datetime):
        update_subscriptions_on_comment(folder_path, scope_key, self.name, timestamp)

    def _load_from_db(self):
        db = JSONDatabase()[0]  # dw_users.json
        user_info = db.get_entry(self.os_user_name)
        self.name = user_info.get("name", self.os_user_name)
        self.email = user_info.get("email", "")
        self.avatar_path = user_info.get("thumbnail_cache_path", "placeholder.png")
        self.role = user_info.get("role", "unknown")
        self.id = user_info.get("id", -1)

    def _register_and_cache(self):
        backend = CommentWidgetConfig.USER_BACKEND

        if backend == "shotgrid":
            info = cache_user_from_sg_to_json(self.os_user_name, do_resize=True)
            if not info:
                self._set_local_fallback()
                return
            print(f"Registering {self.os_user_name} via ShotGrid")
            self.name = info.get("name", self.os_user_name)
            self.email = info.get("email", "")
            self.avatar_path = info.get("thumbnail_cache_path", "placeholder.png")
            self.role = info.get("user_role", "unknown")
            self.id = info.get("user_id", -1)

        elif CommentWidgetConfig.CUSTOM_USER_RESOLVER is not None:
            info = CommentWidgetConfig.CUSTOM_USER_RESOLVER(self.os_user_name)
            self.name = info.get("name", self.os_user_name)
            self.email = info.get("email", "")
            self.avatar_path = info.get("thumbnail_cache_path", "placeholder.png")
            self.role = info.get("role", "unknown")
            self.id = info.get("id", -1)

        else:
            # Pure local / standalone mode – no external service
            self._set_local_fallback()

    def _set_local_fallback(self):
        """Populate with local-only defaults (no external service)."""
        self.name = self.os_user_name
        self.email = ""
        self.avatar_path = random_user_icon() or "placeholder.png"
        self.role = "user"
        self.id = -1

    def to_dict(self):
        return {
            "name": self.name,
            "email": self.email,
            "avatar_path": self.avatar_path,
            "role": self.role,
            "id": self.id,
            "os_name": self.os_user_name
        }

    def is_supervisor(self):
        return self.role.lower() in {"supervisor", "lead"}

    @thread_safe_lru_cache(maxsize=8)
    def avatar_pixmap(self, size=(50, 50)):
        from PySide6 import QtGui, QtCore
        pixmap = QtGui.QPixmap(self.avatar_path)
        if pixmap.isNull():
            fallback = random_user_icon()
            if fallback:
                pixmap = QtGui.QPixmap(fallback)
        if pixmap.isNull():
            # Last resort: solid grey square
            pixmap = QtGui.QPixmap(*size)
            pixmap.fill(QtGui.QColor("grey"))
        return pixmap.scaled(*size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)


class CurrentUser(USER):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # set here to be safe
        return cls._instance

    def __init__(self, *args, **kwargs):
        if self._initialized:
            return  # Skip reinitialization
        super().__init__(*args, **kwargs)
        self._initialized = True

    def get_nice_name_from_current_win_session(self):
        import ctypes

        GetUserNameEx = ctypes.windll.secur32.GetUserNameExW
        NameDisplay = 3

        size = ctypes.pointer(ctypes.c_ulong(0))
        GetUserNameEx(NameDisplay, None, size)

        nameBuffer = ctypes.create_unicode_buffer(size.contents.value)
        GetUserNameEx(NameDisplay, nameBuffer, size)
        win_name = nameBuffer.value

        match = re.search(r'/\s*([A-Za-z .-]+)\s*\[', win_name)

        if match:
            romanized_name = match.group(1).strip().replace(" ", "_").lower()
            return romanized_name
        else:
            return None


