"""Param editor panel: edit one recipe node entry as data.

Summary:
    Deliberately json-level for the first pass - params and inputs are
    edited as json text so every op's arbitrary nesting (attrs dicts, id
    lists) works before any per-op widget exists. Apply emits the parsed
    entry; the main window owns the Recipe mutation.

Classes:
    ParamEditorWidget

Author:
    DrWeeny
"""

import json

from PySide6 import QtWidgets, QtCore, QtGui

from CfxForge.ui.wgt_scene_tree import SceneTreeDialog


class ParamEditorWidget(QtWidgets.QWidget):

    #: payload: {'old_id', 'node_id', 'type', 'params', 'inputs'}
    apply_requested = QtCore.Signal(dict)

    def __init__(self, op_types=(), parent=None):
        super().__init__(parent)
        self._current = None

        self.id_edit = QtWidgets.QLineEdit()
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.setEditable(True)
        self.type_combo.addItems(list(op_types))

        mono = QtGui.QFont('Consolas', 9)
        self.params_edit = QtWidgets.QPlainTextEdit()
        self.params_edit.setFont(mono)
        self.inputs_edit = QtWidgets.QPlainTextEdit()
        self.inputs_edit.setFont(mono)
        self.inputs_edit.setMaximumHeight(90)

        self.error_label = QtWidgets.QLabel('')
        self.error_label.setStyleSheet('color: #d05a5a;')
        self.error_label.setWordWrap(True)

        self.apply_btn = QtWidgets.QPushButton('Apply')
        self.apply_btn.clicked.connect(self._on_apply)
        self.browse_btn = QtWidgets.QPushButton('Pick file...')
        self.browse_btn.clicked.connect(self._on_browse)
        self.type_combo.currentTextChanged.connect(self._refresh_browse)

        # group-op section: item / mode / component id chunks
        self.pattern_edit = QtWidgets.QLineEdit()
        self.pattern_edit.setPlaceholderText('wildcards, e.g. *_sim_msh')
        self.item_combo = QtWidgets.QComboBox()
        self.item_combo.setEditable(True)
        self.item_combo.lineEdit().setPlaceholderText(
            'one mesh for component groups')
        self.mode_group = QtWidgets.QButtonGroup(self)
        mode_row = QtWidgets.QHBoxLayout()
        for mode in ('object', 'point', 'edge', 'face'):
            radio = QtWidgets.QRadioButton(mode)
            self.mode_group.addButton(radio)
            mode_row.addWidget(radio)
        self.ids_list = QtWidgets.QListWidget()
        self.ids_list.setMaximumHeight(90)
        self.ids_add_btn = QtWidgets.QPushButton('Edit...')
        self.ids_remove_btn = QtWidgets.QPushButton('Remove')
        self.ids_pick_btn = QtWidgets.QPushButton('Pick')
        self.ids_pick_btn.setEnabled(False)
        self.ids_pick_btn.setToolTip(
            'grab the DCC selection - only available inside Maya (planned)')
        ids_btns = QtWidgets.QHBoxLayout()
        ids_btns.addWidget(self.ids_add_btn)
        ids_btns.addWidget(self.ids_remove_btn)
        ids_btns.addWidget(self.ids_pick_btn)
        group_form = QtWidgets.QFormLayout()
        group_form.addRow('pattern', self.pattern_edit)
        group_form.addRow('item', self.item_combo)
        group_form.addRow('mode', mode_row)
        group_form.addRow('ids', self.ids_list)
        group_form.addRow('', ids_btns)
        self.group_box = QtWidgets.QGroupBox('group')
        self.group_box.setLayout(group_form)

        self.pattern_edit.editingFinished.connect(
            lambda: self._write_param('pattern', self.pattern_edit.text()))
        self.item_combo.lineEdit().editingFinished.connect(
            self._on_item_edited)
        self.item_combo.activated.connect(self._on_item_edited)
        self.mode_group.buttonClicked.connect(self._on_mode_clicked)
        self.ids_add_btn.clicked.connect(self._on_ids_add)
        self.ids_remove_btn.clicked.connect(self._on_ids_remove)

        # hierarchy-op section: asset / rig / stage groups
        self.asset_edit = QtWidgets.QLineEdit()
        self.rig_edit = QtWidgets.QLineEdit()
        self.groups_list = QtWidgets.QListWidget()
        self.groups_list.setMaximumHeight(110)
        self.group_add_btn = QtWidgets.QPushButton('Add...')
        self.group_remove_btn = QtWidgets.QPushButton('Remove')
        groups_btns = QtWidgets.QHBoxLayout()
        groups_btns.addWidget(self.group_add_btn)
        groups_btns.addWidget(self.group_remove_btn)
        hier_form = QtWidgets.QFormLayout()
        hier_form.addRow('asset', self.asset_edit)
        hier_form.addRow('rig', self.rig_edit)
        hier_form.addRow('groups', self.groups_list)
        hier_form.addRow('', groups_btns)
        self.hierarchy_box = QtWidgets.QGroupBox('hierarchy')
        self.hierarchy_box.setLayout(hier_form)
        self.asset_edit.editingFinished.connect(
            lambda: self._write_param('asset', self.asset_edit.text()))
        self.rig_edit.editingFinished.connect(
            lambda: self._write_param('rig', self.rig_edit.text()))
        self.group_add_btn.clicked.connect(self._on_group_add)
        self.group_remove_btn.clicked.connect(self._on_group_remove)

        # step-op section: stage / copy method
        self.stage_edit = QtWidgets.QLineEdit()
        self.stage_edit.setPlaceholderText('presim, sim, postsim...')
        self.method_combo = QtWidgets.QComboBox()
        self.method_combo.addItems(['outmesh', 'duplicate'])
        self.method_combo.setToolTip(
            'outmesh = live connected copy (default)\n'
            'duplicate = static copy (nucleus presim meshes)')
        step_form = QtWidgets.QFormLayout()
        step_form.addRow('stage', self.stage_edit)
        step_form.addRow('method', self.method_combo)
        self.step_box = QtWidgets.QGroupBox('step')
        self.step_box.setLayout(step_form)
        self.stage_edit.editingFinished.connect(
            lambda: self._write_param('stage', self.stage_edit.text()))
        self.method_combo.activated.connect(self._on_method_picked)

        # file-op section: path / filter / hierarchy inspector
        self.path_edit = QtWidgets.QLineEdit()
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("wildcards, e.g. *_sim_msh")
        self.tree_btn = QtWidgets.QPushButton('Tree...')
        self.tree_btn.clicked.connect(self._on_tree)
        self.path_edit.editingFinished.connect(
            lambda: self._write_param('path', self.path_edit.text()))
        self.filter_edit.editingFinished.connect(
            lambda: self._write_param('filter', self.filter_edit.text()))
        path_row = QtWidgets.QHBoxLayout()
        path_row.addWidget(self.path_edit)
        path_row.addWidget(self.browse_btn)
        filter_row = QtWidgets.QHBoxLayout()
        filter_row.addWidget(self.filter_edit)
        filter_row.addWidget(self.tree_btn)
        file_form = QtWidgets.QFormLayout()
        file_form.addRow('path', path_row)
        file_form.addRow('filter', filter_row)
        self.file_box = QtWidgets.QGroupBox('file')
        self.file_box.setLayout(file_form)

        form = QtWidgets.QFormLayout()
        form.addRow('id', self.id_edit)
        form.addRow('type', self.type_combo)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.file_box)
        layout.addWidget(self.group_box)
        layout.addWidget(self.step_box)
        layout.addWidget(self.hierarchy_box)
        layout.addWidget(QtWidgets.QLabel('params'))
        layout.addWidget(self.params_edit, stretch=1)
        layout.addWidget(QtWidgets.QLabel('inputs  (port: "node" or "node.key")'))
        layout.addWidget(self.inputs_edit)
        layout.addWidget(self.error_label)
        layout.addWidget(self.apply_btn)
        self.set_node(None, None)

    # ------------------------------------------------------------------
    def set_node(self, node_id, entry, item_options=None):
        self._item_options = list(item_options or [])
        self._current = node_id
        self.setEnabled(node_id is not None)
        self.error_label.setText('')
        if node_id is None:
            self.id_edit.setText('')
            self.params_edit.setPlainText('')
            self.inputs_edit.setPlainText('')
            return
        self.id_edit.setText(node_id)
        self.type_combo.setCurrentText(entry.get('type', ''))
        self._refresh_browse()
        self.params_edit.setPlainText(
            json.dumps(entry.get('params', {}), indent=4))
        self.inputs_edit.setPlainText(
            json.dumps(entry.get('inputs', {}), indent=4))
        self._sync_file_fields()
        self._sync_group_fields()
        self._sync_step_fields()
        self._sync_hierarchy_fields()

    def pending_payload(self):
        """Current panel state as an apply payload (None when no node is
        loaded or the json does not parse) - lets the main window commit
        edits before the selection moves elsewhere."""
        if self._current is None:
            return None
        try:
            params = json.loads(self.params_edit.toPlainText() or '{}')
            inputs = json.loads(self.inputs_edit.toPlainText() or '{}')
        except ValueError:
            return None
        node_id = self.id_edit.text().strip()
        if (not node_id or not isinstance(params, dict)
                or not isinstance(inputs, dict)):
            return None
        return {'old_id': self._current,
                'node_id': node_id,
                'type': self.type_combo.currentText(),
                'params': params,
                'inputs': inputs}

    #: op types whose params carry a browsable file, and the param key
    PATH_PARAMS = {'file': 'path',
                   'preset': 'path',
                   'constraint': 'preset_path'}

    def _refresh_browse(self, *args):
        op_type = self.type_combo.currentText()
        self.file_box.setVisible(op_type in self.PATH_PARAMS)
        is_file = op_type == 'file'
        self.filter_edit.setVisible(is_file)
        self.tree_btn.setVisible(is_file)
        self.group_box.setVisible(op_type == 'group')
        self.step_box.setVisible(op_type == 'step')
        self.hierarchy_box.setVisible(op_type == 'hierarchy')

    HIERARCHY_DEFAULTS = ('presim', 'utils', 'collider', 'sim',
                          'postsim', 'exp')

    def _write_groups(self):
        groups = [self.groups_list.item(i).text()
                  for i in range(self.groups_list.count())]
        params = self._params()
        if groups and groups != list(self.HIERARCHY_DEFAULTS):
            params['groups'] = groups
        else:
            params.pop('groups', None)
        self.params_edit.setPlainText(json.dumps(params, indent=4))

    def _on_group_add(self):
        text, ok = QtWidgets.QInputDialog.getText(
            self, 'Add group', 'stage group name:')
        if not ok or not text.strip():
            return
        entry = QtWidgets.QListWidgetItem(text.strip())
        self.groups_list.addItem(entry)
        self._write_groups()

    def _on_group_remove(self):
        for item in self.groups_list.selectedItems():
            self.groups_list.takeItem(self.groups_list.row(item))
        self._write_groups()

    def _sync_hierarchy_fields(self):
        params = self._params()
        self.asset_edit.setText(str(params.get('asset', '')))
        self.rig_edit.setText(str(params.get('rig', '')))
        self.groups_list.clear()
        for name in params.get('groups') or self.HIERARCHY_DEFAULTS:
            entry = QtWidgets.QListWidgetItem(str(name))
            self.groups_list.addItem(entry)

    def _on_method_picked(self, *args):
        method = self.method_combo.currentText()
        # default method stays out of the document
        self._write_param('method', '' if method == 'outmesh' else method)

    def _sync_step_fields(self):
        params = self._params()
        self.stage_edit.setText(str(params.get('stage', '')))
        self.method_combo.setCurrentText(
            str(params.get('method', 'outmesh')))

    # ------------------------------------------------------------------
    # group section
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_chunk(text: str):
        """'7' -> 7; '33-47' / '33:47' -> '33:47'. Raises ValueError."""
        text = text.strip().replace('-', ':')
        if ':' in text:
            start, end = text.split(':', 1)
            return f'{int(start)}:{int(end)}'
        return int(text)

    def _on_item_edited(self, *args):
        text = self.item_combo.currentText().strip()
        items = [t.strip() for t in text.split(',') if t.strip()]
        params = self._params()
        if items:
            params['items'] = items
        else:
            params.pop('items', None)
        self.params_edit.setPlainText(json.dumps(params, indent=4))

    def _on_mode_clicked(self, button):
        self._write_param('mode', button.text())

    def _write_ids(self):
        ids = []
        for row in range(self.ids_list.count()):
            try:
                ids.append(self._parse_chunk(self.ids_list.item(row).text()))
            except ValueError:
                continue
        params = self._params()
        if ids:
            params['ids'] = ids
        else:
            params.pop('ids', None)
        self.params_edit.setPlainText(json.dumps(params, indent=4))

    def _on_ids_add(self):
        text, ok = QtWidgets.QInputDialog.getText(
            self, 'Component ids', "id or range ('7', '33-47'):")
        if not ok or not text.strip():
            return
        try:
            chunk = self._parse_chunk(text)
        except ValueError:
            self.error_label.setText(f'invalid id chunk: {text!r}')
            return
        entry = QtWidgets.QListWidgetItem(str(chunk))
        self.ids_list.addItem(entry)
        self._write_ids()

    def _on_ids_remove(self):
        for item in self.ids_list.selectedItems():
            self.ids_list.takeItem(self.ids_list.row(item))
        self._write_ids()

    def _sync_group_fields(self):
        params = self._params()
        pattern = params.get('pattern', '')
        if isinstance(pattern, list):
            pattern = ', '.join(str(p) for p in pattern)
        self.pattern_edit.setText(str(pattern))
        self.item_combo.blockSignals(True)
        self.item_combo.clear()
        self.item_combo.addItem('')
        self.item_combo.addItems(getattr(self, '_item_options', []))
        self.item_combo.setEditText(
            ', '.join(str(i) for i in params.get('items', [])))
        self.item_combo.blockSignals(False)
        mode = params.get('mode', 'object')
        for button in self.mode_group.buttons():
            button.setChecked(button.text() == mode)
        self.ids_list.clear()
        for chunk in params.get('ids', []):
            entry = QtWidgets.QListWidgetItem(str(chunk))
            self.ids_list.addItem(entry)

    def _params(self) -> dict:
        try:
            params = json.loads(self.params_edit.toPlainText() or '{}')
        except ValueError:
            params = {}
        return params if isinstance(params, dict) else {}

    def _write_param(self, key: str, value: str):
        if key == 'path':
            key = self.PATH_PARAMS.get(self.type_combo.currentText(), 'path')
        params = self._params()
        if value:
            params[key] = value
        else:
            params.pop(key, None)
        self.params_edit.setPlainText(json.dumps(params, indent=4))

    def _sync_file_fields(self):
        params = self._params()
        key = self.PATH_PARAMS.get(self.type_combo.currentText(), 'path')
        self.path_edit.setText(str(params.get(key, '')))
        value = params.get('filter', '')
        if isinstance(value, list):
            value = ', '.join(str(v) for v in value)
        self.filter_edit.setText(str(value))

    def _on_browse(self):
        op_type = self.type_combo.currentText()
        key = self.PATH_PARAMS.get(op_type)
        if key is None:
            return
        params = self._params()
        filters = ('Geometry (*.abc);;Maya (*.ma *.mb);;All files (*)'
                   if op_type == 'file' else 'Preset (*.json)')
        if op_type == 'file' and params.get('mode') == 'write':
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, 'Output file', params.get(key, ''), filters)
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, 'Pick file', params.get(key, ''), filters)
        if not path:
            return
        self._write_param('path', path)
        self._sync_file_fields()

    def _on_tree(self):
        path = self.path_edit.text().strip()
        if not path:
            self.error_label.setText('set a file path first')
            return
        dialog = SceneTreeDialog(path, self)
        dialog.picked.connect(self._on_tree_pick)
        dialog.exec()

    def _on_tree_pick(self, name: str):
        self.filter_edit.setText(name)
        self._write_param('filter', name)

    def _on_apply(self):
        if self._current is None:
            return
        try:
            params = json.loads(self.params_edit.toPlainText() or '{}')
            inputs = json.loads(self.inputs_edit.toPlainText() or '{}')
        except ValueError as e:
            self.error_label.setText(f'json error: {e}')
            return
        if not isinstance(params, dict) or not isinstance(inputs, dict):
            self.error_label.setText('params and inputs must be json objects')
            return
        node_id = self.id_edit.text().strip()
        if not node_id:
            self.error_label.setText('node id cannot be empty')
            return
        self.error_label.setText('')
        self.apply_requested.emit({'old_id': self._current,
                                   'node_id': node_id,
                                   'type': self.type_combo.currentText(),
                                   'params': params,
                                   'inputs': inputs})