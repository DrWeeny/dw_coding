"""
clipboard_cmds.py - scene-side commands behind the NodeClipboard UI.

Summary:
    Thin command layer between the Qt widgets and
    ``dw_presets_io.preset_clipboard``. The UI never calls ``maya.cmds`` or
    the preset API directly: it asks here for entries, captures the current
    selection, and pastes an entry back with a per-node component selection.

Features:
    - Capture writes a *complete* entry (every component the wrapped classes
      own, keyframes included even though they are opt-in at capture time),
      so the same entry can be pasted differently twice. Filtering happens on
      paste.
    - Paste runs in one undo chunk and re-selects what it rebuilt.

Functions:
    component_label, all_component_keys, sanitize_name, default_entry_name,
    selected_nodes, is_shape, expand_selection, scene_namespaces,
    list_entries, entry_info,
    clipboard_location, copy_selection, paste_entry, delete_entry,
    clear_entries, cleanup_hours, set_cleanup_hours, cleanup_label,
    run_cleanup

Example:
    import dw_maya.NodeClipboard.clipboard_cmds as clipboard_cmds
    clipboard_cmds.copy_selection("walk_colliders")
    info = clipboard_cmds.entry_info("walk_colliders")
    clipboard_cmds.paste_entry("walk_colliders",
                               include={"nClothShape1": ["attributes"]})

Author:
    DrWeeny
"""

import re
from typing import Dict, List, Optional

import maya.cmds as cmds

import dw_maya.dw_lsNode as dw_lsNode
import dw_maya.dw_decorators as dw_decorators
import dw_maya.dw_presets_io.preset_clipboard as preset_clipboard
from dw_logger import get_logger

logger = get_logger()

#: Readable labels for the component keys a preset body can hold. Unknown
#: keys (a component added later) fall back to the raw key.
COMPONENT_LABELS = {
    "hierarchy": "Hierarchy",
    "attributes": "Attributes",
    "connections": "Connections",
    "keyframes": "Keyframes",
    "geometry": "Geometry",
    "network": "Network rebuild",
}

COMPONENT_TIPS = {
    "hierarchy": "Parent chain - re-parents the node, creating the group when missing.",
    "attributes": "Scalar / string attribute values.",
    "connections": "Incoming plug connections (internal + external).",
    "keyframes": "Anim curves, tangents and infinity.",
    "geometry": "Mesh points, topology and UVs.",
    "network": "Type-specific rebuild (constraints, nConstraints).",
}

_NAME_CLEAN = re.compile(r"[^A-Za-z0-9_.-]+")

#: optionVar holding the cleanup delay in hours (0 = never expire). An
#: optionVar rather than a config file: the delay is a per-artist habit, and
#: Maya already persists it across sessions without a new file to ship.
CLEANUP_OPTION_VAR = "dwNodeClipboardCleanupHours"

#: Default delay - a clipboard entry is a "carry it across right now" thing,
#: so a day is already generous.
DEFAULT_CLEANUP_HOURS = 24

#: Menu choices, ordered: (label, hours). 0 disables the sweep.
CLEANUP_CHOICES = (
    ("Disabled (keep forever)", 0),
    ("1 hour", 1),
    ("6 hours", 6),
    ("24 hours (default)", 24),
    ("3 days", 72),
    ("1 week", 168),
)


def component_label(key: str = "") -> str:
    """Return the readable label for a component key."""
    return COMPONENT_LABELS.get(key, key)


def component_tip(key: str = "") -> str:
    """Return the tooltip for a component key ('' when unknown)."""
    return COMPONENT_TIPS.get(key, "")


def sanitize_name(name: str = "") -> str:
    """Make ``name`` safe as a file stem (the entry becomes <name>.json)."""
    cleaned = _NAME_CLEAN.sub("_", name).strip("_")
    return cleaned or "clipboard"


