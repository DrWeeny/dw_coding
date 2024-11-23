from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Set
from PySide6 import QtWidgets, QtGui, QtCore
import maya.cmds as cmds
import maya.utils as mu
from shiboken6 import wrapInstance
import maya.OpenMayaUI as omui
import shutil
import mmap

from dw_maya.dw_presets_io import dw_preset, dw_json, dw_folder
from dw_logger import get_logger
from .sim_cmds import ziva_cmds, cache_management, vtx_map_management, info_management
from .dendrology.nucleus_leaf import (
    CharacterTreeItem, NucleusStandardItem, ClothTreeItem,
    HairTreeItem, NRigidTreeItem
)
from .dendrology.ziva_leaf import ZSolverTreeItem, FasciaTreeItem, SkinTreeItem
from .sim_widget import (
    StateManager, SimulationTreeView, PresetManager,
    CacheTreeWidget, MapTreeWidget, PresetWidget,
    CommentEditor,
    CacheInfo, MapInfo, PresetInfo, CacheType, PresetType, MapType
)

logger = get_logger()

# ====================================================================
# WINDOW GETTER
# ====================================================================

def get_maya_window():
    """
    Get the Maya main window as a QWidget pointer.
    Returns:
        QWidget: The main Maya window.
    """
    return wrapInstance(int(omui.MQtUtil.mainWindow()), QtWidgets.QWidget)


def get_all_treeitems(model, item_type=None):
    """
    Generator that yields items in the tree, optionally filtered by item type.

    Args:
        model (QtGui.QStandardItemModel): The model containing the tree.
        item_type (str, optional): The type of items to yield (e.g., "nCloth").

    Yields:
        QtGui.QStandardItem: Each matching item in the tree.
    """
    def recurse(parent_item):
        for row in range(parent_item.rowCount()):
            child_item = parent_item.child(row)
            if item_type is None or child_item.node_type == item_type:
                yield child_item
            yield from recurse(child_item)

    root_item = model.invisibleRootItem()
    yield from recurse(root_item)

@dataclass
class UIState:
    """Contains UI state information."""
    save_preset: bool = True
    mouse_over: bool = False
    current_node: Optional[str] = None

