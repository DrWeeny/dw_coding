"""Extensible deformer sub-panel registry for Slimfast.

Summary:
    Provides a plugin registry so code can register new deformer modes
    (radio-button label + source-combo filter + dedicated sub-panel widget)
    into the Slimfast deformer group without modifying ``main_ui.py``.

    The common UI elements — mesh picker, source combo, copy/paste, envelope
    and paint button — always live in ``main_ui.py``.  Each registered panel
    only contributes its *extra* widgets that appear between the source combo
    and the copy/paste row.

Features:
    - ``register_deformer_panel()`` public API: adds a radio button + panel.
    - ``get_mode_registry()``  returns the ordered registry for radio buttons.
    - ``get_panel_class()``    resolves a panel class from a Maya node type.
    - ``get_ctrl_mode()``      maps a mode_key to a controller mode string.
    - Built-in panels: DefaultPanel, BlendShapePanel, NucleusPanel,
      VtxAlphaPanel.

Classes:
    DeformerPanelBase  — Abstract base widget.
    DefaultPanel       — Empty placeholder (generic deformers).
    BlendShapePanel    — Adds a target-map combobox.
    NucleusPanel       — Adds a map-type badge label.
    VtxAlphaPanel      — Adds a greyscale-preview toggle button.

Functions:
    register_deformer_panel — Add an entry to the registry.
    get_mode_registry       — Return the sorted mode registry.
    get_panel_class         — Resolve a panel class by Maya node type.
    get_ctrl_mode           — Resolve the controller mode string.

Example:
    from dw_maya.Slimfast import wgt_deformer_panel

    class MySkinPanel(wgt_deformer_panel.DeformerPanelBase):
        def __init__(self, parent=None):
            super().__init__(parent)
            # build bone-list QListView here …

        def on_source_changed(self, source, active_map, ctrl):
            # refresh bone list from source.node_name
            pass

        def has_envelope(self):
            return True

    wgt_deformer_panel.register_deformer_panel(
        mode_key='skinCluster',
        label='SkinCluster',
        panel_class=MySkinPanel,
        ctrl_mode='deformer',          # maps to resolve_weight_sources mode
        node_types=['skinCluster'],    # these node types activate this panel
        order=15,                      # position among radio buttons
    )

TODO:
    - SkinCluster bone-list panel built-in implementation.
    - Persist per-panel settings in QSettings.

Author: DrWeeny
"""

from __future__ import annotations

import collections
from typing import Dict, List, Optional, Type, TYPE_CHECKING

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Signal, Slot
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Signal, Slot

if TYPE_CHECKING:
    from dw_maya.dw_paint.protocol import WeightSource
    from dw_maya.Slimfast.cmds import SlimfastController


# ---------------------------------------------------------------------------
# Internal registry stores
# ---------------------------------------------------------------------------

# Ordered by insertion; re-sorted by 'order' on every read.
_MODE_REGISTRY: Dict[str, dict] = collections.OrderedDict()

# Maps Maya node-type strings to a panel class.
_PANEL_BY_NODE_TYPE: Dict[str, Type['DeformerPanelBase']] = {}


# ---------------------------------------------------------------------------
# Public registry API
# ---------------------------------------------------------------------------

def register_deformer_panel(
    mode_key: str,
    label: str,
    panel_class: Type['DeformerPanelBase'],
    ctrl_mode: str = '',
    node_types: Optional[List[str]] = None,
    order: int = 100,
) -> None:
    """Register a deformer mode radio button and its companion sub-panel.

    Args:
        mode_key:    Unique string key (e.g. ``'skinCluster'``).
        label:       Radio-button text displayed in the deformer group header.
        panel_class: A ``DeformerPanelBase`` subclass to instantiate.
        ctrl_mode:   Mode string forwarded to ``SlimfastController.set_mode()``.
                     Defaults to ``mode_key`` when left empty.  Must be one of
                     the values accepted by ``resolve_weight_sources``
                     (``'all'``, ``'deformer'``, ``'nucleus'``, ``'vtxColor'``)
                     unless the controller has been extended.
        node_types:  Maya node-type strings whose selection in the source combo
                     triggers this panel.  Empty list → panel used as fallback.
        order:       Determines the left-to-right radio-button order (lower = left).

    Example::

        register_deformer_panel(
            'wire', 'Wire', WirePanel,
            ctrl_mode='deformer',
            node_types=['wire'],
            order=18,
        )
    """
    _MODE_REGISTRY[mode_key] = {
        'label': label,
        'panel_class': panel_class,
        'ctrl_mode': ctrl_mode or mode_key,
        'order': order,
    }
    for nt in (node_types or []):
        _PANEL_BY_NODE_TYPE[nt] = panel_class