def selected_nodes() -> List[str]:
    """Return the current selection as-is (long names)."""
    return cmds.ls(selection=True, long=True) or []


def is_shape(node: str = "") -> bool:
    """True when ``node`` is a shape rather than a transform."""
    return bool(cmds.objectType(node, isAType="shape"))


def expand_selection(nodes: Optional[List[str]] = None,
                     include_shapes: bool = False) -> List[str]:
    """Return ``nodes`` (or the selection) plus everything under them.

    Selecting a group is the natural gesture - nobody wants to select every
    collider inside it - so a copy walks the hierarchy itself.

    Shapes are dropped when their transform is already in the list: a preset
    identity is transform-based, so a shape would capture under the same
    identity and simply overwrite its own transform's entry. A shape whose
    transform is *not* in the list (someone picked the shape alone) is kept,
    and intermediate shapes are always dropped.

    Parents come before children: the hierarchy slice re-parents against
    names that must already exist when a child is rebuilt.
    """
    roots = nodes if nodes is not None else selected_nodes()
    roots = cmds.ls(roots, long=True) or []
    if not roots:
        return []
    descendants = cmds.listRelatives(roots, allDescendents=True,
                                     fullPath=True) or []
    # dict.fromkeys keeps the first occurrence and drops repeats
    everything = list(dict.fromkeys(roots + descendants))
    # A shorter dag path is always higher in the hierarchy.
    everything.sort(key=lambda node: node.count("|"))
    if include_shapes:
        return everything

    present = set(everything)
    kept = []
    for node in everything:
        if not is_shape(node):
            kept.append(node)
            continue
        parent = (cmds.listRelatives(node, parent=True, fullPath=True)
                  or [None])[0]
        if parent in present:
            continue
        if cmds.attributeQuery("intermediateObject", node=node, exists=True)                 and cmds.getAttr(f"{node}.intermediateObject"):
            continue
        kept.append(node)
    return kept


def default_entry_name(nodes: Optional[List[str]] = None) -> str:
    """Propose an entry name from ``nodes`` (defaults to the selection)."""
    nodes = nodes if nodes is not None else selected_nodes()
    if not nodes:
        return "clipboard"
    short = nodes[0].split("|")[-1].split(":")[-1]
    if len(nodes) > 1:
        short = f"{short}_and_{len(nodes) - 1}"
    return sanitize_name(short)


def scene_namespaces() -> List[str]:
    """Return the scene namespaces, root first, as paste targets."""
    found = cmds.namespaceInfo(listOnlyNamespaces=True, recurse=True) or []
    found = [ns for ns in found if ns not in ("UI", "shared")]
    return [":"] + sorted(found)


def all_component_keys(nodes: Optional[List[str]] = None) -> List[str]:
    """Union of every component key ``nodes`` could contribute.

    Built from the wrapped classes themselves (plus the known labels) so a
    component added later is captured without editing this module. Used as
    the ``only`` filter on capture: it is a superset, and it overrides
    ``enabled_by_default``, which is how opt-in slices like ``keyframes``
    make it into the saved entry.
    """
    keys = set(COMPONENT_LABELS)
    for name in nodes or []:
        wrapped = dw_lsNode.lsNode(name)
        if not wrapped:
            continue
        keys.update(comp.key for comp in wrapped[0].preset_components)
    return sorted(keys)


def cleanup_hours() -> int:
    """Current cleanup delay in hours (0 = entries never expire)."""
    if not cmds.optionVar(exists=CLEANUP_OPTION_VAR):
        return DEFAULT_CLEANUP_HOURS
    return int(cmds.optionVar(query=CLEANUP_OPTION_VAR))


def set_cleanup_hours(hours: int = DEFAULT_CLEANUP_HOURS) -> int:
    """Store the cleanup delay. Returns the stored value."""
    hours = max(0, int(hours))
    cmds.optionVar(intValue=(CLEANUP_OPTION_VAR, hours))
    return hours


