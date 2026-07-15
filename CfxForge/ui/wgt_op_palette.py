"""Op palette panel: browse and create recipe nodes.

Summary:
    Solver-family combobox (from taxonomy.SOLVER_OPS) filtering the op
    list, a search field, and the ops with their graph header colors.
    Double-click / Enter requests a node creation - the main window owns
    the Recipe.

Classes:
    OpPaletteWidget

Author:
    DrWeeny
"""

from PySide6 import QtWidgets, QtCore, QtGui

from CfxForge.taxonomy import OP_TYPES, SOLVER_OPS
from CfxForge.ui.wgt_node_graph import TYPE_COLORS, DEFAULT_COLOR


def _swatch(op_type: str) -> QtGui.QIcon:
    pixmap = QtGui.QPixmap(12, 12)
    pixmap.fill(QtGui.QColor(TYPE_COLORS.get(op_type, DEFAULT_COLOR)))
    return QtGui.QIcon(pixmap)


class OpPaletteWidget(QtWidgets.QWidget):

    create_requested = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.solver_combo = QtWidgets.QComboBox()
        self.solver_combo.addItem('all')
        self.solver_combo.addItems(sorted(SOLVER_OPS))
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText('search... (Tab in graph)')
        self.op_list = QtWidgets.QListWidget()

        form = QtWidgets.QFormLayout()
        form.addRow('solver', self.solver_combo)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(form)
        layout.addWidget(self.search_edit)
        layout.addWidget(self.op_list, stretch=1)

        self.solver_combo.currentTextChanged.connect(self._refresh)
        self.search_edit.textChanged.connect(self._refresh)
        self.search_edit.returnPressed.connect(self._create_first)
        self.op_list.itemDoubleClicked.connect(self._on_double_click)
        self._refresh()

    def _refresh(self, *args):
        solver = self.solver_combo.currentText()
        ops = OP_TYPES if solver == 'all' else SOLVER_OPS.get(solver, ())
        text = self.search_edit.text().strip().lower()
        self.op_list.clear()
        for op_type in ops:
            if text and text not in op_type.lower():
                continue
            item = QtWidgets.QListWidgetItem(_swatch(op_type), op_type)
            self.op_list.addItem(item)

    def _create_first(self):
        item = self.op_list.item(0)
        if item is not None:
            self.create_requested.emit(item.text())

    def _on_double_click(self, item):
        self.create_requested.emit(item.text())