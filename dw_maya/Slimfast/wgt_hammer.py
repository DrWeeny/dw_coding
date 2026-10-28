"""Hammer popup for Slimfast - repair a map after topology was added.

Summary:
    When an artist inserts edge loops or smooths a mesh that already carries
    a painted map, the appended vertices come in at the attribute's default
    value. This is Maya's Hammer Skin Weights generalized to every weight
    source Slimfast knows: the selected vertices are re-derived from the
    ring of unselected vertices around them.

    Two buttons, on purpose in this order:

    Select candidates
        Asks the controller which vertices look appended (exact when the
        map still stores fewer values than the mesh has vertices, inferred
        from the padded tail otherwise) and puts them in the Maya selection.
        The label says which detector fired and how much to trust it. The
        artist then adds or removes vertices in the viewport like any other
        selection - the tool proposes, it never decides.

    Hammer selection
        Fills the current vertex selection from its unselected neighbours,
        as one undo step. With only the object selected it runs the
        detection itself and hammers what it finds (and leaves it
        selected); with nothing detected it refuses.

    Non-modal, no soft lock: nothing here previews or holds state between
    clicks, both buttons read the live scene when pressed.

Classes:
    HammerDialog -- the popup.

Example::

    dlg = HammerDialog(controller, parent=main_window)
    dlg.show()

Author: DrWeeny
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

try:
    from PySide6 import QtWidgets
    from PySide6.QtCore import Slot
except ImportError:
    from PySide2 import QtWidgets
    from PySide2.QtCore import Slot

from dw_logger import get_logger

if TYPE_CHECKING:
    from dw_maya.Slimfast.cmds import SlimfastController

logger = get_logger()


class HammerDialog(QtWidgets.QDialog):
    """Non-modal 'select candidates / hammer selection' popup."""

    def __init__(self,
                 controller: 'SlimfastController',
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._ctrl = controller
        self.setWindowTitle('Hammer weights')
        self.setModal(False)
        self.setMinimumWidth(340)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        intro = QtWidgets.QLabel(
            'Repairs the active map after topology was added to the mesh '
            '(edge loops, smooth): the selected vertices are overwritten with '
            'the average of their <i>unselected</i> neighbours.<br><br>'
            '1. <b>Select candidates</b> proposes the appended vertices - '
            'review the selection in the viewport.<br>'
            '2. <b>Hammer selection</b> fills whatever is selected, in one undo step.'
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._status = QtWidgets.QLabel('')
        self._status.setWordWrap(True)
        self._status.setStyleSheet('color: #9ab; padding: 4px 0;')
        layout.addWidget(self._status)

        row = QtWidgets.QHBoxLayout()
        self._select_btn = QtWidgets.QPushButton('Select candidates')
        self._select_btn.setToolTip(
            'Detect the vertices appended since the map was last written and '
            'select them. Exact when the map still stores fewer values than the '
            'mesh has vertices; otherwise inferred from the constant run at the '
            'tail of the map.'
        )
        self._hammer_btn = QtWidgets.QPushButton('Hammer selection')
        self._hammer_btn.setToolTip(
            'Overwrite the selected vertices with the mean of their unselected '
            'neighbours. Runs in passes so a smoothed region fills inward. '
            'With only the object selected, detects the candidates first.'
        )
        row.addWidget(self._select_btn)
        row.addWidget(self._hammer_btn)
        layout.addLayout(row)

        close_btn = QtWidgets.QPushButton('Close')
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn, 0)

        self._select_btn.clicked.connect(self._on_select_candidates)
        self._hammer_btn.clicked.connect(self._on_hammer)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot()
    def _on_select_candidates(self) -> None:
        report = self._ctrl.find_hammer_candidates()
        if report is None:
            self._status.setText('No active weight source.')
            return
        self._status.setText(report.describe())

    @Slot()
    def _on_hammer(self) -> None:
        report = self._ctrl.hammer()
        if not report:
            self._status.setText(
                'Nothing hammered - no vertex selection and no appended '
                'vertices detected. Select the vertices to repair.'
            )
            return
        text = f"Hammered {report['filled']} vertices in {report['passes']} pass(es)."
        if report.get('unfilled'):
            text += (f" {report['unfilled']} left untouched: no unselected "
                     f"neighbour to derive from.")
        self._status.setText(text)
