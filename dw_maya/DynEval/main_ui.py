

class DynEvalUI(DynEvalMainWindow):

    def __init__(self, parent=None):
        super().__init__(parent or get_maya_window())
        self._hub = DataHub()

        self.setWindowTitle('DynEval')
        self.setGeometry(867, 546, 900, 500)

        self.central_widget = QtWidgets.QWidget(self)
        self._build_ui()
        self.setCentralWidget(self.central_widget)

        self._sync_frame_range()
        self.build_tree()

    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = QtWidgets.QHBoxLayout(self.central_widget)

        self.tree_panel   = SimTreePanel(self._hub, parent=self)
        self.detail_panel = SimDetailPanel(self._hub, parent=self)

        layout.addWidget(self.tree_panel,   stretch=1)
        layout.addWidget(self.detail_panel, stretch=2)

    def _sync_frame_range(self):
        start = int(cmds.playbackOptions(q=True, min=True))
        end   = int(cmds.playbackOptions(q=True, max=True))
        self._hub.set(DynEvalKeys.FRAME_RANGE, (start, end))

    def build_tree(self):
        self.tree_panel.build_tree()

    def refresh_tree(self):
        self.tree_panel.refresh_tree()

class SimTreePanel(DynEvalWidgetBase):
    def __init__(self, hub, parent=None):
        super().__init__(hub, parent)
        layout = QtWidgets.QVBoxLayout(self)

        self.tree = SimulationTreeView()
        self.tree.setMinimumWidth(260)
        layout.addWidget(self.tree)

        self.tree.selectionModel().selectionChanged.connect(self._on_selection)

    def _on_selection(self):
        items = self.tree.get_selected_items()
        self.publish(DynEvalKeys.SELECTED_NODE, items[0] if items else None)

    def build_tree(self):
        self.tree.clear()
        for system_name, solvers in discover_all().items():
            for solver in solvers:
                solver_item = get_system('nucleus').make_item(solver)
                self._add_children(solver_item, system_name)
                self.tree.model().invisibleRootItem().appendRow(solver_item)
        self.tree.expandAll()

    def _add_children(self, solver_item, system_name):
        # ask the solver item for its dependent nodes, build child items
        ...

    def refresh_tree(self):
        # capture expansion state, rebuild, restore
        ...

class SimDetailPanel(DynEvalWidgetBase):
    def __init__(self, hub, parent=None):
        super().__init__(hub, parent)
        layout = QtWidgets.QVBoxLayout(self)

        self.tabs = QtWidgets.QTabWidget()
        self.cache_tab = CacheVersionPanel(hub)
        self.maps_tab  = MapListPanel(hub)

        self.tabs.addTab(self.cache_tab, "Cache")
        self.tabs.addTab(self.maps_tab,  "Maps")
        layout.addWidget(self.tabs)

        # Both sub-panels subscribe to SELECTED_NODE themselves —
        # this panel doesn't proxy for them.

class CacheVersionPanel(DynEvalWidgetBase):
    def __init__(self, hub, parent=None):
        super().__init__(hub, parent)
        # build your list widget for cache versions
        self.subscribe(DynEvalKeys.SELECTED_NODE, self._on_node)
        self.subscribe(DynEvalKeys.FRAME_RANGE,   self._on_frame_range)

    def _on_node(self, old, new):
        # repopulate cache version list for `new`
        ...

    def _on_frame_range(self, old, new):
        # update frame range display
        ...


class MapListPanel(DynEvalWidgetBase):
    def __init__(self, hub, parent=None):
        super().__init__(hub, parent)
        # just a list of maps + a "Paint in Slimfast" button
        self.subscribe(DynEvalKeys.SELECTED_NODE, self._on_node)

    def _on_node(self, old, new):
        # list the maps available on this node
        ...

    def _on_paint_clicked(self):
        map_info = self.current_map()
        if map_info:
            self.publish(DynEvalKeys.PAINT_REQUESTED, map_info)
            # main window (or a dedicated listener) catches this
            # and calls slimfast.open_for(map_info)