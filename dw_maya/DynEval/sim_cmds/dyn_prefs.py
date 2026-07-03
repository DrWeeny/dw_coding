"""
sim_cmds/dyn_prefs.py — DynEval user preferences.

Persisted with Maya optionVars so they survive the session and are readable
from batch scripts as well as the UI (the Pref menu in main_ui writes here,
NucleusCacheOps reads here — no hub key involved).

Preferences
-----------
cache distribution: 'OneFile' (default) or 'OneFilePerFrame'. Per-frame
caching pays off when batching simulations — each frame lands on disk as
it is computed, so an in-progress sim can be inspected for free.

cache mode: 'increment' (default, each create makes a new version) or
'replace' (create overwrites the attached version — or the latest when
none is attached).

hidden node types: leaf types unchecked in the tree filter row
(e.g. hide nRigids to declutter).
"""

from typing import Iterable, Set

import maya.cmds as cmds

OPT_CACHE_DISTRIBUTION = "dwDynEval_cacheDistribution"
OPT_CACHE_MODE = "dwDynEval_cacheMode"
OPT_HIDDEN_NODE_TYPES = "dwDynEval_hiddenNodeTypes"

CACHE_DISTRIBUTIONS = ("OneFile", "OneFilePerFrame")
DEFAULT_DISTRIBUTION = "OneFile"

CACHE_MODES = ("increment", "replace")
DEFAULT_CACHE_MODE = "increment"


def get_cache_distribution() -> str:
    """Current cache distribution ('OneFile' when unset or invalid)."""
    if cmds.optionVar(exists=OPT_CACHE_DISTRIBUTION):
        value = cmds.optionVar(query=OPT_CACHE_DISTRIBUTION)
        if value in CACHE_DISTRIBUTIONS:
            return value
    return DEFAULT_DISTRIBUTION


def set_cache_distribution(value: str) -> None:
    if value not in CACHE_DISTRIBUTIONS:
        raise ValueError(
            f"Invalid cache distribution {value!r}, "
            f"expected one of {CACHE_DISTRIBUTIONS}."
        )
    cmds.optionVar(stringValue=(OPT_CACHE_DISTRIBUTION, value))


def get_cache_mode() -> str:
    """Current cache create mode ('increment' when unset or invalid)."""
    if cmds.optionVar(exists=OPT_CACHE_MODE):
        value = cmds.optionVar(query=OPT_CACHE_MODE)
        if value in CACHE_MODES:
            return value
    return DEFAULT_CACHE_MODE


def set_cache_mode(value: str) -> None:
    if value not in CACHE_MODES:
        raise ValueError(
            f"Invalid cache mode {value!r}, expected one of {CACHE_MODES}."
        )
    cmds.optionVar(stringValue=(OPT_CACHE_MODE, value))


def get_hidden_node_types() -> Set[str]:
    """Leaf node types currently hidden in the sim tree (empty = show all)."""
    if cmds.optionVar(exists=OPT_HIDDEN_NODE_TYPES):
        value = cmds.optionVar(query=OPT_HIDDEN_NODE_TYPES) or ""
        return {t for t in value.split(",") if t}
    return set()


def set_hidden_node_types(types: Iterable[str]) -> None:
    cmds.optionVar(
        stringValue=(OPT_HIDDEN_NODE_TYPES, ",".join(sorted(set(types))))
    )