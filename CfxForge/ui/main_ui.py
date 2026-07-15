"""CfxForge recipe editor - main window (first UI pass).

Summary:
    Node-graph editor over the dw_recipe json document. The Recipe object
    is the single source of truth: the graph scene and the param panel
    request edits, this window applies them and reloads the views. Node
    positions persist inside each entry under a ``ui`` key the executor
    ignores. Validate runs the structural check; Dry Run goes through the
    real executor (inside Maya the maya_ops backends resolve too).

    PySide6-only by decision - no PySide2 fallback.

Example:
    python CfxForge/ui/main_ui.py [recipe.json]

Author:
    DrWeeny
"""

import functools
import os
import sys

if __package__ in (None, ''):
    # ran as a script: make the repo root importable
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from PySide6 import QtWidgets, QtCore, QtGui

import CfxForge
from CfxForge.recipe import Recipe
from CfxForge.taxonomy import OP_TYPES
from CfxForge.ui import file_probe
from CfxForge.ui.wgt_node_graph import NodeGraphWidget
from CfxForge.ui.wgt_op_palette import OpPaletteWidget
from CfxForge.ui.wgt_param_editor import ParamEditorWidget


class RecipeEditorWindow(QtWidgets.QMainWindow):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('CfxForge Recipe Editor')
        self.resize(1280, 760)
        self.recipe = Recipe(name='untitled')
        self.path = None

        op_types = sorted(set(OP_TYPES) | set(CfxForge.list_op_types()))

        self.graph = NodeGraphWidget(op_types, self)
        self.setCentralWidget(self.graph)

        self.palette_widget = OpPaletteWidget(self)
        dock = QtWidgets.QDockWidget('Ops', self)
        dock.setObjectName('ops_dock')
        dock.setWidget(self.palette_widget)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, dock)

        self.params = ParamEditorWidget(op_types, self)
        dock = QtWidgets.QDockWidget('Node', self)
        dock.setObjectName('node_dock')
        dock.setWidget(self.params)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self.report = QtWidgets.QPlainTextEdit(self)
        self.report.setReadOnly(True)
        self.report.setFont(QtGui.QFont('Consolas', 9))
        dock = QtWidgets.QDockWidget('Report', self)
        dock.setObjectName('report_dock')
        dock.setWidget(self.report)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, dock)

        self._build_toolbar(op_types)

        self.graph.scene.node_selected.connect(self._on_node_selected)
        self.graph.scene.connection_requested.connect(self._on_connect)
        self.graph.scene.edge_delete_requested.connect(self._on_edge_delete)
        self.graph.scene.nodes_delete_requested.connect(self._on_nodes_delete)
        self.graph.scene.create_requested.connect(self._on_create_at)
        self.palette_widget.create_requested.connect(self._create_node)
        self.params.apply_requested.connect(self._on_apply)

    # ------------------------------------------------------------------
    # toolbar / file handling
    # ------------------------------------------------------------------
    def _build_toolbar(self, op_types):
        bar = self.addToolBar('main')
        bar.setObjectName('main_toolbar')
        bar.setMovable(False)
        bar.addAction('New', self.new_recipe)
        bar.addAction('Open', self.open_recipe)
        bar.addAction('Save', self.save_recipe)
        bar.addSeparator()
        bar.addAction('Layout', self.auto_layout)
        bar.addAction('Fit (F)', self.graph.view.fit_all)
        bar.addSeparator()
        bar.addAction('Validate', self.validate)
        bar.addAction('Dry Run', self.dry_run)

    def new_recipe(self):
        self.recipe = Recipe(name='untitled')
        self.path = None
        self._reload(keep_positions=False)

    def open_recipe(self, path: str = None):
        if not path:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, 'Open recipe', '', 'Recipe (*.json)')
        if not path:
            return
        try:
            self.recipe = CfxForge.load_recipe(path)
        except Exception as e:
            self._log(f'could not open {path}:\n{e}')
            return
        self.path = path
        self._reload(keep_positions=False)
        self._log(f'opened {path} ({len(self.recipe.nodes)} nodes)')

    def save_recipe(self):
        self._commit_pending()
        if not self.path:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, 'Save recipe', self.recipe.name + '.json',
                'Recipe (*.json)')
            if not path:
                return
            self.path = path
        # persist layout inside the document; the executor ignores 'ui'
        for node_id, pos in self.graph.positions().items():
            if node_id in self.recipe.nodes:
                self.recipe.nodes[node_id].setdefault('ui', {})['pos'] = \
                    [round(pos[0], 1), round(pos[1], 1)]
        CfxForge.save_recipe(self.recipe, self.path)
        self._log(f'saved {self.path}')
        self._refresh_title()

    # ------------------------------------------------------------------
    # graph edits (requested by the views, applied on the Recipe)
    # ------------------------------------------------------------------
    def _create_node(self, op_type: str, pos=None):
        index = 1
        node_id = op_type
        while node_id in self.recipe.nodes:
            index += 1
            node_id = f'{op_type}{index}'
        self.recipe.add_node(node_id, op_type)
        positions = self.graph.positions()
        if pos is None:
            center = self.graph.view.mapToScene(
                self.graph.view.rect().center())
            pos = (center.x(), center.y())
        positions[node_id] = pos
        self._reload(positions=positions, select=node_id)
        self._log(f"added '{node_id}' ({op_type})")
        return node_id

    def _on_create_at(self, op_type: str, x: float, y: float):
        self._create_node(op_type, (x, y))

    def _on_connect(self, src_ref, dst_id, port):
        self._commit_pending()
        self.recipe.nodes[dst_id].setdefault('inputs', {})[port] = src_ref
        self._reload()
        self._refresh_panel()

    def _on_edge_delete(self, dst_id, port):
        self._commit_pending()
        self.recipe.nodes.get(dst_id, {}).get('inputs', {}).pop(port, None)
        self._reload()
        self._refresh_panel()

    def _refresh_panel(self):
        """Re-sync the param panel after the recipe changed under it
        (a stale panel would commit old inputs over fresh connections)."""
        current = self.params._current
        if current and current in self.recipe.nodes:
            entry = self.recipe.nodes[current]
            self.params.set_node(current, entry, self._item_options(entry))
        elif current:
            self.params.set_node(None, None)

    def _item_options(self, entry) -> list:
        """Shape names the upstream 'source' file node is known to carry
        (probe cache; a fresh .abc probe is cheap, .ma/.mb never trigger)."""
        ref = entry.get('inputs', {}).get('source', '')
        src = self.recipe.nodes.get(str(ref).split('.')[0])
        if not src or src.get('type') != 'file':
            return []
        path = str(src.get('params', {}).get('path', ''))
        if not path or not os.path.isfile(path):
            return []
        cached = os.path.isfile(file_probe.cached_probe_path(path))
        if not cached and not path.lower().endswith('.abc'):
            return []
        try:
            data = file_probe.probe(path)
        except Exception:
            return []
        return [e['path'].rsplit('/', 1)[-1]
                for e in data.get('entries', [])
                if e.get('type') != 'group']

    def _on_nodes_delete(self, node_ids):
        for node_id in node_ids:
            self.recipe.nodes.pop(node_id, None)
        for entry in self.recipe.nodes.values():
            inputs = entry.get('inputs', {})
            for port in [p for p, r in inputs.items()
                         if str(r).split('.')[0] in node_ids]:
                del inputs[port]
        self._reload()
        self.params.set_node(None, None)

    def _on_node_selected(self, node_id):
        self._commit_pending(select=node_id or None)
        if node_id and node_id in self.recipe.nodes:
            entry = self.recipe.nodes[node_id]
            self.params.set_node(node_id, entry, self._item_options(entry))
        else:
            self.params.set_node(None, None)

    def _commit_pending(self, select: str = None):
        """Persist un-applied panel edits (called before the selection
        moves and before save/validate/run)."""
        if getattr(self, '_committing', False):
            return
        payload = self.params.pending_payload()
        if payload is None:
            return
        entry = self.recipe.nodes.get(payload['old_id'])
        if entry is None:
            return
        unchanged = (payload['node_id'] == payload['old_id']
                     and payload['type'] == entry.get('type')
                     and payload['params'] == entry.get('params', {})
                     and payload['inputs'] == entry.get('inputs', {}))
        if unchanged:
            return
        self._committing = True
        try:
            # the selection change that lands here can originate from a
            # mouse event Qt is STILL delivering to a NodeItem - rebuild
            # the scene only after that event finishes, or the item dies
            # under Qt's feet (0xC0000005)
            self._apply_payload(payload, select=select, defer_reload=True)
        finally:
            self._committing = False

    def _on_apply(self, payload):
        self._apply_payload(payload, select=payload['node_id'])

    def _apply_payload(self, payload, select=None, defer_reload=False):
        old_id = payload['old_id']
        new_id = payload['node_id']
        if new_id != old_id and new_id in self.recipe.nodes:
            self._log(f"rename refused: '{new_id}' already exists")
            return
        entry = self.recipe.nodes.pop(old_id)
        entry['type'] = payload['type']
        entry['params'] = payload['params']
        entry['inputs'] = payload['inputs']
        # rebuild preserving order, entry under its (possibly new) key
        rebuilt = {}
        for node_id, other in list(self.recipe.nodes.items()):
            rebuilt[node_id] = other
        rebuilt[new_id] = entry
        if new_id != old_id:
            for other in rebuilt.values():
                inputs = other.get('inputs', {})
                for port, ref in list(inputs.items()):
                    parts = str(ref).split('.', 1)
                    if parts[0] == old_id:
                        parts[0] = new_id
                        inputs[port] = '.'.join(parts)
        self.recipe.nodes = rebuilt
        if defer_reload:
            QtCore.QTimer.singleShot(
                0, functools.partial(self._reload_after_apply,
                                     old_id, new_id, select))
        else:
            self._reload_after_apply(old_id, new_id, select)
        self._log(f"applied '{new_id}'")

    def _reload_after_apply(self, old_id, new_id, select):
        positions = self.graph.positions()
        if old_id in positions:
            positions[new_id] = positions.pop(old_id)
        self._reload(select=select or new_id, positions=positions)

    def auto_layout(self):
        self.graph.load(self.recipe.nodes, {})
        self.graph.view.fit_all()

    # ------------------------------------------------------------------
    # checks
    # ------------------------------------------------------------------
    def validate(self):
        self._commit_pending()
        errors = self.recipe.validate()
        if errors:
            self._log('validate: ' + str(len(errors)) + ' error(s)\n'
                      + '\n'.join(f'  {e}' for e in errors))
        else:
            self._log(f'validate: OK ({len(self.recipe.nodes)} nodes, '
                      f'order: {" > ".join(self.recipe.topological_order())})')

    def dry_run(self):
        self._commit_pending()
        try:
            from CfxForge import maya_ops  # noqa: F401  (inside Maya only)
        except ImportError:
            self._log('note: maya_ops backends unavailable outside Maya - '
                      'maya op types will report as unregistered\n')
        ctx = CfxForge.execute_recipe(self.recipe, dry_run=True)
        self._log('dry run:\n' + ctx.summary())

    # ------------------------------------------------------------------
    def _reload(self,
                keep_positions: bool = True,
                select: str = None,
                positions: dict = None):
        if positions is None:
            positions = self.graph.positions() if keep_positions else {}
        if not keep_positions:
            for node_id, entry in self.recipe.nodes.items():
                pos = (entry.get('ui') or {}).get('pos')
                if pos:
                    positions[node_id] = tuple(pos)
        self.graph.load(self.recipe.nodes, positions)
        if not keep_positions:
            self.graph.view.fit_all()
        if select and select in self.graph.scene.node_items:
            self.graph.scene.node_items[select].setSelected(True)
        self._refresh_title()

    def _refresh_title(self):
        label = self.path or 'untitled'
        self.setWindowTitle(f'CfxForge Recipe Editor - {label}')

    def _log(self, message: str):
        self.report.appendPlainText(message)


