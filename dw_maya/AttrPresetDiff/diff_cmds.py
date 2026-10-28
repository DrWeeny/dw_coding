"""
diff_cmds.py - AttrPresetDiff core: sources, Maya defaults, the diff, edits.

Summary:
    Compares attribute values between two sources, with the node type's Maya
    default as a third, reference column. A source is a preset file (one node
    entry of a dw_preset envelope), a scene node, or the Maya default of a node
    type. Values are keyed by (role, attr) - the role split the v2 preset
    AttributeComponent writes (transform / shape for a DAG pair, node for a DG
    node) - and every source is read with that same capture code, so a row that
    differs is a real difference, never two readers disagreeing.

    Maya defaults are what a bare createNode gives: a throwaway node is
    created with undo off, captured, deleted, and the values cached as json
    (one file per node type, keyed by the Maya and plugin version). The cache
    is also what answers when the plugin is not loaded.

Classes:
    Source - base: label, node_type, values {(role, attr): value}, editable.
    FileSource - one node entry of a preset file; edit in memory, save().
    NodeSource - a scene node, read live; edits set the attribute (one undo).
    DefaultSource - the node type's createNode defaults; read-only.
    Row - one (role, attr) across A / B / default, with its differences.

Functions:
    default_values - a node type's defaults, from cache or a throwaway node.
    type_own_attrs - attributes a node type declares itself (not inherited).
    diff_rows - the rows for two sources and a default.
    parse_value - text typed in a cell -> a value shaped like the old one.

Example:
    import dw_maya.AttrPresetDiff.diff_cmds as dc
    a = dc.FileSource("D:/presets/hood_soft.json")
    b = dc.NodeSource("nClothShape1")
    d = dc.DefaultSource(a.node_type)
    for row in dc.diff_rows(a, b, d, differences_only=True):
        print(row.key, row.a, row.b, row.default)

Author:
    DrWeeny
"""

from __future__ import annotations

import ast
import json
import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import maya.cmds as cmds

import dw_maya.dw_presets_io as dw_presets_io
import dw_maya.dw_presets_io.preset_components as pcomp
from dw_maya.dw_decorators import dw_undo
from dw_maya.dw_maya_nodes import MayaNode
from dw_logger import get_logger

logger = get_logger()

Key = Tuple[str, str]   # (role, attr)
ROLES = ("transform", "shape", "node")
DEFAULTS_FORMAT = "dw_node_defaults"
DEFAULTS_VERSION = 1
_TOLERANCE = 1e-6


class _Missing(object):
    """The attribute is not in this source (shown as an empty cell)."""

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()


# ============================================================================
# VALUES
# ============================================================================

def _flatten(attributes: Dict[str, Dict[str, Any]]) -> Dict[Key, Any]:
    """{role: {attr: value}} -> {(role, attr): value}."""
    return {(role, attr): value
            for role, values in (attributes or {}).items()
            for attr, value in (values or {}).items()}


def same(left: Any, right: Any) -> bool:
    """Equal values, numbers within a relative tolerance (bool and 0/1 compare equal)."""
    if left is MISSING or right is MISSING:
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        scale = max(1.0, abs(float(left)), abs(float(right)))
        return abs(float(left) - float(right)) <= _TOLERANCE * scale
    return left == right


def parse_value(text: str,
                like: Any = MISSING,) -> Any:
    """
    The value typed in a cell, shaped like `like` (the value it replaces, or
    the other side's): bool accepts 1/0/true/false/on/off, int accepts 2.0,
    a string stays the text. Without a model, a python literal or the text.
    Raises ValueError when the text does not fit the model's type.
    """
    text = text.strip()
    if isinstance(like, bool):
        lowered = text.lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{text!r} is not a bool (1/0, true/false, on/off)")
    if isinstance(like, int):
        return int(round(float(text)))
    if isinstance(like, float):
        return float(text)
    if isinstance(like, str):
        return text
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def format_value(value: Any) -> str:
    """Cell text: floats short, MISSING empty."""
    if value is MISSING:
        return ""
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        return f"{value:.6g}"
    return f"{value}"


