"""Extensible deformer sub-panel registry for Slimfast.

Architecture
------------
DeformerPanelBase
    Zone-based ABC.  Subclasses override ``build_header``, ``build_body``,
    ``build_footer`` to inject widgets into a pre-assembled vertical layout.
    Capabilities (envelope, paint, artisan clamp) are declared as ClassVars
    so subclasses state intent at the top of the class, not scattered across
    three one-liner methods.

@panel_for
    Decorator that combines registration + capability overrides in one place.
    Replaces the separate ``register_deformer_panel(...)`` call at the bottom
    of each panel file.

DefaultPanel
    Handles both generic deformers (cluster, softMod, wire, blendShape …).
    For blendShape nodes, a secondary target combo appears automatically via
    ``on_combo_changed``.  No separate BlendShapePanel class is needed.

NucleusPanel / VtxAlphaPanel
    Each overrides one zone factory and ``on_source_changed``.  Both are now
    ~15 lines instead of ~50.

Registry
--------
``register_deformer_panel`` and ``panel_for`` both write into two dicts:

    _MODE_REGISTRY        mode_key  → {label, panel_class, ctrl_mode, order}
    _PANEL_BY_NODE_TYPE   node_type → panel_class

``get_mode_registry``   → ordered dict for radio-button building in main_ui.py
``get_panel_class``     → panel_class from a Maya node type string
``get_ctrl_mode``       → ctrl mode string from a mode_key

Example — external panel in 20 lines
--------------------------------------
    from dw_maya.Slimfast.wgt_deformer_panel import DeformerPanelBase, panel_for

    @panel_for(
        node_types = ['wire'],
        label      = 'Wire',
        ctrl_mode  = 'deformer',
        order      = 18,
    )
    class WirePanel(DeformerPanelBase):
        def build_header(self):
            self._lbl = QtWidgets.QLabel('Wire deformer')
            return self._lbl

        def on_source_changed(self, source, active_map, ctrl):
            self._lbl.setText(source.node_name if source else '—')

Author: DrWeeny
"""

from __future__ import annotations

import collections
from typing import ClassVar, Dict, List, Optional, Type, TYPE_CHECKING

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Signal, Slot, Qt
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Signal, Slot, Qt

if TYPE_CHECKING:
    from dw_maya.dw_paint.protocol import WeightSource
    from dw_maya.Slimfast.cmds import SlimfastController


# ---------------------------------------------------------------------------
# Internal registry stores
# ---------------------------------------------------------------------------

_MODE_REGISTRY: Dict[str, dict] = collections.OrderedDict()
_PANEL_BY_NODE_TYPE: Dict[str, Type['DeformerPanelBase']] = {}


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------

def register_deformer_panel(
        mode_key:    str,
        label:       str,
        panel_class: Type['DeformerPanelBase'],
        ctrl_mode:   str = '',
        node_types:  Optional[List[str]] = None,
        order:       int = 100,) -> None:
    """Register a deformer mode radio button and its companion sub-panel.

    Args:
        mode_key:    Unique key (e.g. ``'skinCluster'``).
        label:       Radio-button text shown in the deformer group header.
        panel_class: A ``DeformerPanelBase`` subclass.
        ctrl_mode:   Mode string forwarded to ``SlimfastController.set_mode()``.
                     Defaults to ``mode_key`` when empty.
        node_types:  Maya node-type strings that trigger this panel.
        order:       Left-to-right radio-button order (lower = left).
    """
    _MODE_REGISTRY[mode_key] = {
        'label':       label,
        'panel_class': panel_class,
        'ctrl_mode':   ctrl_mode or mode_key,
        'order':       order,
    }
    for nt in (node_types or []):
        _PANEL_BY_NODE_TYPE[nt] = panel_class


def panel_for(
        node_types: List[str],
        label:      str,
        ctrl_mode:  str = 'deformer',
        order:      int = 100,
        **capabilities,):
    """Decorator: registration + capability overrides in one declaration.

    Capabilities listed as keyword args override the ``DeformerPanelBase``
    ClassVar defaults.  Missing capabilities keep the base-class default.

    Example::

        @panel_for(
            node_types        = ['skinCluster'],
            label             = 'SkinCluster',
            order             = 11,
            has_artisan_clamp = False,   # overrides _has_artisan_clamp = True
        )
        class SkinPanel(DeformerPanelBase):
            ...
    """
    _CAPABILITY_KEYS = {'has_envelope', 'has_paint', 'has_artisan_clamp'}

    def decorator(cls: Type['DeformerPanelBase']) -> Type['DeformerPanelBase']:
        # Inject ClassVar overrides only for explicitly supplied capability kwargs.
        for key in _CAPABILITY_KEYS:
            if key in capabilities:
                setattr(cls, f'_{key}', bool(capabilities[key]))

        mode_key = node_types[0] if node_types else cls.__name__.lower()
        register_deformer_panel(
            mode_key    = mode_key,
            label       = label,
            panel_class = cls,
            ctrl_mode   = ctrl_mode,
            node_types  = node_types,
            order       = order,
        )
        return cls

    return decorator


