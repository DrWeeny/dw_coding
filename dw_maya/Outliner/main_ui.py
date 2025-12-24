"""
This outliner was orignally designed for manipulating export data from a lod rig [cfx, rig, sculpt...etc] and tag things you want to add to exports
or remove some data form the tag, it is just here to keep the bone architecture
it is designed to have a custom parameter editor to manipulate the data in whatever mean, todo find a minimalistic way to make it an exporter
"""


from Qt import QtWidgets, QtCore, QtGui
import maya.cmds as cmds
import maya.api.OpenMaya as om

try:
    from .cmds import get_exportable_type_list
except ImportError:
    cache = None
    cache_utils = None

from dw_utils.qt_utils.wgt_toggle_slide import ToggleSlideWidget
from .model import SceneTreeModel
from dw_maya.dw_decorators import timeIt

# ============================================================================
# Constants
# ============================================================================

QSETTINGS_ORGANIZATION = "DrWeeny"
QSETTINGS_APPLICATION = "OutlinerViewer"

# ============================================================================
# Main Window
# ============================================================================

class OutlinerViewerWindow(QtWidgets.QMainWindow):
    """
    Attributes:
        episode: Current episode context
        sequence: Current sequence context
        shot: Current shot context
        asset_namespaces: List of asset namespaces in scene
    """

    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        self.setWindowTitle("cache Viewer")
        self._width = kwargs.get("width", 600)
        self._height = kwargs.get("width", 600)
        self.resize(self._height, self._width)

        # QSettings for persistent state
        self.settings = QtCore.QSettings(QSETTINGS_ORGANIZATION, QSETTINGS_APPLICATION)
        self.param_editor_visibility = False

        # Context
        self.episode = None
        self.sequence = None
        self.shot = None
        self.asset_namespaces = []

        # Flags
        self._show_only_in_cache = False
        self._filter_by_namespace = True  # Filter namespace enabled by default

        # Build UI
        self._build_menu_bar()
        self._build_ui()

        # Restore window state
        self._restore_window_state()

        # Don't auto-refresh - just show empty UI
        self.refresh()

    def _build_ui(self):
        """Build the main UI layout."""
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QtWidgets.QVBoxLayout(central_widget)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Header section
        header_layout = QtWidgets.QHBoxLayout()

        title_label = QtWidgets.QLabel("cache Setup")
        title_font = title_label.font()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # Refresh button
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.setToolTip("Reload cache setup from scene")
        header_layout.addWidget(self.refresh_btn)

        main_layout.addLayout(header_layout)

        # Bottom controls
        controls_layout = QtWidgets.QHBoxLayout()

        # Shot info section (will be populated by refresh)
        self.shot_label = QtWidgets.QLabel("Shot: Not set")
        self.shot_label.setStyleSheet("color: #888; font-size: 9pt;")
        controls_layout.addWidget(self.shot_label)

        controls_layout.addStretch()
        main_layout.addLayout(controls_layout)

        # Info label
        self.info_label = QtWidgets.QLabel("No cache operators found")
        self.info_label.setStyleSheet("color: gray; font-style: italic;")
        main_layout.addWidget(self.info_label)


        # Main 3-column splitter
        self.main_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)


        # Left column: Scene Hierarchy
        left_widget = self._build_scene_hierarchy_column()
        self.main_splitter.addWidget(left_widget)

        # # Right column: Parameter Editor (collapsible)
        # right_widget = self._build_parameter_editor_column()
        # self.main_splitter.addWidget(right_widget)

        self.main_splitter.setSizes([int(self._width*.6), int(self._width*.3), int(self._width*.1)])
        # Add splitter with stretch factor to take all remaining vertical space
        main_layout.addWidget(self.main_splitter, stretch=1)

    def _build_menu_bar(self):
        """Build the menu bar with Scene Tree menu."""
        menu_bar = self.menuBar()

        # Scene Tree menu
        scene_tree_menu = menu_bar.addMenu("Scene Tree")

        # Filter by Asset Namespace action (checkable, enabled by default)
        self.filter_namespace_action = QtWidgets.QAction("Filter by Asset Namespace", self)
        self.filter_namespace_action.setCheckable(True)
        self.filter_namespace_action.setChecked(True)
        self.filter_namespace_action.setToolTip("Show only transforms from asset namespaces in shot context")
        self.filter_namespace_action.triggered.connect(self._on_filter_namespace_toggled)
        scene_tree_menu.addAction(self.filter_namespace_action)

    def _build_scene_hierarchy_column(self):
        """Build the left column: Scene Hierarchy with add/remove buttons."""
        column_widget = QtWidgets.QWidget()
        column_layout = QtWidgets.QVBoxLayout(column_widget)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(8)

        # Column header with dark background and toggle
        header_widget = QtWidgets.QWidget()
        header_widget.setStyleSheet("background-color: #3a3a3a;")
        header_layout = QtWidgets.QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5, 5, 5, 5)
        header_layout.setSpacing(10)

        self._title_label = QtWidgets.QLabel("Minimal Scene Hierarchy")
        self._title_label.setStyleSheet("font-weight: bold; font-size: 18px; color: #e0e0e0;")
        header_layout.addWidget(self._title_label)

        header_layout.addStretch()

        # Add toggle slide widget
        self.scene_hierarchy_toggle = ToggleSlideWidget(checked=False, width=50, height=25)
        self.scene_hierarchy_toggle.setToolTip("Show only nodes in cache")
        self.scene_hierarchy_toggle.toggled.connect(self._on_show_only_toggled)
        header_layout.addWidget(self.scene_hierarchy_toggle)

        column_layout.addWidget(header_widget)

        # Tree view with buttons overlay container
        tree_container = QtWidgets.QWidget()
        tree_container_layout = QtWidgets.QVBoxLayout(tree_container)
        tree_container_layout.setContentsMargins(0, 0, 0, 0)
        tree_container_layout.setSpacing(0)

        # Scene hierarchy tree
        self.scene_tree_view = QtWidgets.QTreeView()
        self.scene_tree_view.setAlternatingRowColors(True)
        self.scene_tree_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.scene_tree_view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        tree_container_layout.addWidget(self.scene_tree_view)

        # Create and set model
        self.scene_tree_model = SceneTreeModel()
        self.scene_tree_view.setModel(self.scene_tree_model)

        # Hide the header since we don't need column labels
        self.scene_tree_view.setHeaderHidden(True)

        # Enable mouse tracking for tooltips
        self.scene_tree_view.setMouseTracking(True)
        self.scene_tree_view.viewport().setMouseTracking(True)

        tree_container_layout.addWidget(self.scene_tree_view)

        # Button container at bottom right
        button_container = QtWidgets.QWidget(tree_container)
        button_layout = QtWidgets.QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 8, 8)
        button_layout.setSpacing(4)
        button_layout.addStretch()

        # Remove button (red with minus)
        self.remove_btn = QtWidgets.QPushButton("−")
        self.remove_btn.setFixedSize(32, 32)
        self.remove_btn.setToolTip("Remove selected nodes from cache")
        self.remove_btn.setStyleSheet("""
            QPushButton {
                background-color: #d32f2f;
                border: none;
                border-radius: 16px;
                color: white;
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f44336;
            }
            QPushButton:pressed {
                background-color: #c62828;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        self.remove_btn.clicked.connect(self._on_remove_from_cache)
        button_layout.addWidget(self.remove_btn)

        # Add button (green with plus)
        self.add_btn = QtWidgets.QPushButton("+")
        self.add_btn.setFixedSize(32, 32)
        self.add_btn.setToolTip("Add selected nodes to cache")
        self.add_btn.setStyleSheet("""
            QPushButton {
                background-color: #388e3c;
                border: none;
                border-radius: 16px;
                color: white;
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4caf50;
            }
            QPushButton:pressed {
                background-color: #2e7d32;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        self.add_btn.clicked.connect(self._on_add_to_cache)
        button_layout.addWidget(self.add_btn)

        # Position button container at bottom right
        button_container.setGeometry(
            tree_container.width() - 80,
            tree_container.height() - 44,
            80,
            44
        )

        # Handle resize to keep buttons in bottom right
        def update_button_position():
            button_container.setGeometry(
                tree_container.width() - 80,
                tree_container.height() - 44,
                80,
                44
            )

        tree_container.resizeEvent = lambda e: (
            QtWidgets.QWidget.resizeEvent(tree_container, e),
            update_button_position()
        )

        column_layout.addWidget(tree_container, stretch=1)

        return column_widget

    def _build_parameter_editor_column(self):
        """Build the right column: Parameter Editor (collapsible)."""
        column_widget = QtWidgets.QWidget()
        column_layout = QtWidgets.QHBoxLayout(column_widget)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(0)

        # Vertical collapse button (placed at the left edge) - fills height
        self.collapse_btn = QtWidgets.QPushButton("◀")
        self.collapse_btn.setFixedWidth(20)
        self.collapse_btn.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)
        self.collapse_btn.setCheckable(True)
        self.collapse_btn.setToolTip("Collapse/Expand Parameter Editor")
        self.collapse_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a3a3a;
                border: none;
                color: #e0e0e0;
                font-size: 12pt;
                border-radius: 0;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
            QPushButton:checked {
                background-color: #2a2a2a;
            }
        """)
        self.collapse_btn.clicked.connect(self._on_collapse_parameter_editor)
        column_layout.addWidget(self.collapse_btn)

        # Parameter content widget (takes remaining width)
        self.parameter_content = QtWidgets.QWidget()
        self.parameter_content.setMinimumWidth(200)
        self.parameter_content.setStyleSheet("background-color: #2a2a2a;")
        parameter_layout = QtWidgets.QVBoxLayout(self.parameter_content)
        parameter_layout.setContentsMargins(8, 8, 8, 8)

        # Title label
        title_label = QtWidgets.QLabel("Parameter Editor")
        title_label.setStyleSheet(
            "font-weight: bold; "
            "font-size: 15px; "
            "padding: 5px; "
            "background-color: #3a3a3a; "
            "color: #e0e0e0;"
        )
        parameter_layout.addWidget(title_label)

        # Placeholder for future content
        parameter_layout.addStretch()

        # Add content to main layout with stretch
        column_layout.addWidget(self.parameter_content, stretch=1)

        # Start collapsed
        self.parameter_content.hide()
        self.collapse_btn.setChecked(self.param_editor_visibility)

        return column_widget

    # ========================================================================
    # Window State Management
    # ========================================================================

    def _save_window_state(self):
        """Save window geometry and splitter positions to QSettings."""
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.settings.setValue("showParam", self.parameter_content.isVisible())

        # Save splitter sizes
        splitter_sizes = self.main_splitter.sizes()
        self.settings.setValue("splitterSizes", splitter_sizes)

    def _restore_window_state(self):
        """Restore window geometry and splitter positions from QSettings."""
        try:
            # Restore geometry
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)

            # Restore window state
            window_state = self.settings.value("windowState")
            if window_state:
                self.restoreState(window_state)

            # Restore param editor visibility
            parameter_visibility = self.settings.value("showParam", defaultValue=False, type=bool)
            # Apply the restored state
            self._on_collapse_parameter_editor(not parameter_visibility)

            # Restore splitter sizes
            splitter_sizes = self.settings.value("splitterSizes")
            if splitter_sizes:
                # Convert to list of ints (QSettings may return strings)
                try:
                    sizes = [int(s) for s in splitter_sizes]
                    self.main_splitter.setSizes(sizes)
                except (ValueError, TypeError):
                    # Use default sizes if conversion fails
                    self.main_splitter.setSizes(
                        [int(self._width * 0.6), int(self._width * 0.3), int(self._width * 0.1)])
        except Exception as e:
            print(f"Error restoring window state: {e}")
            # Use default sizes
            self.main_splitter.setSizes([int(self._width * 0.6), int(self._width * 0.3), int(self._width * 0.1)])

    def closeEvent(self, event):
        """Handle window close event - save state before closing."""
        self._save_window_state()
        super().closeEvent(event)

    # ========================================================================
    # Public Methods
    # ========================================================================

    # Add refresh method:
    def refresh(self):
        """Refresh the scene hierarchy and cache tree."""
        # Get asset namespaces from scene if shot context is set
        if self.episode and self.sequence and self.shot:
            # Extract asset namespaces from scene
            root_nodes = cmds.ls(assemblies=True)
            asset_namespaces = list(set([node.split(":")[0] for node in root_nodes if ":" in node and not node.startswith(":")]))
            self.asset_namespaces = asset_namespaces
            self.scene_tree_model.set_shot_context(asset_namespaces)

        # Rebuild full tree (clears cache)
        self.scene_tree_model.rebuild(minimal_mode=False)

        # Apply minimal mode filter if toggle is unchecked
        is_full_hierarchy = self.scene_hierarchy_toggle.isChecked()
        if not is_full_hierarchy:
            self.scene_tree_model.set_minimal_mode(True)

        # Expand top-level nodes
        for i in range(self.scene_tree_model.rowCount()):
            index = self.scene_tree_model.index(i, 0, QtCore.QModelIndex())
            self.scene_tree_view.expand(index)

        print(f"Scene hierarchy refreshed ({len(self.asset_namespaces)} asset(s))")

    def set_shot_context(self, episode, sequence, shot):
        """
        Set the current shot context for add operations.

        Args:
            episode: Episode name
            sequence: Sequence name
            shot: Shot name
        """
        self.episode = episode
        self.sequence = sequence
        self.shot = shot

        self.shot_label.setText(f"Shot: {episode}/{sequence}/{shot}")
        self.shot_label.setStyleSheet("color: #4CAF50; font-size: 9pt; font-weight: bold;")


    # ========================================================================
    # Event Handlers
    # ========================================================================

    def _on_filter_namespace_toggled(self, checked):
        """
        Handle 'Filter by Asset Namespace' menu action.

        Args:
            checked: Whether the filter is enabled
        """
        self._filter_by_namespace = checked

        # Update info label
        if checked and self.asset_namespaces:
            self.info_label.setText(f"Filtering by {len(self.asset_namespaces)} asset namespace(s)")
            self.info_label.setStyleSheet("color: #4CAF50; font-style: italic;")
        else:
            self.info_label.setText("Showing all scene transforms")
            self.info_label.setStyleSheet("color: #888; font-style: italic;")

    def _on_show_only_toggled(self, checked):
        """Handle 'Show Only In cache' toggle."""
        if checked:
            self._title_label.setText("Full Scene Hierarchy")
        else:
            self._title_label.setText("Minimal Scene Hierarchy")

        # Toggle minimal mode on model (uses cached tree for performance)
        self.scene_tree_model.set_minimal_mode(not checked)

        # Re-expand top-level nodes after filtering
        for i in range(self.scene_tree_model.rowCount()):
            index = self.scene_tree_model.index(i, 0, QtCore.QModelIndex())
            self.scene_tree_view.expand(index)

    def _on_add_to_cache(self):
        """Handle [+] Add to cache button."""
        pass

    def _on_remove_from_cache(self):
        """Handle [-] Remove from cache button."""
        pass

    def _on_collapse_parameter_editor(self, checked):
        """Handle Parameter Editor collapse/expand."""
        self.param_editor_visibility = checked
        # Update button state
        self.collapse_btn.setChecked(checked)
        if checked:
            # Collapsed state
            self.collapse_btn.setText("◀")
            self.parameter_content.hide()
        else:
            # Expanded state
            self.collapse_btn.setText("▶")
            self.parameter_content.show()


# ============================================================================
# Convenience Functions
# ============================================================================

_viewer_instance = None

def get_maya_main_window():
    """
    Get Maya main window as QWidget.

    Returns:
        QtWidgets.QWidget: Maya main window instance.
    """
    from maya import OpenMayaUI as omui
    from shiboken6 import wrapInstance
    main_window_ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(main_window_ptr), QtWidgets.QWidget)

def show(episode="", sequence="", shot=""):
    """
    This Outliner tools was created to inspect exported data in rig lod
    """
    global _viewer_instance
    maya_win = get_maya_main_window()

    if _viewer_instance is None:
        _viewer_instance = OutlinerViewerWindow(maya_win)
    _viewer_instance.set_shot_context(episode, sequence, shot)

    _viewer_instance.show()

    return _viewer_instance


def close():
    """Close the cache Viewer window."""
    global _viewer_instance

    if _viewer_instance:
        _viewer_instance.close()
        _viewer_instance = None

if __name__ == '__main__':
    show()