def get_mode_registry() -> Dict[str, dict]:
    """Return the mode registry sorted by the ``order`` field.

    Returns:
        An ``OrderedDict`` mapping mode_key to its registry entry dict.
    """
    return collections.OrderedDict(
        sorted(_MODE_REGISTRY.items(), key=lambda kv: kv[1]['order'])
    )


def get_panel_class(node_type: str) -> Type['DeformerPanelBase']:
    """Return the panel class registered for a given Maya node type.

    Falls back to :class:`DefaultPanel` when no entry matches.

    Args:
        node_type: Maya type string (e.g. ``'blendShape'``).

    Returns:
        A ``DeformerPanelBase`` subclass.
    """
    return _PANEL_BY_NODE_TYPE.get(node_type, DefaultPanel)


def get_ctrl_mode(mode_key: str) -> str:
    """Return the controller mode string for the given registry key.

    Args:
        mode_key: Registry key (e.g. ``'nucleus'``).

    Returns:
        The ``ctrl_mode`` stored for that key, or ``mode_key`` itself if
        the key is not registered.
    """
    entry = _MODE_REGISTRY.get(mode_key)
    if entry:
        return entry['ctrl_mode']
    return mode_key


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class DeformerPanelBase(QtWidgets.QWidget):
    """Abstract base widget for deformer-specific sub-panels.

    Subclasses live inside the Slimfast deformer group, between the source
    combo and the copy/paste row.  They respond to lifecycle hooks called by
    ``SlimfastWidget`` and emit :attr:`map_selected` to request map switches.

    Attributes:
        map_selected: Emitted with the map attribute name to activate.
                      Connected to ``SlimfastController.select_map`` by the
                      parent widget.
    """

    map_selected = Signal(str)

    def on_source_changed(
        self,
        source: Optional['WeightSource'],
        active_map: str,
        ctrl: 'SlimfastController',
    ) -> None:
        """React to the active ``WeightSource`` changing.

        Called by ``SlimfastWidget._on_active_changed`` after the controller
        has updated its state.  Override to refresh bone lists, map badges, etc.

        Args:
            source:     New active source, or ``None`` when nothing is selected.
            active_map: Currently active map attribute name (empty string when
                        ``source`` is ``None``).
            ctrl:       Controller instance for read-only queries.
        """

    def on_combo_changed(self, node_type: str, maps: List[str]) -> None:
        """React to a different row being selected in the source combo.

        Called by ``SlimfastWidget._on_source_combo_changed`` *before* the
        controller activates the new source.  Override to pre-populate
        secondary widgets (e.g. target lists).

        Args:
            node_type: Maya type string of the newly selected node.
            maps:      All map attribute names available on that node.
        """

    def has_envelope(self) -> bool:
        """Return ``True`` if the envelope spinbox should be shown.

        Returns:
            ``True`` by default; override to ``False`` for panel types whose
            deformer nodes have no ``envelope`` attribute (e.g. nCloth maps,
            vertex-color alpha).
        """
        return True

    def has_paint(self) -> bool:
        """Return ``True`` if the Paint button should be enabled.

        Returns:
            ``True`` by default; override to ``False`` when the panel type
            cannot be painted via the standard artisan context.
        """
        return True


# ---------------------------------------------------------------------------
# Built-in panels
# ---------------------------------------------------------------------------

class DefaultPanel(DeformerPanelBase):
    """Empty placeholder panel used for generic deformer types."""


