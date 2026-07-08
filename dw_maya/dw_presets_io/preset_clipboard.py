"""Cross-session preset clipboard.

Summary:
    Save presets from one Maya session into a stable machine-local directory
    and list / load them from another session. ``tempfile.mkdtemp()`` returns
    a randomly named directory per call (a second Maya cannot know it) and
    ``tempfile.TemporaryDirectory()`` deletes itself when its ``with`` block
    exits - so the clipboard uses a fixed folder under the system temp root
    (``tempfile.gettempdir()``) instead. Every process on the machine resolves
    the same path; set the ``DW_PRESET_CLIPBOARD`` env var (e.g. a network
    share) in both sessions to pass presets between machines. Being under the
    temp root, the OS may clean it eventually - this is a clipboard, not an
    archive: use ``save_preset_file`` with a real path for keepers.

Features:
    - One json per named entry (``<name>.json``, dw_preset envelope).
    - ``list_clipboard`` is newest-first; ``clipboard_info`` peeks at an
      entry (node identities / types, namespace summary) without loading it
      into the scene.

Functions:
    clipboard_dir, save_to_clipboard, list_clipboard, clipboard_info,
    load_from_clipboard, clear_clipboard

Example:
    # Maya session A
    import dw_maya.dw_presets_io.preset_clipboard as clip
    clip.save_to_clipboard(cmds.ls(selection=True), "walk_colliders")

    # Maya session B (same machine)
    clip.list_clipboard()                      # ['walk_colliders', ...]
    clip.clipboard_info("walk_colliders")      # peek before loading
    clip.load_from_clipboard("walk_colliders", target_ns="_DYN_")

Author:
    DrWeeny
"""

import os
import time
import tempfile
from typing import Any, Dict, List, Optional

import dw_maya.dw_presets_io.dw_json as dw_json
import dw_maya.dw_presets_io.preset_components as pcomp
from dw_logger import get_logger

logger = get_logger()

#: Env var overriding the clipboard location (e.g. a shared network path).
CLIPBOARD_ENV = "DW_PRESET_CLIPBOARD"


def clipboard_dir() -> str:
    """Return (and create) the clipboard directory.

    Default is ``<system temp>/dw_preset_clipboard`` - stable across
    processes, so any Maya on this machine resolves the same folder.
    """
    path = os.environ.get(CLIPBOARD_ENV)
    if not path:
        path = os.path.join(tempfile.gettempdir(), "dw_preset_clipboard")
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def _entry_path(name: str) -> str:
    return os.path.join(clipboard_dir(), f"{name}.json")


def save_to_clipboard(nodes: List[Any],
                      name: str,
                      only: Optional[list] = None,
                      skip: Optional[list] = None) -> Optional[str]:
    """Capture ``nodes`` into the clipboard under ``name`` (overwrites).

    Args:
        nodes: Node names, MayaNode instances and/or captured dicts -
            forwarded to :func:`preset_components.save_preset_file`.
        name: Entry name (becomes ``<name>.json``).
        only / skip: Component-key filters.

    Returns:
        The written path, or None when nothing was captured.
    """
    return pcomp.save_preset_file(nodes, _entry_path(name),
                                  only=only, skip=skip)


def list_clipboard() -> List[str]:
    """Return the entry names currently on the clipboard, newest first."""
    folder = clipboard_dir()
    files = [f for f in os.listdir(folder) if f.endswith(".json")]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(folder, f)),
               reverse=True)
    return [os.path.splitext(f)[0] for f in files]


def clipboard_info(name: str) -> Dict[str, Any]:
    """Peek at a clipboard entry without touching the scene.

    Returns ``{"name", "path", "saved" (readable mtime), "nodes"
    ({identity: nodeType}), "namespaces"}``, or an empty dict when the entry
    is missing / not a dw_preset file.
    """
    path = _entry_path(name)
    if not os.path.isfile(path):
        logger.warning(f"clipboard_info: no entry named '{name}'")
        return {}
    data = dw_json.load_json(path)
    if not data or data.get("format") != pcomp.PRESET_FORMAT:
        logger.warning(f"clipboard_info: '{path}' is not a "
                       f"{pcomp.PRESET_FORMAT} file")
        return {}
    return {
        "name": name,
        "path": path,
        "saved": time.strftime("%Y-%m-%d %H:%M:%S",
                               time.localtime(os.path.getmtime(path))),
        "nodes": {identity: body.get("nodeType")
                  for identity, body in data.get("nodes", {}).items()},
        "namespaces": data.get("namespaces", {}),
    }


def load_from_clipboard(name: str,
                        target_ns: str = ":",
                        create: bool = True,
                        remap: Optional[Dict[str, str]] = None,
                        apply_external: bool = True,
                        ext_ns_map: Optional[Dict[str, str]] = None) -> List[Any]:
    """Rebuild a clipboard entry in the current scene.

    Same knobs as :func:`preset_components.load_preset_file` (which this
    forwards to). Returns the wrapped nodes.
    """
    path = _entry_path(name)
    if not os.path.isfile(path):
        logger.warning(f"load_from_clipboard: no entry named '{name}' "
                       f"(have: {list_clipboard()})")
        return []
    return pcomp.load_preset_file(path,
                                  target_ns=target_ns,
                                  create=create,
                                  remap=remap,
                                  apply_external=apply_external,
                                  ext_ns_map=ext_ns_map)


def clear_clipboard(name: Optional[str] = None) -> int:
    """Delete one entry, or every entry when ``name`` is None.

    Returns:
        The number of files removed.
    """
    targets = [name] if name else list_clipboard()
    removed = 0
    for entry in targets:
        path = _entry_path(entry)
        if os.path.isfile(path):
            os.remove(path)
            removed += 1
        elif name:
            logger.warning(f"clear_clipboard: no entry named '{entry}'")
    return removed