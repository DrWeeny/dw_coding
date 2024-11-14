#!/usr/bin/env python
#----------------------------------------------------------------------------#
#------------------------------------------------------------------ HEADER --#

"""
@author:
    abtidona

@description:
    this is a description

@applications:
    - groom
    - cfx
    - fur
"""

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#

# built-in
import sys, os, re

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

# internal
from maya import cmds, mel
import maya.OpenMayaUI as omui
import dw_maya.dw_maya_utils as dwu
import dw_maya.dw_maya_nodes as dwnn
from dw_maya.dw_decorators import singleUndoChunk
from PySide6 import QtWidgets, QtGui, QtCore
from shiboken6 import wrapInstance

# Cache variable
_maya_main_window = None

def get_maya_window():
    global _maya_main_window
    if _maya_main_window is None:
        # Only retrieve and store the main window once
        ptr = omui.MQtUtil.mainWindow()
        _maya_main_window = wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)
    return _maya_main_window

class ButtonStorage(QtWidgets.QPushButton):
    """
    A button widget that manages a set of selected items, updating its display and color
    based on the selection count.
    """
    # Define color and label constants
    COLOR_RED = 'rgb(230, 50, 88)'
    COLOR_GREEN = 'rgb(24, 219, 60)'
    COLOR_BLACK = 'rgb(0,0,0)'
    COLOR_WHITE = 'rgb(255, 255, 255)'
    COLOR_GREY = 'rgb(80, 80, 80)'
    LABEL_TEMPLATE = '{} curves selected'

    def __init__(self, parent=None):
        super().__init__(parent)
        self._storage = set()  # Use a set to ensure unique items
        self.setFixedHeight(120)  # Adjust the height as necessary

        self.installEventFilter(self)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_menu)

        self.clicked.connect(self.select)

        self.update_button()  # Initialize button display


    @property
    def storage(self) -> list:
        """Get the current storage as a list."""
        return list(self._storage)

    @storage.setter
    def storage(self, items):
        """Set the storage with a new set of items and update the button."""
        self._storage = set(items)
        self.update_button()

    def update_button(self):
        """Update button text and color based on the number of stored items."""
        count = len(self._storage)
        self.setText(self.LABEL_TEMPLATE.format(count))

        # Update button color based on whether there are selected items
        background_color = self.COLOR_GREEN if count > 0 else self.COLOR_RED
        text_color = self.COLOR_BLACK if count > 0 else self.COLOR_WHITE
        self.setStyleSheet(f"QPushButton {{background-color: {background_color}; color: {text_color};}}")

    def select_storage(self):
        """Select items stored in the button's storage."""
        if self._storage:
            cmds.select(self._storage)

    def _filter(self, sel: list, ntype=('shape',)) -> list:
        """
        Filter selected Maya items based on type.

        Args:
            sel (list): List of selected item names.
            ntype (tuple): Types to filter by (e.g., ('shape',)).

        Returns:
            list: Filtered list of items matching the specified types.
        """
        return cmds.ls(sel, type=ntype)

    def add(self):
        """Add the current Maya selection to storage and update button."""
        sel = self._filter(cmds.ls(sl=True))
        if sel:
            self.storage = self.storage + sel  # Update through property to trigger UI update

    def remove(self):
        """Remove the current Maya selection from storage and update button."""
        sel = self._filter(cmds.ls(sl=True))
        if sel:
            self.storage = list(self._storage - set(sel))  # Update through property

    def clear(self):
        """Clear all items from storage and update button."""
        self.storage = []

    def context_menu(self):
        """Create and display a context menu for managing storage."""
        menu = QtWidgets.QMenu(self)
        actions = [
            ("Add Selected", self.add),
            ("Remove Selected", self.remove),
            ("Clear Selection", self.clear)
        ]
        for text, handler in actions:
            action = QtWidgets.QAction(text, self)
            action.triggered.connect(handler)
            menu.addAction(action)
        menu.exec(QtGui.QCursor.pos())  # Show the menu at the cursor position


class ButtonAnimwires(ButtonStorage):
    """
    Specialized button for handling 'animWire' curve selection and storage.
    Extends ButtonStorage with additional menu actions and filtering specific to animWire curves.
    """

    def __init__(self):
        super().__init__()
        self.setToolTip("Left Click - Select Curves stored\nRight Click - use the menu to store curves")

        # Add custom menu action for selecting processed curves
        select_processed_action = QtWidgets.QAction('Select Already Processed Curves', self)
        select_processed_action.triggered.connect(self.select_curves_processed)
        self.menu.addAction(select_processed_action)

    def _filter(self, sel: list, ntype=('nurbsCurve',)) -> list:
        """
        Filters selected items to include only nurbsCurve types with specific naming patterns.

        Args:
            sel (list): List of selected Maya objects.
            ntype (tuple): Type filter, defaults to 'nurbsCurve'.

        Returns:
            list: Filtered list of animWire curve names that match specified patterns.
        """
        animwire_pattern = re.compile(r'\|\w+:animWires\|')

        # Get all curves matching the specified types
        curve_list = dwu.lsTr(sel, dag=True, type=ntype)

        # Filter to include only those ending with '_CRV'
        filtered_curves = [c for c in curve_list if c.endswith('_CRV')]

        # Use long names and filter for animWire pattern
        full_names = cmds.ls(filtered_curves, long=True)
        animwire_curves = [name for name, full_name in zip(filtered_curves, full_names) if
                           animwire_pattern.search(full_name)]

        return animwire_curves