# ---------------------------------------------------------------------------
# Registry accessors
# ---------------------------------------------------------------------------

def get_mode_registry() -> Dict[str, dict]:
    """Return the mode registry sorted by ``order``."""
    return collections.OrderedDict(
        sorted(_MODE_REGISTRY.items(), key=lambda kv: kv[1]['order'])
    )


def get_panel_class(node_type: str) -> Type['DeformerPanelBase']:
    """Resolve a panel class from a Maya node type.  Falls back to DefaultPanel."""
    return _PANEL_BY_NODE_TYPE.get(node_type, DefaultPanel)


def get_ctrl_mode(mode_key: str) -> str:
    """Resolve the controller mode string for a given registry key."""
    entry = _MODE_REGISTRY.get(mode_key)
    return entry['ctrl_mode'] if entry else mode_key


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class DeformerPanelBase(QtWidgets.QWidget):
    """Zone-based ABC for Slimfast deformer sub-panels.

    The constructor assembles three named vertical zones in order::

        [header]  — badge / status / map-type indicator (optional)
        [body]    — main content: list, combo, canvas …  (optional)
        [footer]  — extra action row                     (optional)

    Only zones whose factory returns a non-None widget are added to the
    layout.  Subclasses override only the zones they need.

    Capability ClassVars
    --------------------
    Declare capabilities at the top of the subclass — no need to override
    three separate one-liner methods::

        class MyPanel(DeformerPanelBase):
            _has_envelope      = False   # hides the envelope spinbox
            _has_artisan_clamp = False   # skips clamp sync on enterEvent

    Use ``@panel_for(has_artisan_clamp=False)`` for the same effect at
    registration time without touching the class body.

    Signals
    -------
    map_selected(str)
        Emitted when the panel activates a new map attribute name.
        Connected to ``SlimfastController.select_map`` by ``main_ui.py``.
    """

    # Capability defaults — override per subclass or via @panel_for
    _has_envelope:      ClassVar[bool] = True
    _has_paint:         ClassVar[bool] = True
    _has_artisan_clamp: ClassVar[bool] = True
    _min_size: ClassVar[int] = 20
    _max_size: ClassVar[int] = 20

    map_selected = Signal(str)

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        for widget in filter(None, [
            self.build_header(),
            self.build_body(),
            self.build_footer(),
        ]):
            lay.addWidget(widget)
    # ------------------------------------------------------------------
    # Zone factories — override in subclasses
    # ------------------------------------------------------------------

    def build_header(self) -> Optional[QtWidgets.QWidget]:
        """Return a widget for the top zone, or None to skip."""
        return None

    def build_body(self) -> Optional[QtWidgets.QWidget]:
        """Return a widget for the main content zone, or None to skip."""
        return None

    def build_footer(self) -> Optional[QtWidgets.QWidget]:
        """Return a widget for the bottom zone, or None to skip."""
        return None

    # ------------------------------------------------------------------
    # Lifecycle hooks — override in subclasses
    # ------------------------------------------------------------------

    def on_source_changed(self,
                          source: Optional['WeightSource'],
                          active_map: str,
                          ctrl: 'SlimfastController') -> None:
        """React to the active WeightSource changing.

        Called by ``SlimfastWidget._on_active_changed`` after the controller
        has updated.  Override to refresh badges, lists, etc.
        """

    def on_combo_changed(self, node_type: str, maps: List[str]) -> None:
        """React to a different source-combo row being selected.

        Called by ``SlimfastWidget._on_source_combo_changed`` *before*
        ``on_source_changed`` fires for the new source.  Override to
        pre-populate secondary widgets (target list, map picker …).
        """

    # ------------------------------------------------------------------
    # Capability accessors — read by main_ui.py; do not override manually
    # when using @panel_for or ClassVar declarations
    # ------------------------------------------------------------------

    def has_envelope(self)      -> bool: return self._has_envelope
    def has_paint(self)         -> bool: return self._has_paint
    def has_artisan_clamp(self) -> bool: return self._has_artisan_clamp


# ---------------------------------------------------------------------------
# DefaultPanel
# ---------------------------------------------------------------------------

class DefaultPanel(DeformerPanelBase):
    """Generic panel for cluster, softMod, wire, and blendShape.

    For blendShape sources the secondary target combo appears automatically
    when ``on_combo_changed`` is called with ``node_type='blendShape'``.
    For all other deformer types the combo stays hidden — no separate
    BlendShapePanel class is needed.
    """

    def build_body(self) -> Optional[QtWidgets.QWidget]:
        """Build the hidden-by-default blendShape target combo."""
        container = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._bs_combo = QtWidgets.QComboBox()
        self._bs_combo.setMinimumWidth(220)
        self._bs_combo.setToolTip('BlendShape target map')
        self._bs_combo.setVisible(False)
        self._bs_combo.currentIndexChanged.connect(self._on_bs_target_changed)
        lay.addWidget(self._bs_combo)

        return container

    def on_combo_changed(self, node_type: str, maps: List[str]) -> None:
        """Show/populate the blendShape combo; hide it for all other types."""
        is_bs = (node_type == 'blendShape')
        self._bs_combo.setVisible(is_bs)
        if not is_bs:
            return
        self._bs_combo.blockSignals(True)
        self._bs_combo.clear()
        for m in maps:
            self._bs_combo.addItem('base weights' if m == 'weightList' else m, m)
        self._bs_combo.blockSignals(False)

    @Slot(int)
    def _on_bs_target_changed(self, index: int) -> None:
        data = self._bs_combo.itemData(index)
        if data:
            self.map_selected.emit(data)