def cleanup_label(hours: int = -1) -> str:
    """Readable form of a delay ('24 hours (default)', '13 hours', ...)."""
    hours = cleanup_hours() if hours < 0 else hours
    for label, value in CLEANUP_CHOICES:
        if value == hours:
            return label
    return f"{hours} hours"


def run_cleanup(hours: int = -1) -> List[str]:
    """Drop entries older than the delay. Returns the removed names."""
    hours = cleanup_hours() if hours < 0 else hours
    return preset_clipboard.prune_clipboard(hours)


def list_entries() -> List[str]:
    """Clipboard entry names, newest first."""
    return preset_clipboard.list_clipboard()


def entry_info(name: str = "") -> dict:
    """Peek at an entry: name/path/saved/nodes/components/namespaces."""
    return preset_clipboard.clipboard_info(name)


def clipboard_location() -> str:
    """Folder the entries live in (see DW_PRESET_CLIPBOARD)."""
    return preset_clipboard.clipboard_dir()


def copy_selection(name: str = "",
                   nodes: Optional[List[str]] = None,
                   expand: bool = True,
                   include_shapes: bool = False) -> Optional[str]:
    """Capture ``nodes`` (or the selection) into the clipboard under ``name``.

    Args:
        name: Entry name; empty names it from the selection.
        nodes: Nodes to capture. Defaults to the selection.
        expand: Walk into the selected groups (see :func:`expand_selection`).
        include_shapes: Keep shapes whose transform is also captured. Off,
            since both share one preset identity.

    Returns:
        The written path, or None when nothing was captured.
    """
    roots = nodes if nodes is not None else selected_nodes()
    if not roots:
        logger.warning("copy_selection: nothing selected.")
        return None
    captured = expand_selection(roots, include_shapes) if expand else roots
    if not captured:
        logger.warning("copy_selection: nothing left to capture.")
        return None
    if len(captured) != len(roots):
        logger.info(f"copy_selection: {len(roots)} selected -> "
                    f"{len(captured)} node(s) with the hierarchy")
    entry = sanitize_name(name) if name else default_entry_name(roots)
    return preset_clipboard.save_to_clipboard(
        captured, entry, only=all_component_keys(captured))


@dw_decorators.singleUndoChunk
def paste_entry(name: str = "",
                include: Optional[Dict[str, Optional[list]]] = None,
                target_ns: str = ":",
                create: bool = True,
                apply_external: bool = True,
                ext_ns_map: Optional[Dict[str, str]] = None,
                select: bool = True) -> List[str]:
    """Rebuild a clipboard entry, keeping only the checked components.

    Args:
        name: Entry name.
        include: ``{identity: [component keys]}`` - identities absent from it
            are not rebuilt at all, an empty list rebuilds the bare node.
            None pastes everything the entry holds.
        target_ns: Namespace the rebuilt nodes land in (``:`` = root).
        create: Allow creating nodes that are missing from the scene.
        apply_external: False skips connections captured toward other assets.
        ext_ns_map: External-namespace remap, e.g. ``{"alien_999": "alien01"}``.
        select: Select the rebuilt nodes when done.

    Returns:
        The rebuilt node names.
    """
    wrapped = preset_clipboard.load_from_clipboard(name,
                                                   target_ns=target_ns,
                                                   create=create,
                                                   apply_external=apply_external,
                                                   ext_ns_map=ext_ns_map,
                                                   include=include)
    names = [node.tr or node.node for node in wrapped if node]
    existing = [n for n in names if cmds.objExists(n)]
    if select and existing:
        cmds.select(existing, replace=True)
    return existing


def delete_entry(name: str = "") -> int:
    """Delete one clipboard entry. Returns the number of files removed."""
    return preset_clipboard.clear_clipboard(name)


def clear_entries() -> int:
    """Delete every clipboard entry. Returns the number of files removed."""
    return preset_clipboard.clear_clipboard()