class AnimWireSmooth(QtWidgets.QMainWindow):

    def __init__(self, parent=get_maya_window()):
        super(AnimWireSmooth, self).__init__(parent)
        self.setWindowTitle("Span Smooth for Anim Wires")

        self.initUI()

    def initUI(self):

        central_widget = QtWidgets.QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout()

        main_layout.addWidget(self._create_button_animwires())
        main_layout.addWidget(self._create_separator())
        main_layout.addLayout(self._create_slider_layout())
        main_layout.addWidget(self._create_separator())
        main_layout.addWidget(self._create_exec_button())


        central_widget.setLayout(main_layout)

    def _create_button_animwires(self):
        self.btn_anmw = ButtonAnimwires()
        self.btn_anmw.setFixedHeight(120)
        return self.btn_anmw

    def _create_separator(self):
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        return separator

    def _create_slider_layout(self):
        slider_layout = QtWidgets.QHBoxLayout()

        self.lb_iter = QtWidgets.QLabel('3')
        font = QtGui.QFont()
        font.setBold(True)
        font.setPointSize(12)
        self.lb_iter.setFont(font)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setMinimum(1)
        self.slider.setMaximum(10)
        self.slider.setValue(3)
        self.slider.setTickPosition(QtWidgets.QSlider.TicksBelow)

        self.ckb_live = QtWidgets.QCheckBox()
        lb_live = QtWidgets.QLabel('live')

        self.slider.valueChanged.connect(self.update_slider_label)
        self.slider.sliderReleased.connect(self.apply_live_setting)

        slider_layout.addWidget(self.lb_iter)
        slider_layout.addWidget(self.slider)
        slider_layout.addWidget(self.ckb_live)
        slider_layout.addWidget(lb_live)

        return slider_layout

    def _create_exec_button(self):
        btn_exec = QtWidgets.QPushButton("Smooth Curves' Spans!")
        btn_exec.clicked.connect(self.smooth_curves)
        return btn_exec

    @property
    def curves(self):
        return self.btn_anmw.storage

    @property
    def smooth(self):
        return self.slider.value()

    def update_slider_label(self):
        self.lb_iter.setText(str(self.smooth))

    def apply_live_setting(self):
        if self.ckb_live.isChecked():
            crvs_attr = get_conform_reduce_attr_from_sel()
            if crvs_attr:
                for attr in crvs_attr:
                    cmds.setAttr(attr, self.smooth)

    def smooth_curves(self):
        smooth_rebuild_animwires(self.curves, self.smooth, do_stack=False)


@singleUndoChunk
def smooth_rebuild_animwires(crvs=None, span_smooth=3, do_stack=True):
    """
    Smooths and rebuilds spans on animWire curves, creating two rebuild nodes
    for reducing and conforming spans.
    """

    pattern_smooth = re.compile(r"span_count_smooth(\d+)")

    if crvs is None:
        anm_wires = cmds.ls('*:animWires')
        crv_list = dwu.lsTr(anm_wires, dag=True, type='nurbsCurve')
        crvs_nodes = [dwnn.MayaNode(c) for c in crv_list if c.endswith('_CRV')]
    else:
        crvs_nodes = [dwnn.MayaNode(c) for c in crvs]

    for node in crvs_nodes:
        if 'span_count_orig' in node.listAttr() and not do_stack:
            continue


        degree, spans = node.degree.get(), node.spans.get()

        # Create rebuild nodes
        rb_reduce = cmds.rebuildCurve(node.tr, rt=0, d=degree, s=span_smooth, ch=True, name=f'rb_reduce_{node.tr.split(":")[-1]}')
        rb_conform = cmds.rebuildCurve(node.tr, rt=0, d=degree, s=spans, ch=True, name=f'rb_conform_{node.tr.split(":")[-1]}')

        # Get the current index for span_count_smooth attributes
        smooth_indices = [int(match.group(1)) for attr in node.listAttr() if (match := pattern_smooth.search(attr))]
        idx = max(smooth_indices) + 1 if smooth_indices else 1

        # Add attributes
        node.addAttr('span_count_orig', spans).set(lock=True)
        span_smooth_attr = node.addAttr(f'span_count_smooth{idx}', span_smooth)
        node.addAttr('reduce_count_stack', idx)

        # Link span smoothing attribute to the conform node
        conform_node = dwnn.MayaNode(rb_reduce[1])
        span_smooth_attr > conform_node.spans

def get_crv_span_smoothed():
    """Retrieve all curves with original span count attributes."""
    return [c.split('.')[0] for c in cmds.ls("*.span_count_orig", r=True)]

def select_curved_processed():
    """Select all curves that have already been processed with smoothing."""
    cmds.select(get_crv_span_smoothed())


def get_conform_reduce_attr_from_sel():
    """Retrieve span smoothing attributes for selected animWire curves."""
    processed_crvs = set(get_crv_span_smoothed())
    selected_crvs = set(dwu.lsTr(sl=True, dag=True, type='nurbsCurve'))
    to_manipulate = processed_crvs & selected_crvs

    return [f"{crv}.span_count_smooth1" for crv in to_manipulate] if to_manipulate else None