# ---------------------------------------------------------------------------
# NucleusPanel
# ---------------------------------------------------------------------------

_NUCLEUS_MAP_TYPE_INFO: Dict[int, tuple] = {
    0: ('● None  (map disabled)', '#888888'),
    1: ('● PerVertex',            '#4ecdc4'),
    2: ('● Texture',              '#ddcc44'),
}


class NucleusPanel(DeformerPanelBase):
    """Colour-coded map-type badge for nCloth / nRigid maps."""

    _has_envelope = False

    def build_header(self) -> Optional[QtWidgets.QWidget]:
        self._badge = QtWidgets.QLabel()
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setStyleSheet('font-size: 11px;')
        return self._badge

    def on_source_changed(self,
                          source: Optional['WeightSource'],
                          active_map: str,
                          ctrl: 'SlimfastController') -> None:
        from dw_maya.dw_nucleus_utils import NClothMap
        if not isinstance(source, NClothMap) or not active_map:
            self._badge.setText('')
            return
        try:
            mt = source.map_type(active_map)
            text, color = _NUCLEUS_MAP_TYPE_INFO.get(mt, (f'● type={mt}', '#aaaaaa'))
            self._badge.setText(text)
            self._badge.setStyleSheet(f'color: {color}; font-size: 11px;')
        except Exception:
            self._badge.setText('')


# ---------------------------------------------------------------------------
# VtxAlphaPanel
# ---------------------------------------------------------------------------

class VtxAlphaPanel(DeformerPanelBase):
    """Greyscale preview toggle for VertexColorAlpha sources."""

    _has_envelope      = False
    _has_paint         = False
    _has_artisan_clamp = False
    _min_size = 50
    _max_size = 50

    def build_header(self) -> Optional[QtWidgets.QWidget]:
        self._source = None
        btn = QtWidgets.QPushButton('👁  Alpha B&W preview')
        btn.setCheckable(True)
        btn.setFixedHeight(32)
        btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        btn.setStyleSheet(
            'QPushButton { background-color: #443355; color: #ccaaee; }'
            'QPushButton:hover { background-color: #554466; }'
            'QPushButton:checked { background-color: #775599; color: white; }'
        )
        btn.setToolTip('Toggle greyscale preview of the alpha channel in the viewport')
        btn.toggled.connect(self._on_toggled)
        self._preview_btn = btn
        return btn

    def on_source_changed(self,
                          source: Optional['WeightSource'],
                          active_map: str,
                          ctrl: 'SlimfastController') -> None:
        from dw_maya.dw_paint.vertex_color_alpha import VertexColorAlpha
        is_alpha = isinstance(source, VertexColorAlpha)
        self._source = source if is_alpha else None
        if not is_alpha and self._preview_btn.isChecked():
            self._preview_btn.blockSignals(True)
            self._preview_btn.setChecked(False)
            self._preview_btn.blockSignals(False)

    @Slot(bool)
    def _on_toggled(self, checked: bool) -> None:
        if self._source is None:
            return
        self._source.enable_preview() if checked else self._source.disable_preview()


# ---------------------------------------------------------------------------
# Built-in registrations
# ---------------------------------------------------------------------------
# skinCluster is intentionally absent from 'deformer' node_types so that
# wgt_skin_panel.py (when imported) can register SkinPanel for it cleanly.

register_deformer_panel(
    mode_key    = 'all',
    label       = 'All',
    panel_class = DefaultPanel,
    ctrl_mode   = 'all',
    node_types  = [],
    order       = 0,
)

register_deformer_panel(
    mode_key    = 'deformer',
    label       = 'Deformer',
    panel_class = DefaultPanel,
    ctrl_mode   = 'deformer',
    node_types  = ['cluster', 'softMod', 'wire'],   # skinCluster registered separately
    order       = 10,
)

# register_deformer_panel(
#     mode_key    = 'blendShape',
#     label       = 'BlendShape',
#     panel_class = DefaultPanel,        # DefaultPanel shows secondary combo
#     ctrl_mode   = 'deformer',
#     node_types  = ['blendShape'],
#     order       = 20,
# )

register_deformer_panel(
    mode_key    = 'nucleus',
    label       = 'nCloth',
    panel_class = NucleusPanel,
    ctrl_mode   = 'nucleus',
    node_types  = ['nCloth', 'nRigid'],
    order       = 30,
)

register_deformer_panel(
    mode_key    = 'vtxColor',
    label       = 'vtxAlpha',
    panel_class = VtxAlphaPanel,
    ctrl_mode   = 'vtxColor',
    node_types  = ['vtxColor'],
    order       = 40,
)