# ============================================================================
# NODE TYPES
# ============================================================================

def type_own_attrs(node_type: str) -> Optional[set]:
    """
    Long and short names of the attributes `node_type` declares itself, without
    what it inherits (visibility, intermediateObject, ...). None when the type
    is not registered (plugin not loaded) - the caller then shows everything.

    A python plugin type's direct parent can be a synthetic one MNodeClass
    cannot open (THlocatorShape, THsurfaceShape), so the base is the nearest
    queryable ancestor.
    """
    import maya.api.OpenMaya as om

    def names(type_name: str) -> set:
        out = set()
        for attr in om.MNodeClass(type_name).getAttributes():
            fn = om.MFnAttribute(attr)
            out.update((fn.name, fn.shortName))
        return out

    try:
        own = names(node_type)
        lineage = cmds.nodeType(node_type, isTypeName=True, inherited=True) or []
    except RuntimeError:
        return None
    for parent_type in reversed(lineage[:-1]):
        try:
            return own - names(parent_type)
        except RuntimeError:
            continue
    return own


def role_types(node_type: str) -> Dict[str, str]:
    """The node type each role's attributes belong to (a DAG pair's transform is a transform)."""
    return {"transform": "transform", "shape": node_type, "node": node_type}


# ============================================================================
# MAYA DEFAULTS
# ============================================================================

def defaults_dir() -> str:
    """Where defaults are cached: DW_NODE_DEFAULTS_PATH, else a stable temp folder."""
    return os.environ.get("DW_NODE_DEFAULTS_PATH") or os.path.join(tempfile.gettempdir(), "dw_node_defaults")


def _plugin_of(node_type: str) -> Optional[Dict[str, str]]:
    """{'name', 'version'} of the loaded plugin registering `node_type`, None for a built-in type."""
    for plugin in cmds.pluginInfo(query=True, listPlugins=True) or []:
        if node_type in (cmds.pluginInfo(plugin, query=True, dependNode=True) or []):
            return {"name": plugin, "version": cmds.pluginInfo(plugin, query=True, version=True)}
    return None


def _type_known(node_type: str) -> bool:
    return node_type in (cmds.allNodeTypes() or [])


def _capture_throwaway(node_type: str) -> Dict[str, Dict[str, Any]]:
    """
    createNode `node_type`, capture it like a preset, delete everything the
    creation made. Undo is off for the duration (nothing to undo, and the
    queue is not flushed); the scene is left as it was found.
    """
    before = set(cmds.ls(long=True) or [])
    cmds.undoInfo(stateWithoutFlush=False)
    try:
        node = cmds.createNode(node_type, skipSelect=True)
        entry = MayaNode(node).createPreset(only=["attributes"])
        return next(iter(entry.values())).get("attributes", {})
    finally:
        made = [n for n in set(cmds.ls(long=True) or []) - before if cmds.objExists(n)]
        if made:
            cmds.delete(made)
        cmds.undoInfo(stateWithoutFlush=True)


def default_values(node_type: str,
                   refresh:   bool = False,) -> Dict[Key, Any]:
    """
    The values a bare createNode of `node_type` gets, as {(role, attr): value}.
    Served from the json cache when its Maya / plugin version matches (or when
    the type is not registered here at all - the cache is then the only
    answer), otherwise measured on a throwaway node and cached.
    Raises ValueError for an unknown type with no cache.
    """
    path = os.path.join(defaults_dir(), f"{node_type}.json")
    cached = None
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as handle:
                cached = json.load(handle)
        except (OSError, ValueError):
            logger.warning(f"AttrPresetDiff: unreadable defaults cache {path}, measuring again")

    if not _type_known(node_type):
        if cached:
            return _flatten(cached.get("values"))
        raise ValueError(f"Unknown node type {node_type!r} (plugin not loaded?) and no cached defaults.")

    stamp = {"maya": cmds.about(version=True), "plugin": _plugin_of(node_type)}
    if cached and not refresh and all(cached.get(k) == v for k, v in stamp.items()):
        return _flatten(cached.get("values"))

    values = _capture_throwaway(node_type)
    data = {"format": DEFAULTS_FORMAT, "version": DEFAULTS_VERSION, "node_type": node_type, **stamp,
            "values": values}
    try:
        dw_presets_io.save_json(path, data)
    except Exception as e:
        logger.warning(f"AttrPresetDiff: could not cache defaults to {path}: {e}")
    return _flatten(values)


