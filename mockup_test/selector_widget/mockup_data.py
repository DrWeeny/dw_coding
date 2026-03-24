"""
Mockup data module that replaces pub / pyu pipeline dependencies.

Provides a fake project object and token-chain resolution so that
wgt_shot_select_standalone.py can be run offline without any pipeline
packages installed.

Features

- Supplies fake shot and asset hierarchies with familiar-sounding but
  agnostic names (fruits, vehicles, animals … instead of real show names).
- Exposes the same surface that wgt_shot_select uses:
    project.get()                          → MockProject
    MockProject.VersionAliases             → token-order dict
    MockProject.get_publish_dir_pattern()  → dummy pattern string
    MockProject.next_token_values()        → (token_name, [values])
    MockProject.get_valid_departments()    → list[str]
    MockProject.get_valid_lods()           → list[str]

Usage

    import selector_widget.mockup_data as project
    proj = project.get()
    print(proj.VersionAliases)

"""

# ---------------------------------------------------------------------------
# Shot tree
#   episode → sequence → shot → department → element → revision
# ---------------------------------------------------------------------------
_SHOT_TREE = {
    "ep001": {
        "sq010": {
            "sh0010": {"anim": ["body", "face"], "cfx": ["cloth", "hair"], "fx": ["dust"]},
            "sh0020": {"anim": ["body"],          "cfx": ["cloth"],         "fx": []},
            "sh0030": {"anim": ["body", "face"],  "cfx": [],                "fx": ["spark"]},
        },
        "sq020": {
            "sh0010": {"anim": ["body"], "cfx": ["hair"],  "fx": []},
            "sh0050": {"anim": ["body"], "cfx": [],        "fx": ["smoke", "debris"]},
        },
    },
    "ep002": {
        "sq010": {
            "sh0010": {"anim": ["body"],         "cfx": ["cloth", "hair"], "fx": []},
            "sh0040": {"anim": ["body", "face"], "cfx": ["cloth"],         "fx": ["rain"]},
        },
        "sq030": {
            "sh0020": {"anim": ["body"], "cfx": ["hair"], "fx": []},
            "sh0060": {"anim": ["body"], "cfx": [],       "fx": ["explosion"]},
        },
    },
    "ep003": {
        "sq005": {
            "sh0010": {"anim": ["body"],         "cfx": ["cloth"],         "fx": []},
            "sh0030": {"anim": ["body", "face"], "cfx": ["cloth", "hair"], "fx": ["snow"]},
        },
    },
}

# Revisions are always the same set
_REVISIONS = ["v001", "v002", "v003", "v004", "v005"]

# ---------------------------------------------------------------------------
# Asset tree
#   category → name → variation → department → lod
# ---------------------------------------------------------------------------
_ASSET_TREE = {
    "fruit": {
        "apple": {
            "RED": {
                "model": ["default", "rend", "high"],
                "rig":   ["default", "high"],
                "cfx":   ["default", "rend"],
                "light": [],
            },
            "GREEN": {
                "model": ["default", "rend"],
                "rig":   ["default"],
                "cfx":   [],
                "light": [],
            },
        },
        "banana": {
            "STD": {
                "model": ["default", "high"],
                "rig":   ["default"],
                "cfx":   [],
                "light": [],
            },
            "BRUISED": {
                "model": ["default"],
                "rig":   [],
                "cfx":   [],
                "light": [],
            },
        },
        "cherry": {
            "STD": {
                "model": ["default"],
                "rig":   [],
            },
        },
    },
    "vehicle": {
        "car": {
            "STD": {
                "model": ["default", "rend", "high", "low"],
                "rig":   ["default"],
                "cfx":   [],
                "light": ["default"],
            },
            "DAMAGED": {
                "model": ["default", "high"],
                "rig":   [],
                "cfx":   [],
                "light": [],
            },
        },
        "truck": {
            "STD": {
                "model": ["default", "rend"],
                "rig":   ["default"],
            },
            "HEAVY": {
                "model": ["default"],
                "rig":   [],
            },
        },
        "bicycle": {
            "STD": {
                "model": ["default", "high"],
                "rig":   ["default", "high"],
            },
        },
    },
    "animal": {
        "cat": {
            "STD": {
                "model": ["default", "rend"],
                "rig":   ["default", "high"],
                "cfx":   ["default", "rend", "fx"],
                "light": [],
            },
            "FLUFFY": {
                "model": ["default"],
                "rig":   [],
                "cfx":   [],
                "light": [],
            },
        },
        "dog": {
            "STD": {
                "model": ["default", "rend", "high"],
                "rig":   ["default", "high"],
                "cfx":   ["default"],
                "light": [],
            },
            "SHAGGY": {
                "model": ["default", "rend"],
                "rig":   ["default"],
                "cfx":   ["default", "rend", "fx"],
                "light": [],
            },
        },
        "tree": {
            "OAK": {
                "model": ["default", "rend"],
                "rig":   [],
                "cfx":   ["default", "fx"],
                "light": [],
            },
            "PINE": {
                "model": ["default"],
                "rig":   [],
            },
        },
    },
    "prop": {
        "table": {
            "STD": {
                "model": ["default", "rend"],
                "rig":   [],
            },
        },
        "chair": {
            "STD": {
                "model": ["default", "high"],
                "rig":   [],
            },
            "BROKEN": {
                "model": ["default"],
                "rig":   [],
            },
        },
        "lamp": {
            "STD": {
                "model": ["default", "rend", "high"],
                "light": ["default"],
            },
        },
    },
}

