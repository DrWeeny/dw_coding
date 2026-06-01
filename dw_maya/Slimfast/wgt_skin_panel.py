from typing import Dict, List, Optional, Type, TYPE_CHECKING

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Signal, Slot
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Signal, Slot

from dw_maya.Slimfast.wgt_deformer_panel import DeformerPanelBase

if TYPE_CHECKING:
    from dw_maya.dw_paint.protocol import WeightSource
    from dw_maya.Slimfast.cmds import SlimfastController

class SkinPanel(DeformerPanelBase):
    """Adds a greyscale-preview toggle for ``VertexColorAlpha`` sources.

    The toggle calls ``source.enable_preview()`` / ``source.disable_preview()``
    which switches the active colour set to a greyscale display mode in the
    Maya viewport.
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self._listview = QtWidgets.QListView(self)

        lay.addWidget(self._listview)

        self._source = None

    def on_source_changed(self,
                          source: Optional['WeightSource'],
                          active_map: str,
                          ctrl: 'SlimfastController',) -> None:
        """Track the active ``VertexColorAlpha`` and reset the button when
        switching away.

        Args:
            source:     New source; stored only if it is a ``VertexColorAlpha``.
            active_map: Unused.
            ctrl:       Unused.
        """
        pass

    def has_envelope(self) -> bool:
        """Return ``False`` — vertex colour alpha maps have no envelope."""
        return False

    def has_paint(self) -> bool:
        """Return ``False`` — vtxAlpha is not painted via artisan."""
        return False