# ============================================================================
# SOURCES
# ============================================================================

class Source(object):
    """A side of the diff: values keyed by (role, attr)."""

    kind = ""
    editable = False

    def __init__(self) -> None:
        self.node_type: str = ""
        self.values: Dict[Key, Any] = {}

    @property
    def label(self) -> str:
        return ""

    @property
    def dirty(self) -> bool:
        return False

    def get(self,
            key: Key,) -> Any:
        return self.values.get(key, MISSING)

    def set(self,
            key:   Key,
            value: Any,) -> None:
        raise NotImplementedError(f"{self.kind} source is read-only")

    def refresh(self) -> None:
        """Re-read the values (a node changes under the tool, a file does not)."""


class FileSource(Source):
    """
    One node entry of a dw_preset file. Edits stay in memory until save(),
    which rewrites the whole document - the other entries, components and
    keys (rules, namespaces...) untouched. A pre-v2 flat entry ({attr: value}
    beside nodeType) is read and written back flat, under the 'node' role.
    """

    kind = "file"
    editable = True

    def __init__(self,
                 path:     str,
                 identity: Optional[str] = None,) -> None:
        super().__init__()
        self.path = path
        with open(path, encoding="utf-8") as handle:
            self._doc = json.load(handle)
        self._nodes = self._doc.get("nodes", self._doc) if isinstance(self._doc, dict) else {}
        self._nodes = {k: v for k, v in self._nodes.items() if isinstance(v, dict) and "nodeType" in v}
        if not self._nodes:
            raise ValueError(f"{os.path.basename(path)}: no node entry (not a dw_preset?)")
        self.identity = identity if identity in self._nodes else next(iter(self._nodes))
        self._dirty = False
        self._read()

    @property
    def identities(self) -> List[str]:
        return list(self._nodes)

    @property
    def label(self) -> str:
        star = "*" if self._dirty else ""
        return f"{os.path.basename(self.path)}{star} [{self.identity}]"

    @property
    def dirty(self) -> bool:
        return self._dirty

    def _body(self) -> dict:
        return self._nodes[self.identity]

    def _is_flat(self) -> bool:
        return "attributes" not in self._body()

    def _read(self) -> None:
        body = self._body()
        self.node_type = body.get("nodeType", "")
        if self._is_flat():
            self.values = {("node", a): v for a, v in body.items() if a != "nodeType" and not isinstance(v, dict)}
        else:
            self.values = _flatten(body.get("attributes"))

    def select(self,
               identity: str,) -> None:
        self.identity = identity
        self._read()

    def set(self,
            key:   Key,
            value: Any,) -> None:
        role, attr = key
        body = self._body()
        if self._is_flat():
            body[attr] = value
        else:
            body.setdefault("attributes", {}).setdefault(role, {})[attr] = value
        self.values[key] = value
        self._dirty = True

    def save(self,
             path: Optional[str] = None,) -> str:
        path = path or self.path
        if not dw_presets_io.save_json(path, self._doc):
            raise OSError(f"could not write {path}")
        self.path = path
        self._dirty = False
        return path


class NodeSource(Source):
    """A scene node, read live through the preset capture; edits set the attribute."""

    kind = "node"
    editable = True

    def __init__(self,
                 node: str,) -> None:
        super().__init__()
        if not cmds.objExists(node):
            raise ValueError(f"{node!r} does not exist")
        self._node = MayaNode(node)
        self.refresh()

    @property
    def label(self) -> str:
        return (self._node.sh or self._node.node or "").split("|")[-1]

    def refresh(self) -> None:
        entry = self._node.createPreset(only=["attributes"])
        body = next(iter(entry.values()))
        self.node_type = body.get("nodeType", "")
        self.values = _flatten(body.get("attributes"))

    def _plug_node(self,
                   role: str,) -> Optional[str]:
        return {"transform": self._node.tr, "shape": self._node.sh, "node": self._node.node}.get(role)

    @dw_undo.singleUndoChunk
    def set(self,
            key:   Key,
            value: Any,) -> None:
        role, attr = key
        node = self._plug_node(role)
        if not node:
            raise ValueError(f"{self.label} has no {role} node")
        pcomp.apply_attr(f"{node}.{attr}", value)
        self.values[key] = cmds.getAttr(f"{node}.{attr}")