class BlendShapePanel(DeformerPanelBase):
    """Adds a secondary combobox for selecting a blendShape target map.

    Emits :attr:`map_selected` whenever the user picks a different target.
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self._combo = QtWidgets.QComboBox()
        self._combo.setMinimumWidth(220)
        self._combo.setToolTip('BlendShape target map')
        self._combo.currentIndexChanged.connect(self._on_target_changed)
        lay.addWidget(self._combo)

    @Slot(int)
    def _on_target_changed(self, index: int) -> None:
        map_name = self._combo.itemData(index)
        if map_name:
            self.map_selected.emit(map_name)

    def on_combo_changed(self, node_type: str, maps: List[str]) -> None:
        """Populate the target combo from the new blendShape map list.

        Args:
            node_type: Expected to be ``'blendShape'``.
            maps:      All map attribute names on the node.
        """
        if node_type != 'blendShape':
            return
        self._combo.blockSignals(True)
        self._combo.clear()
        for m in maps:
            display_label = 'base weights' if m == 'weightList' else m
            self._combo.addItem(display_label, m)
        self._combo.blockSignals(False)


class NucleusPanel(DeformerPanelBase):
    """Adds a colour-coded badge label showing the map type of a nucleus map.

    Possible states: ``None (disabled)``, ``PerVertex``, ``Texture``.
    """

    _MAP_TYPE_INFO: Dict[int, tuple] = {
        0: ('● None  (map disabled)', '#888888'),
        1: ('● PerVertex', '#4ecdc4'),
        2: ('● Texture', '#ddcc44'),
    }

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._badge = QtWidgets.QLabel()
        self._badge.setAlignment(QtCore.Qt.AlignCenter)
        self._badge.setStyleSheet('font-size: 11px;')
        lay.addWidget(self._badge)

    def on_source_changed(
        self,
        source: Optional['WeightSource'],
        active_map: str,
        ctrl: 'SlimfastController',
    ) -> None:
        """Update the badge text and colour from the nCloth map type.

        Args:
            source:     Expected to be an ``NClothMap`` instance.
            active_map: Active map attribute name.
            ctrl:       Unused; provided for interface consistency.
        """
        # Import here to avoid a hard dependency at module level.
        from dw_maya.dw_nucleus_utils import NClothMap
        if not isinstance(source, NClothMap) or not active_map:
            self._badge.setText('')
            return
        try:
            mt = source.map_type(active_map)
            text, color = self._MAP_TYPE_INFO.get(mt, (f'● type={mt}', '#aaaaaa'))
            self._badge.setText(text)
            self._badge.setStyleSheet(f'color: {color}; font-size: 11px;')
        except Exception:
            self._badge.setText('')

    def has_envelope(self) -> bool:
        """Return ``False`` — nCloth nodes have no ``envelope`` attribute."""
        return False


class VtxAlphaPanel(DeformerPanelBase):
    """Adds a greyscale-preview toggle for ``VertexColorAlpha`` sources.

    The toggle calls ``source.enable_preview()`` / ``source.disable_preview()``
    which switches the active colour set to a greyscale display mode in the
    Maya viewport.
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._preview_btn = QtWidgets.QPushButton('👁  Alpha B&W preview')
        self._preview_btn.setCheckable(True)
        self._preview_btn.setFixedHeight(24)
        self._preview_btn.setStyleSheet(
            'QPushButton { background-color: #443355; color: #ccaaee; }'
            'QPushButton:hover { background-color: #554466; }'
            'QPushButton:checked { background-color: #775599; color: white; }'
        )
        self._preview_btn.setToolTip(
            'Toggle greyscale preview of the alpha channel in the viewport'
        )
        self._preview_btn.toggled.connect(self._on_toggled)
        lay.addWidget(self._preview_btn)

        self._source = None

    def on_source_changed(
        self,
        source: Optional['WeightSource'],
        active_map: str,
        ctrl: 'SlimfastController',
    ) -> None:
        """Track the active ``VertexColorAlpha`` and reset the button when
        switching away.

        Args:
            source:     New source; stored only if it is a ``VertexColorAlpha``.
            active_map: Unused.
            ctrl:       Unused.
        """
        from dw_maya.dw_paint.vertex_color_alpha import VertexColorAlpha
        is_alpha = isinstance(source, VertexColorAlpha)
        self._source = source if is_alpha else None
        if not is_alpha and self._preview_btn.isChecked():
            # Uncheck without triggering a preview toggle on a dead source.
            self._preview_btn.blockSignals(True)
            self._preview_btn.setChecked(False)
            self._preview_btn.blockSignals(False)

    @Slot(bool)
    def _on_toggled(self, checked: bool) -> None:
        if self._source is None:
            return
        if checked:
            self._source.enable_preview()
        else:
            self._source.disable_preview()

    def has_envelope(self) -> bool:
        """Return ``False`` — vertex colour alpha maps have no envelope."""
        return False

    def has_paint(self) -> bool:
        """Return ``False`` — vtxAlpha is not painted via artisan."""
        return False


# ---------------------------------------------------------------------------
# Built-in registrations (executed at import time)
# ---------------------------------------------------------------------------

register_deformer_panel(
    mode_key='all',
    label='All',
    panel_class=DefaultPanel,
    ctrl_mode='all',
    node_types=[],
    order=0,
)

register_deformer_panel(
    mode_key='deformer',
    label='Deformer',
    panel_class=DefaultPanel,
    ctrl_mode='deformer',
    node_types=['cluster', 'softMod', 'wire', 'skinCluster'],
    order=10,
)

register_deformer_panel(
    mode_key='blendShape',
    label='BlendShape',
    panel_class=BlendShapePanel,
    ctrl_mode='deformer',
    node_types=['blendShape'],
    order=20,
)

register_deformer_panel(
    mode_key='nucleus',
    label='nCloth',
    panel_class=NucleusPanel,
    ctrl_mode='nucleus',
    node_types=['nCloth', 'nRigid'],
    order=30,
)

register_deformer_panel(
    mode_key='vtxColor',
    label='vtxAlpha',
    panel_class=VtxAlphaPanel,
    ctrl_mode='vtxColor',
    node_types=['VertexColorAlpha'],
    order=40,
)

