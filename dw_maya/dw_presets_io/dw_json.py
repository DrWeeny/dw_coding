"""Compatibility shim over the canonical `json_utils` package.

The single source of truth for JSON I/O is the top-level, cross-DCC `json_utils`
package: a pure-Python `json_utils.core` (no Maya import - usable from any DCC or
a plain shell) plus a thin `json_utils.maya` bridge for Maya-idle (`executeDeferred`)
writes. This module used to carry its own duplicated copy of that logic; it now
just delegates, preserving the historical `dw_maya.dw_presets_io` surface
(`save_json` / `load_json` / `merge_json` / `update_json`, including the `defer`
flag) so existing callers keep working unchanged.

Prefer importing `json_utils` directly in new code. The Maya bridge is imported
lazily (only when ``defer=True``) so importing this module never pulls in Maya.

Note:
    ``load_json`` returns ``{}`` (not ``None``) on a missing/bad file - it is the
    ``json_utils.core`` behaviour. Callers here guard with ``if not data``, which
    is unaffected.
"""

from typing import Any, Dict

import json_utils.core as _jcore

# Identical-behaviour re-exports.
load_json = _jcore.load_json
save_json_atomic = _jcore.save_json_atomic
merge_nested_dict = _jcore.merge_nested_dict


def save_json(file_path: str, data: Dict[str, Any], indent: int = 4, defer: bool = False) -> bool:
    """Save ``data`` to ``file_path``. When ``defer`` is True, write on Maya idle.

    Args:
        file_path: Destination path (parent dirs are created).
        data: JSON-serializable dict.
        indent: JSON indentation.
        defer: Write via Maya's ``executeDeferred`` (Maya only) instead of now.

    Returns:
        bool: True on success (always True when deferred, since the write runs later).
    """
    if defer:
        import json_utils.maya as _jmaya
        _jmaya.save_json_deferred(file_path, data, indent)
        return True
    return _jcore.save_json(file_path, data, indent)


def merge_json(file_path: str, new_data: dict, indent: int = 4, defer: bool = False) -> bool:
    """Recursively merge ``new_data`` into an existing JSON file (optionally deferred)."""
    if defer:
        import json_utils.maya as _jmaya
        return _jmaya.merge_json(file_path, new_data, indent, defer=True)
    return _jcore.merge_json(file_path, new_data, indent)


def update_json(key: str, value: Any, path: str) -> bool:
    """Add or update a single top-level key in a JSON file (creating it if needed)."""
    data = _jcore.load_json(path) or {}
    data[key] = value
    return _jcore.save_json(path, data)


def save_json_safely(file_path: str, data: dict, indent: int = 4) -> bool:
    """Atomic write, kept for API compatibility (delegates to ``save_json_atomic``)."""
    return _jcore.save_json_atomic(file_path, data, indent)