class DynEvalUI(QtWidgets.QMainWindow):

    """
    The Sim UI embed a unified way to simulate different type of solvers
    """
    save_preset = True

    def __init__(self, parent=None):
        super().__init__(parent)

        # Core managers
        # self.state_manager = StateManager()
        self.preset_manager = PresetManager()

        # UI Setup
        self.setGeometry(867, 546, 1200, 600)  # Wider to accommodate new features
        self.setWindowTitle('Dynamic Systems Manager')

        # Track if mouse is over the window
        # self.setMouseTracking(True)
        # self._mouse_over = False

        # Setup central widget and layout
        self.central_widget = QtWidgets.QWidget(self)
        self._setup_ui()
        self.setCentralWidget(self.central_widget)

        # self._setup_shortcuts()
        self.build_tree()

        # Connect signals
        self._connect_signals()

    def _setup_ui(self):
        """Initialize the main UI layout."""

        main_layout = QtWidgets.QHBoxLayout()

        # ====================================================================
        # LEFT PANEL
        # ====================================================================
        left_panel = QtWidgets.QVBoxLayout()

        # Set up the main tree model
        tree_widget = QtWidgets.QWidget()
        tree_layout = QtWidgets.QVBoxLayout()
        self.dyn_eval_tree = SimulationTreeView()
        tree_layout.addWidget(self.dyn_eval_tree)  # Add only once
        tree_widget.setLayout(tree_layout)
        tree_widget.setMinimumHeight(300)
        tree_widget.setMinimumWidth(280)

        left_panel.addWidget(tree_widget)

        # Create a contextual menu
        # self.dyn_eval_tree.installEventFilter(self)
        # self.dyn_eval_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        # self.dyn_eval_tree.customContextMenuRequested.connect(self._show_tree_context_menu)

        # Add status label beneath tree
        self.status_label = QtWidgets.QLabel()
        self.status_label.setAlignment(QtCore.Qt.AlignLeft)
        self.status_label.hide()

        # # Add loading indicator
        self.loading_movie = QtGui.QMovie(".icons/loading.gif")
        self.loading_movie.setScaledSize(QtCore.QSize(25, 25))  # Scale to 16x16 pixels
        self.loading_label = QtWidgets.QLabel()
        self.loading_label.setFixedSize(16, 200)
        self.loading_label.setMovie(self.loading_movie)
        self.loading_label.hide()

        status_widget = QtWidgets.QWidget()
        status_wrapper = QtWidgets.QHBoxLayout()
        status_wrapper.addWidget(self.loading_label)
        status_wrapper.addWidget(self.status_label, stretch=1)
        status_widget.setMaximumHeight(25)
        status_widget.setLayout(status_wrapper)

        left_panel.addWidget(status_widget)
        main_layout.addLayout(left_panel)

        # ====================================================================
        # MIDDLE PANEL
        # ====================================================================
        middle_panel = QtWidgets.QVBoxLayout()
        # Set up the cache and maps area
        self.mode_selector = QtWidgets.QComboBox()
        # todo : deformer list
        self.mode_selector.addItems(["Cache", "Maps", "Presets"])
        middle_panel.addWidget(self.mode_selector)

        # Stacked widget for different views
        self.stack_widget = QtWidgets.QStackedWidget()

        # Cache view
        self.cache_tree = CacheTreeWidget()
        self.stack_widget.addWidget(self.cache_tree)

        # Maps view
        self.maps_tree = MapTreeWidget()
        self.stack_widget.addWidget(self.maps_tree)

        # Preset view
        self.preset_widget = PresetWidget()
        self.stack_widget.addWidget(self.preset_widget)
        middle_panel.addWidget(self.stack_widget)
        main_layout.addLayout(middle_panel)

        # ====================================================================
        # RIGHT PANEL
        # ====================================================================
        self.details_panel = QtWidgets.QTabWidget()
        self.details_panel.setMinimumWidth(300)

        # Comments tab
        self.comments_tab = CommentEditor()
        self.details_panel.addTab(self.comments_tab, "Comments")

        # Info tab (for showing node/cache/map details)
        self.info_tab = QtWidgets.QTextEdit()
        self.info_tab.setReadOnly(True)
        self.details_panel.addTab(self.info_tab, "Info")

        main_layout.addWidget(self.details_panel)
        self.central_widget.setLayout(main_layout)


    # ====================================================================
    # TREE BUILDING METHODS
    # ====================================================================
    def build_tree(self):
        """Build the complete simulation hierarchy tree."""
        try:
            self.dyn_eval_tree.clear()

            # Get data (safely in main thread)
            # nucleus_data = mu.executeInMainThreadWithResult(self._get_nucleus_data)
            nucleus_data = self._get_nucleus_data()

            # Build trees
            if nucleus_data:
                self._build_nucleus_tree(nucleus_data)

            # Expand items
            for i in range(self.dyn_eval_tree.model().rowCount()):
                index = self.dyn_eval_tree.model().index(i, 0)
                self.dyn_eval_tree.expand(index)

        except Exception as e:
            logger.error(f"Failed to build tree: {e}")

    def _build_nucleus_tree(self, system_hierarchy: Dict[str, Any]):
        """Build nucleus system hierarchy with improved organization.

        Args:
            system_hierarchy: Dictionary of nucleus systems
        """
        try:
            for character, solvers in system_hierarchy.items():
                # Create character group
                # char_item = CharacterTreeItem(character)

                # Sort and add solvers
                sorted_solvers = info_management.sort_list_by_outliner(list(solvers.keys()))
                for solver in sorted_solvers:
                    # Create solver item
                    solver_item = NucleusStandardItem(solver)
                    state_item = QtGui.QStandardItem()
                    state_item.setEditable(False)
                    state_item.setData(solver_item.state, QtCore.Qt.UserRole + 3)

                    # Add row with both columns
                    row = [solver_item, state_item]

                    # Add dynamic elements to solver
                    elements = system_hierarchy[character][solver]
                    if any(elements.get(key) for key in ['nCloth', 'hairSystem', 'nRigid']):
                        self._add_dynamic_elements(elements, solver_item)

                    # Add to root - DON'T append to itself
                    self.dyn_eval_tree.model().invisibleRootItem().appendRow(row)

        except Exception as e:
            logger.error(f"Failed to build nucleus tree: {e}")

    def _add_dynamic_elements(self, elements: Dict[str, List[str]], parent_item: QtGui.QStandardItem):
        """Add dynamic elements to parent item with proper organization.

        Args:
            elements: Dictionary of element types and their nodes
            parent_item: Parent item to add elements to
        """
        # Define element types and their corresponding item classes
        element_types = [
            ('nCloth', ClothTreeItem),
            ('hairSystem', HairTreeItem),
            ('nRigid', NRigidTreeItem)
        ]

        for element_type, item_class in element_types:
            nodes = elements.get(element_type, [])
            if nodes:
                self._add_ordered_items(nodes, item_class, parent_item)

    def _add_ordered_items(self, nodes: List[str], item_class: type, parent_item: QtGui.QStandardItem):
        """Add items in proper outliner order with error handling.

        Args:
            nodes: List of node names to add
            item_class: Class to use for creating items
            parent_item: Parent item to add to
        """
        try:
            sorted_nodes = info_management.sort_list_by_outliner(nodes)
            for node in sorted_nodes:
                try:
                    item = item_class(node)
                    state_item = QtGui.QStandardItem()
                    state_item.setData(item.state, QtCore.Qt.UserRole + 3)
                    state_item.setEditable(False)

                    row = [item, state_item]
                    parent_item.appendRow(row)
                except Exception as e:
                    logger.warning(f"Failed to create item for {node}: {e}")

        except Exception as e:
            logger.error(f"Failed to add ordered items: {e}")

    def _get_nucleus_data(self) -> Dict[str, Any]:
        """Gather nucleus system data safely."""
        try:
            return info_management.dw_get_hierarchy()
        except Exception as e:
            logger.error(f"Failed to get nucleus data: {e}")
            return {}
    # ====================================================================
    # CONNECT SIGNALS
    # ====================================================================
    def _connect_signals(self):
        """Connect all UI signals."""
        # Connect to double-click signal
        self.dyn_eval_tree.itemDoubleClicked.connect(self.handle_item_double_click)
        # Try both approaches:
        # 1. For single click handling
        self.dyn_eval_tree.clicked.connect(self.handle_item_clicked)

        # 2. For multi-selection handling
        self.dyn_eval_tree.selectionModel().selectionChanged.connect(
            lambda selected, deselected: self.handle_selection_changed(
                self.dyn_eval_tree.get_selected_items()
            )
        )


    def handle_item_double_click(self, item):
        """Handle double-click on tree item."""
        cmds.select(item.mesh_)
        # Your double-click handling code here

    def handle_item_clicked(self, item):
        """Handle single click on tree item."""
        print(f"Clicked: {item.node}")
        # Your click handling code here

    def handle_selection_changed(self, selected_items):
        """Handle selection changes."""
        print(f"Selection changed - selected items: {[item.node for item in selected_items]}")
        # Your selection change handling code here

    def _show_tree_context_menu(self):
        pass

    def refresh_tree(self):
        pass

    # def _setup_shortcuts(self):
    #     """Setup keyboard shortcuts."""
    #     # Create shortcuts
    #     self.undo_shortcut = QtGui.QShortcut(QtGui.QKeySequence.Undo, self)
    #     self.redo_shortcut = QtGui.QShortcut(QtGui.QKeySequence.Redo, self)
    #
    #     # Connect signals
    #     self.undo_shortcut.activated.connect(self._handle_undo)
    #     self.redo_shortcut.activated.connect(self._handle_redo)
    #
    #     # Initial state
    #     self._update_shortcuts_state(False)
    #
    # def _handle_undo(self):
    #     """Handle undo operation."""
    #     cmds.undo()
    #     self.refresh_tree()
    #
    # def _handle_redo(self):
    #     """Handle redo operation."""
    #     cmds.redo()
    #     self.refresh_tree()
    #
    # def enterEvent(self, event):
    #     """Handle mouse entering window."""
    #     super().enterEvent(event)
    #     self._mouse_over = True
    #     self._update_shortcuts_state(True)
    #
    # def leaveEvent(self, event):
    #     """Handle mouse leaving window."""
    #     super().leaveEvent(event)
    #     self._mouse_over = False
    #     self._update_shortcuts_state(False)
    #
    # def _update_shortcuts_state(self, enabled: bool):
    #     """Update shortcut states based on mouse position."""
    #     if enabled:
    #         self.undo_shortcut.setKey(QtGui.QKeySequence.Undo)
    #         self.redo_shortcut.setKey(QtGui.QKeySequence.Redo)
    #     else:
    #         self.undo_shortcut.setKey(QtGui.QKeySequence())
    #         self.redo_shortcut.setKey(QtGui.QKeySequence())