# ---------------------------------------------------------------------------
# All valid departments / lods regardless of what exists on disk
# ---------------------------------------------------------------------------
_ALL_DEPARTMENTS_ASSET = [
    "model", "rig", "cfx", "light", "crowd", "scouting", "camera",
]

_ALL_DEPARTMENTS_SHOT = [
    "anim", "cfx", "fx", "layout", "lighting", "comp", "previz",
]

_ALL_LODS = [
    "default", "low", "high", "rend", "fx",
]

# ---------------------------------------------------------------------------
# Dummy pattern (the actual pattern string is only used as a key; the mock
# project does not parse it).
# ---------------------------------------------------------------------------
_PATTERN = "{episode}/{sequence}/{shot}/{department}/{element}/{revision}"
_ASSET_PATTERN = "{category}/{name}/{variation}/{department}/{lod}/{revision}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sorted_keys(d: dict) -> list:
    return sorted(d.keys())


class MockProject:
    """
    Drop-in replacement for the pub project object used by wgt_shot_select.

    Attributes
        VersionAliases  dict mapping type → ordered token list
        TokenAliases    dict mapping alias → canonical token name (kept for compat)

    Example
        proj = MockProject()
        token_name, values = proj.next_token_values("asset", proj.get_publish_dir_pattern(),
                                                     category="fruit")
        # → ("name", ["apple", "banana", "cherry"])
    """

    VersionAliases = {
        "shot":  ["episode", "sequence", "shot", "department", "element", "revision"],
        "asset": ["category", "name", "variation", "department", "lod", "revision"],
    }

    TokenAliases = {
        "asset": {
            "category":   "category",
            "name":       "name",
            "variation":  "variation",
            "department": "department",
            "lod":        "lod",
            "revision":   "revision",
        },
    }

    def get_publish_dir_pattern(self) -> str:
        return _PATTERN

    def get_version_dir_pattern(self) -> str:
        return _ASSET_PATTERN

    # ------------------------------------------------------------------
    # Core token resolution — mirrors pub.project behaviour:
    #   next_token_values(type_name, pattern, **already_resolved_tokens)
    #   → (next_token_name, [possible_values])
    # ------------------------------------------------------------------
    def next_token_values(self, type_name: str, pattern: str, **tokens) -> tuple:
        """
        Return the name and possible values for the *next* unresolved token.

        Args:
            type_name: "shot" or "asset"
            pattern:   Ignored in mockup (kept for API compatibility)
            **tokens:  Already-resolved tokens  e.g. category="fruit"

        Returns:
            (token_name, [values]) or None when the chain is exhausted
        """
        order = self.VersionAliases.get(type_name, [])

        # Find the first token that hasn't been resolved yet
        for token in order:
            if token not in tokens:
                values = self._get_values_for_token(type_name, token, tokens)
                if values is None:
                    return None
                return token, values

        return None  # All tokens resolved

    def _get_values_for_token(self, type_name: str, token: str, resolved: dict):
        if type_name == "shot":
            return self._shot_values(token, resolved)
        else:
            return self._asset_values(token, resolved)

    # ------------------------------------------------------------------
    # Shot resolution
    # ------------------------------------------------------------------
    def _shot_values(self, token: str, resolved: dict):
        if token == "episode":
            return _sorted_keys(_SHOT_TREE)

        ep = resolved.get("episode")
        if ep not in _SHOT_TREE:
            return None

        if token == "sequence":
            return _sorted_keys(_SHOT_TREE[ep])

        sq = resolved.get("sequence")
        if sq not in _SHOT_TREE[ep]:
            return None

        if token == "shot":
            return _sorted_keys(_SHOT_TREE[ep][sq])

        sh = resolved.get("shot")
        if sh not in _SHOT_TREE[ep][sq]:
            return None

        shot_depts = _SHOT_TREE[ep][sq][sh]

        if token == "department":
            return _sorted_keys(shot_depts)

        dept = resolved.get("department")
        if dept not in shot_depts:
            return None

        if token == "element":
            return shot_depts[dept] if shot_depts[dept] else ["none"]

        # revision
        return _REVISIONS

    # ------------------------------------------------------------------
    # Asset resolution
    # ------------------------------------------------------------------
    def _asset_values(self, token: str, resolved: dict):
        if token == "category":
            return _sorted_keys(_ASSET_TREE)

        cat = resolved.get("category")
        if cat not in _ASSET_TREE:
            return None

        if token == "name":
            return _sorted_keys(_ASSET_TREE[cat])

        name = resolved.get("name")
        if name not in _ASSET_TREE[cat]:
            return None

        if token == "variation":
            return _sorted_keys(_ASSET_TREE[cat][name])

        var = resolved.get("variation")
        if var not in _ASSET_TREE[cat][name]:
            return None

        var_depts = _ASSET_TREE[cat][name][var]

        if token == "department":
            return _sorted_keys(var_depts)

        dept = resolved.get("department")
        if dept not in var_depts:
            return None

        if token == "lod":
            return sorted(var_depts[dept]) if var_depts[dept] else ["default"]

        # revision
        return _REVISIONS

    # ------------------------------------------------------------------
    # Valid department / lod lists (used by PublishAssetUI to colour combos)
    # ------------------------------------------------------------------
    def get_valid_departments(self, type_name: str = "asset") -> list:
        if type_name == "asset":
            return list(_ALL_DEPARTMENTS_ASSET)
        return list(_ALL_DEPARTMENTS_SHOT)

    def get_valid_lods(self) -> list:
        return list(_ALL_LODS)

    # ------------------------------------------------------------------
    # Asset publish helpers (used by cfx_utils.files mockup below)
    # ------------------------------------------------------------------
    def list_asset_departments(self, category: str, name: str, variation: str) -> list:
        """Return departments that already have published data (non-empty lod list)."""
        try:
            var_data = _ASSET_TREE[category][name][variation]
            return [dept for dept, lods in var_data.items() if lods]
        except KeyError:
            return []

    def list_asset_lods(self, category: str, name: str, variation: str, department: str) -> list:
        """Return LODs that already exist for a given department."""
        try:
            return list(_ASSET_TREE[category][name][variation][department])
        except KeyError:
            return []


# Module-level singleton (mirrors pub.project.get())
_instance: MockProject = None


def get() -> MockProject:
    """Return the singleton MockProject instance."""
    global _instance
    if _instance is None:
        _instance = MockProject()
    return _instance


# ---------------------------------------------------------------------------
# Lightweight stubs for the two cfx_utils.files helpers used in PublishAssetUI
# ---------------------------------------------------------------------------

def list_pub_asset_departments(category: str, name: str, variation: str) -> list:
    """Return departments that already have published lods."""
    return get().list_asset_departments(category, name, variation)


def list_pub_asset_lod(category: str, name: str, variation: str, department: str) -> list:
    """Return lods that already exist for a given department."""
    return get().list_asset_lods(category, name, variation, department)