class DefaultSource(Source):
    """What createNode gives a node type (cached json); read-only."""

    kind = "default"

    def __init__(self,
                 node_type: str,
                 refresh:   bool = False,) -> None:
        super().__init__()
        self.node_type = node_type
        self.values = default_values(node_type, refresh=refresh)

    @property
    def label(self) -> str:
        return f"default {self.node_type}"


# ============================================================================
# DIFF
# ============================================================================

class Row(object):
    """One (role, attr) across the sources."""

    __slots__ = ("key", "a", "b", "default")

    def __init__(self,
                 key:     Key,
                 a:       Any,
                 b:       Any,
                 default: Any,) -> None:
        self.key = key
        self.a = a
        self.b = b
        self.default = default

    @property
    def a_vs_b(self) -> bool:
        return not same(self.a, self.b)

    @property
    def a_changed(self) -> bool:
        """A differs from the default (only meaningful when there is one)."""
        return self.default is not MISSING and self.a is not MISSING and not same(self.a, self.default)

    @property
    def b_changed(self) -> bool:
        return self.default is not MISSING and self.b is not MISSING and not same(self.b, self.default)


def diff_rows(a:                Optional[Source],
              b:                Optional[Source],
              default:          Optional[Source] = None,
              differences_only: bool = False,
              own_only:         bool = True,
              elements:         bool = False,
              text:             str = "",) -> List[Row]:
    """
    One Row per (role, attr) present in A or B, sorted by role then name.

    differences_only: keep rows where A != B, or - with a single source - where
        it differs from the default.
    own_only: hide attributes the node type inherits (when the type is known).
    elements: show array elements (bones[3].mass...), hidden by default -
        per-element values are a chain-length-dependent layer, not a preset.
    text: case-insensitive substring filter on the attribute name.
    """
    sources = [s for s in (a, b) if s is not None]
    keys = set()
    for source in sources:
        keys.update(source.values)

    own_by_role = {}
    if own_only and sources:
        node_type = sources[0].node_type
        for role, type_name in role_types(node_type).items():
            own_by_role[role] = type_own_attrs(type_name) if type_name else None

    needle = text.strip().lower()
    rows = []
    for key in sorted(keys, key=lambda k: (ROLES.index(k[0]) if k[0] in ROLES else 9, k[1].lower())):
        role, attr = key
        if not elements and "[" in attr:
            continue
        if needle and needle not in attr.lower():
            continue
        own = own_by_role.get(role)
        if own is not None and attr.split(".")[0].split("[")[0] not in own:
            continue
        row = Row(key,
                  a.get(key) if a else MISSING,
                  b.get(key) if b else MISSING,
                  default.get(key) if default else MISSING)
        if differences_only:
            interesting = row.a_vs_b if len(sources) == 2 else (row.a_changed or row.b_changed)
            if not interesting:
                continue
        rows.append(row)
    return rows


@dw_undo.singleUndoChunk
def copy_rows(rows:   List[Row],
              target: Source,
              origin: str,) -> List[str]:
    """
    Copy each row's `origin` value ('a' / 'b' / 'default') onto `target`, one
    undo step for a node target. Returns the problems (a missing value, a
    refused write) instead of stopping at the first one.
    """
    problems = []
    for row in rows:
        value = getattr(row, origin)
        if value is MISSING:
            problems.append(f"{row.key[0]}.{row.key[1]}: no {origin} value")
            continue
        try:
            target.set(row.key, value)
        except Exception as e:
            problems.append(f"{row.key[0]}.{row.key[1]}: {e}")
    return problems