def _apply_dark_palette(app):
    app.setStyle('Fusion')
    palette = QtGui.QPalette()
    role = QtGui.QPalette.ColorRole
    colors = {role.Window: '#3a3a3a',
              role.WindowText: '#d8d8d8',
              role.Base: '#2b2b2b',
              role.AlternateBase: '#333333',
              role.Text: '#d8d8d8',
              role.Button: '#3f3f3f',
              role.ButtonText: '#d8d8d8',
              role.Highlight: '#5a7fa6',
              role.HighlightedText: '#f0f0f0',
              role.ToolTipBase: '#2b2b2b',
              role.ToolTipText: '#d8d8d8',
              role.PlaceholderText: '#888888'}
    for key, value in colors.items():
        palette.setColor(key, QtGui.QColor(value))
    palette.setColor(QtGui.QPalette.ColorGroup.Disabled, role.Text,
                     QtGui.QColor('#777777'))
    palette.setColor(QtGui.QPalette.ColorGroup.Disabled, role.ButtonText,
                     QtGui.QColor('#777777'))
    app.setPalette(palette)


def launch(path: str = None):
    app = QtWidgets.QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QtWidgets.QApplication(sys.argv)
        _apply_dark_palette(app)
    window = RecipeEditorWindow()
    window.show()
    if path:
        window.open_recipe(path)
    if owns_app:
        app.exec()
    return window


if __name__ == '__main__':
    launch(sys.argv[1] if len(sys.argv) > 1 else None)