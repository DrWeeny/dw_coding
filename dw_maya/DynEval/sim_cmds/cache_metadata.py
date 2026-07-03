"""
sim_cmds/cache_metadata.py — comments and tags for cache versions.

One metadata.json per namespace/solver (path given by item.metadata(), see
BaseSimulationItem.metadata) is shared by every sim item under that solver;
entries are keyed by the item's short_name (the stable cache-naming identity).

Schema
------
{
    "comments":  {"<short_name>": {"<version>": "comment text"}},
    "favorites": {"<short_name>": [<version:int>, ...]},
    "published": {"<short_name>": <version:int>}
}

favorites — versions worth keeping around (composite-cache / blendshape
sources, previous publishes). Multiple allowed per item.
published — the single version tagged for publish. After a scene rebuild,
"Attach Published Caches" (tree context menu) walks the solver's items and
reattaches every tagged version.

Writes are immediate (no defer) so the cache panel can reread the file right
after a save without racing a deferred idle-time write.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from dw_logger import get_logger
from dw_maya.dw_presets_io import dw_json

logger = get_logger()


# ---------------------------------------------------------------------------
# Internal I/O
# ---------------------------------------------------------------------------

def _metadata_path(item) -> Optional[Path]:
    """Resolve the item's metadata.json path, None when unavailable."""
    if not hasattr(item, "metadata"):
        return None
    try:
        return Path(item.metadata())
    except Exception as e:
        logger.warning(f"cache_metadata: no metadata path for {item!r}: {e}")
        return None


def _load(item) -> dict:
    """Load the whole metadata document ({} when missing/unreadable)."""
    path = _metadata_path(item)
    if path is None:
        return {}
    try:
        if not path.exists():
            return {}
        return dw_json.load_json(str(path)) or {}
    except Exception as e:
        logger.warning(f"cache_metadata: load failed for {path}: {e}")
        return {}


def _save(item, data: dict) -> bool:
    """Write the whole metadata document back (immediate, not deferred)."""
    path = _metadata_path(item)
    if path is None:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return dw_json.save_json(str(path), data)
    except Exception as e:
        logger.error(f"cache_metadata: save failed for {path}: {e}")
        return False


def _item_key(item) -> str:
    return getattr(item, "short_name", "") or getattr(item, "node", "")


# ---------------------------------------------------------------------------
# Read API
# ---------------------------------------------------------------------------

def get_tags(item) -> dict:
    """All metadata for one item in a single file read.

    Returns:
        {"comments": {version(str): text},
         "favorites": [version(int), ...],
         "published": version(int) | None}
    """
    data = _load(item)
    key = _item_key(item)
    return {
        "comments": data.get("comments", {}).get(key, {}),
        "favorites": data.get("favorites", {}).get(key, []),
        "published": data.get("published", {}).get(key),
    }


def get_comment(item, version: int) -> str:
    return get_tags(item)["comments"].get(str(version), "")


def get_favorites(item) -> list:
    return list(get_tags(item)["favorites"])


def is_favorite(item, version: int) -> bool:
    return version in get_tags(item)["favorites"]


def get_published(item) -> Optional[int]:
    return get_tags(item)["published"]


# ---------------------------------------------------------------------------
# Write API
# ---------------------------------------------------------------------------

def set_comment(item, version: int, text: str) -> bool:
    data = _load(item)
    key = _item_key(item)
    data.setdefault("comments", {}).setdefault(key, {})[str(version)] = text
    return _save(item, data)


def toggle_favorite(item, version: int) -> bool:
    """Flip the favorite tag on a version. Returns the new state."""
    data = _load(item)
    key = _item_key(item)
    favorites = data.setdefault("favorites", {}).setdefault(key, [])
    if version in favorites:
        favorites.remove(version)
        state = False
    else:
        favorites.append(version)
        favorites.sort()
        state = True
    _save(item, data)
    return state


def set_published(item, version: Optional[int]) -> bool:
    """Tag one version as the publish target (None clears the tag)."""
    data = _load(item)
    key = _item_key(item)
    published = data.setdefault("published", {})
    if version is None:
        published.pop(key, None)
    else:
        published[key] = version
    return _save(item, data)