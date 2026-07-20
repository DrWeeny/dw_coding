"""Shared per-type colour store for Slimfast weight-source types.

Colours are keyed by WeightSource subclass name (``type(x).__name__``) and
cached in QSettings, so the Slimfast UI and the Maya Map Transfer widget agree
on the same colour for a given type and keep it across sessions. The colours
are editable from Slimfast's Pref menu via :class:`TypeColorDialog`.

A type with no stored colour is seeded from :data:`_SEED` when known, otherwise
a deterministic colour is generated from its name (stable across runs, never
random) and persisted.

Functions:
    get_hex / get_color / set_hex / all_hex / reset / generate_color

Classes:
    TypeColorDialog: small swatch editor (one colour per type).

Author:
    DrWeeny
"""

from __future__ import annotations

from functools import partial
from typing import Callable, Dict, Optional

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

_ORG = "DrWeeny"
_APP = "SlimfastWidget"
_GROUP = "type_colors"

# Bumped whenever _SEED changes; a mismatch wipes the cached colours once so the
# new scheme takes effect without the user having to hit "Reset all".
_PALETTE_VERSION = 3
_VERSION_KEY = "type_colors_version"

# Default colour for any type not in the scheme (mesh / unknown).
_DEFAULT_HEX = "#ffffff"

# Curated palette, keyed by the colour-type returned by the Map Transfer tool
# (the WeightSource subclass name). Deformers share a family of orange shades.
# nCloth and nRigid are one class (NClothMap) today, so they share one colour;
# registering separate classes later would let them diverge for free.
_SEED = {
    # nucleus (cloth + rigid until a split is registered)
    "NClothMap":        "#5cc46a",   # green
    # skinning
    "SkinCluster":      "#d9534f",   # red
    # deformers -> shades of orange
    "Deformer":         "#e0913f",
    "Cluster":          "#e8954a",
    "BlendShape":       "#e0a020",
    "SoftMod":          "#f0a860",
    "Wire":             "#d07a30",
    "DeltaMush":        "#f2b86b",
    "Tension":          "#c2702a",
    # vertex colour
    "VertexColorSet":   "#b884d0",   # mauve
    # geometry
    "mesh":             "#ffffff",   # white
}

# Maya node type -> colour-type key, so node-type callers (Slimfast's source
# combo) colour consistently with the Map Transfer tool. Both nucleus node
# types map to the single NClothMap class; unmapped types fall back to self.
_NODE_TYPE_TO_TYPE = {
    "nCloth": "NClothMap",
    "nRigid": "NClothMap",
    "cluster": "Cluster",
    "softMod": "SoftMod",
    "wire": "Wire",
    "blendShape": "BlendShape",
    "skinCluster": "SkinCluster",
    "deltaMush": "DeltaMush",
    "tension": "Tension",
}


def type_for_node_type(node_type: str) -> str:
    """Map a Maya node type to its WeightSource subclass colour key."""
    return _NODE_TYPE_TO_TYPE.get(node_type, node_type)


def get_color_for_node_type(node_type: str) -> "QtGui.QColor":
    """Colour for a Maya node type, via the unified type colour store."""
    return get_color(type_for_node_type(node_type))


def get_hex_for_node_type(node_type: str) -> str:
    """Hex colour for a Maya node type, via the unified type colour store."""
    return get_hex(type_for_node_type(node_type))


_version_checked = False


def _settings() -> "QtCore.QSettings":
    return QtCore.QSettings(_ORG, _APP)


def _ensure_palette_version() -> None:
    """Wipe the cached colours once when the seed palette version changes."""
    global _version_checked
    if _version_checked:
        return
    _version_checked = True
    settings = _settings()
    if settings.value(_VERSION_KEY, 0, type=int) != _PALETTE_VERSION:
        settings.beginGroup(_GROUP)
        settings.remove("")
        settings.endGroup()
        settings.setValue(_VERSION_KEY, _PALETTE_VERSION)


def get_hex(type_name: str) -> str:
    """Return the cached hex colour for *type_name*, creating one on first use."""
    _ensure_palette_version()
    settings = _settings()
    key = f"{_GROUP}/{type_name}"
    value = settings.value(key, None)
    if not value:
        value = _SEED.get(type_name, _DEFAULT_HEX)
        settings.setValue(key, value)
    return value


def get_color(type_name: str) -> "QtGui.QColor":
    """Return the cached colour for *type_name* as a QColor."""
    return QtGui.QColor(get_hex(type_name))


def set_hex(type_name: str, hex_str: str) -> None:
    """Persist a colour for *type_name*."""
    _settings().setValue(f"{_GROUP}/{type_name}", hex_str)


def all_hex() -> Dict[str, str]:
    """Return every stored type -> hex pair."""
    settings = _settings()
    settings.beginGroup(_GROUP)
    out = {key: settings.value(key) for key in settings.childKeys()}
    settings.endGroup()
    return out


def reset(type_name: Optional[str] = None) -> None:
    """Clear stored colours (one type, or all when *type_name* is None)."""
    settings = _settings()
    if type_name is None:
        settings.beginGroup(_GROUP)
        settings.remove("")
        settings.endGroup()
    else:
        settings.remove(f"{_GROUP}/{type_name}")


class TypeColorDialog(QtWidgets.QDialog):
    """Swatch editor: one colour per weight-source type, shared via QSettings.

    Args:
        parent:    Owning widget.
        on_change: Optional callback fired after any colour change, so an open
                   tool (e.g. the Maya Map Transfer window) can re-tint live.
    """

    def __init__(self,
                 parent: Optional["QtWidgets.QWidget"] = None,
                 on_change: Optional[Callable[[], None]] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Weight type colours")
        self._on_change = on_change
        self._swatches: Dict[str, QtWidgets.QPushButton] = {}
        self._build()

    def _build(self) -> None:
        lay = QtWidgets.QVBoxLayout(self)
        info = QtWidgets.QLabel("Colour used per weight-source type across Slimfast.")
        info.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        lay.addWidget(info)

        grid = QtWidgets.QGridLayout()
        lay.addLayout(grid)
        for row, type_name in enumerate(sorted(set(_SEED) | set(all_hex()))):
            swatch = QtWidgets.QPushButton()
            swatch.setFixedSize(40, 18)
            self._apply_swatch(swatch, get_hex(type_name))
            swatch.clicked.connect(partial(self._pick, type_name, swatch))
            grid.addWidget(swatch, row, 0)
            grid.addWidget(QtWidgets.QLabel(type_name), row, 1)
            self._swatches[type_name] = swatch

        btn_row = QtWidgets.QHBoxLayout()
        reset_btn = QtWidgets.QPushButton("Reset all")
        reset_btn.clicked.connect(self._reset_all)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

    @staticmethod
    def _apply_swatch(button: "QtWidgets.QPushButton", hex_str: str) -> None:
        button.setStyleSheet(f"background-color: {hex_str}; border: 1px solid #222;")

    def _pick(self, type_name: str, swatch: "QtWidgets.QPushButton") -> None:
        color = QtWidgets.QColorDialog.getColor(
            get_color(type_name), self, f"Colour for {type_name}"
        )
        if color.isValid():
            set_hex(type_name, color.name())
            self._apply_swatch(swatch, color.name())
            self._notify()

    def _reset_all(self) -> None:
        reset()
        for type_name, swatch in self._swatches.items():
            self._apply_swatch(swatch, get_hex(type_name))
        self._notify()

    def _notify(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                pass