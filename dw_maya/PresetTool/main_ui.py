import os
import json
import fnmatch
import traceback

# Maya-specific imports
import maya.cmds as cmds
from maya import OpenMayaUI as omui

from dw_maya.PresetTool.compat import QtWidgets, QtCore, wrapInstance, qt_exec

# External utility imports
import dw_pipe_project
import dw_maya.dw_nucleus_utils as dwnx
import dw_maya.dw_presets_io as dwpreset
from dw_maya.dw_constants import SPECIAL_TOKENS
from dw_logger import get_logger

logger = get_logger()


def get_maya_main_window():
    """
    Get Maya main window as QWidget.

    :return: Maya main window as a QWidget instance.
    """
    main_window_ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(main_window_ptr), QtWidgets.QWidget)


def make_chmod_dir(path, mode=0o777, limiter=10):
    """
    Ensure a directory exists and set permissions.

    :param path: Path of the directory.
    :param mode: Permission mode (default is 0o777).
    :param limiter: Limit the depth of path splitting for creating directories (default is 10).
    """
    path = path.replace('\\', '/')
    path_parts = path.split('/')
    to_check = [path.rsplit('/', x)[0] for x in range(1, limiter + 1) if x <= len(path_parts)]
    to_process = []

    for dir_path in to_check:
        if not os.path.exists(dir_path):
            to_process.append(dir_path)

    # Create directory using external utility (dw_json)
    dwpreset.make_dir(path)

    # Set permission for each new directory (best effort - no-op on Windows)
    for dir_path in to_process:
        try:
            os.chmod(dir_path, mode)
        except OSError:
            pass


class PresetManager(QtWidgets.QMainWindow):
    type_list = ['character', 'prop']
    node_types = ['hairSystem', 'nCloth', 'nRigid', 'dynamicConstraint', 'nucleus', 'follicle']
    is_checked = [True, True, True, False, True, False]

    OPTVAR_ROOT = 'dw_presetTool_root'
    OPTVAR_TOKEN_RULES = 'dw_presetTool_token_rules'
    SHOT_SUBDIR = 'data/attr_presets'

    #: (node type or name pattern, attribute, token) applied at save time:
    #: matching stored values are replaced by the token, which the load side
    #: expands through SPECIAL_TOKENS.
    TOKEN_RULES_DEFAULT = [['nucleus', 'startFrame', '$RFSTART']]

    def __init__(self, parent=None):
        super(PresetManager, self).__init__(parent or get_maya_main_window())

        self._dynC_isChecked = False
        self.project = dw_pipe_project.get_project()
        self._restore_root()
        self.token_rules = self._restore_token_rules()

        self.setGeometry(579, 515, 647, 221)
        self.setWindowTitle('Preset Manager')

        self.initUI()
        self.refresh_all()

    # ------------------------------------------------------------------
    # Root persistence (DefaultProject only)
    # ------------------------------------------------------------------

    def _restore_root(self):
        """Re-apply the root chosen in a previous session (optionVar)."""
        if not isinstance(self.project, dw_pipe_project.DefaultProject):
            return
        if cmds.optionVar(exists=self.OPTVAR_ROOT):
            root = cmds.optionVar(q=self.OPTVAR_ROOT)
            if root:
                self.project.set_root(root)

    def set_preset_root(self):
        """File > Set Preset Root: pick the folder presets are stored under."""
        start = self.project.root if isinstance(self.project, dw_pipe_project.DefaultProject) else ''
        chosen = QtWidgets.QFileDialog.getExistingDirectory(self,
                                                            'Choose preset root',
                                                            start)
        if chosen:
            self.project.set_root(chosen)
            cmds.optionVar(sv=(self.OPTVAR_ROOT, chosen))
            self.refresh_all()

    def reset_preset_root(self):
        """File > Reset Root: back to DW_PRESET_PATH env var or temp dir."""
        self.project.set_root(None)
        if cmds.optionVar(exists=self.OPTVAR_ROOT):
            cmds.optionVar(remove=self.OPTVAR_ROOT)
        self.refresh_all()

    # ------------------------------------------------------------------
    # Special token rules
    # ------------------------------------------------------------------

    def _restore_token_rules(self):
        """Load the token rules saved in a previous session (optionVar)."""
        if cmds.optionVar(exists=self.OPTVAR_TOKEN_RULES):
            try:
                rules = json.loads(cmds.optionVar(q=self.OPTVAR_TOKEN_RULES))
                return [r for r in rules if len(r) == 3]
            except (ValueError, TypeError):
                logger.warning('Invalid saved token rules, using defaults')
        return [list(r) for r in self.TOKEN_RULES_DEFAULT]

    def edit_token_rules(self):
        """File > Special Tokens: edit the save-time tokenization rules."""
        dialog = TokenRulesDialog(self.token_rules, parent=self)
        if qt_exec(dialog) == QtWidgets.QDialog.Accepted:
            self.token_rules = dialog.rules()
            cmds.optionVar(sv=(self.OPTVAR_TOKEN_RULES,
                               json.dumps(self.token_rules)))

    def _apply_token_rules(self, attr_dic):
        """Replace stored values with tokens according to the rules.

        A rule matches when its first field equals the entry's stored
        nodeType, or fnmatches the stored node name (namespace-stripped).
        """
        for match, attr, token in self.token_rules:
            if token not in SPECIAL_TOKENS:
                logger.warning(f"Unknown token '{token}' in rule, skipped")
                continue
            for key, attrs in attr_dic.items():
                if not isinstance(attrs, dict) or attr not in attrs:
                    continue
                if attrs.get('nodeType') == match or fnmatch.fnmatch(key, match):
                    attrs[attr] = token

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def initUI(self):
        self.centralwidget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.centralwidget)
        main_layout = QtWidgets.QVBoxLayout(self.centralwidget)
        central_layout = QtWidgets.QHBoxLayout()

        # Menu bar
        menu_file = self.menuBar().addMenu('File')
        self.act_set_root = menu_file.addAction('Set Preset Root...')
        self.act_set_root.triggered.connect(self.set_preset_root)
        self.act_reset_root = menu_file.addAction('Reset Root to Default')
        self.act_reset_root.triggered.connect(self.reset_preset_root)
        menu_file.addSeparator()
        self.act_tokens = menu_file.addAction('Special Tokens...')
        self.act_tokens.triggered.connect(self.edit_token_rules)
        if not isinstance(self.project, dw_pipe_project.DefaultProject):
            # external studio adapter owns the paths
            self.act_set_root.setEnabled(False)
            self.act_reset_root.setEnabled(False)

        # Layout for saving presets
        vl_save = QtWidgets.QVBoxLayout()
        _width_01 = 180

        # Asset / Shot mode
        self.cb_mode = QtWidgets.QComboBox()
        self.cb_mode.setFixedWidth(_width_01)
        self.cb_mode.addItems(['Asset', 'Shot (Maya project)'])
        vl_save.addWidget(self.cb_mode)

        # Types (asset category) ComboBox - editable for quick tests
        self.cb_types = QtWidgets.QComboBox()
        self.cb_types.setFixedWidth(_width_01)
        self.cb_types.setEditable(True)
        vl_save.addWidget(self.cb_types)

        # Assets ComboBox - editable so any name can be typed and saved
        self.cb_assets = QtWidgets.QComboBox()
        self.cb_assets.setFixedWidth(_width_01)
        self.cb_assets.setEditable(True)
        vl_save.addWidget(self.cb_assets)

        # Preset Name Input
        self.le_preset_name = QtWidgets.QLineEdit()
        self.le_preset_name.setFixedWidth(_width_01)
        self.le_preset_name.setText('defaultPreset')
        from dw_utils.qt_utils.core import make_validator
        validator_maya = make_validator("[A-Za-z_0-9]{1,20}")
        self.le_preset_name.setValidator(validator_maya)
        vl_save.addWidget(self.le_preset_name)

        # Save Button
        self.pb_save = QtWidgets.QPushButton('Save')
        self.pb_save.setFixedWidth(_width_01)
        vl_save.addWidget(self.pb_save)

        # Layout for node types and filters
        vl_type = QtWidgets.QVBoxLayout()

        # Namespace filter ComboBox
        self.cb_nsfilter = QtWidgets.QComboBox()
        self.populate_nsfilter()
        vl_type.addWidget(self.cb_nsfilter)

        # Node type checkboxes
        self.node_checkboxes = []
        for t, state in zip(self.node_types, self.is_checked):
            checkbox = QtWidgets.QCheckBox(t)
            checkbox.setChecked(state)
            self.node_checkboxes.append(checkbox)
            vl_type.addWidget(checkbox)

        # Dynamic Constraint Checkbox
        self.cb_dynC = QtWidgets.QCheckBox('Dynamic Constraint Rig')
        self.cb_dynC.setStyleSheet("QCheckBox { color: red }")
        self.cb_dynC.setChecked(self._dynC_isChecked)
        vl_type.addWidget(self.cb_dynC)

        # Layout for loading presets
        vl_load = QtWidgets.QVBoxLayout()
        self.list_widget = QtWidgets.QListWidget(self)
        self.list_widget.setSelectionMode(QtWidgets.QListWidget.SingleSelection)
        vl_load.addWidget(self.list_widget)

        # Load Button
        self.pb_load = QtWidgets.QPushButton('Load Selected')
        vl_load.addWidget(self.pb_load)

        # Adding layouts to central layout
        central_layout.addLayout(vl_save)
        central_layout.addLayout(vl_type)
        central_layout.addLayout(vl_load)
        main_layout.addLayout(central_layout)

        # Status bar shows where a Save will actually write
        self.statusBar()

        # Connections
        self.cb_mode.activated.connect(self.on_mode_changed)
        self.cb_types.activated.connect(self.on_category_changed)
        self.cb_assets.activated.connect(self.on_asset_changed)
        self.cb_assets.lineEdit().editingFinished.connect(self.on_asset_changed)
        self.pb_save.clicked.connect(self.save_preset)
        self.pb_load.clicked.connect(self.load_preset)

    # ------------------------------------------------------------------
    # Refresh / populate
    # ------------------------------------------------------------------

    def refresh_all(self):
        self.populate_categories()
        self.populate_assets()
        self.populate_presets()
        self.update_status()

    def on_mode_changed(self):
        self.cb_types.setEnabled(not self.shot_mode)
        self.cb_assets.setEnabled(not self.shot_mode)
        self.populate_presets()
        self.update_status()

    def on_category_changed(self):
        self.populate_assets()
        self.populate_presets()
        self.update_status()

    def on_asset_changed(self):
        self.populate_presets()
        self.update_status()

    def update_status(self):
        self.statusBar().showMessage(f"Presets: {self.path}")

    def populate_categories(self):
        """Fill the category ComboBox from the pipe adapter."""
        current = self.category
        self.cb_types.clear()
        try:
            categories = self.project.list_asset_categories()
        except NotImplementedError:
            categories = []
        except Exception:
            logger.error(f"list_asset_categories failed:\n{traceback.format_exc()}")
            categories = []
        self.cb_types.addItems(categories or self.type_list)
        if current:
            self.cb_types.setEditText(current)

    def populate_assets(self):
        """Fill the asset ComboBox from the pipe adapter."""
        current = self.asset
        self.cb_assets.clear()
        try:
            assets = self.project.list_assets(self.category)
        except NotImplementedError:
            assets = []
        except Exception:
            logger.error(f"list_assets failed:\n{traceback.format_exc()}")
            assets = []
        self.cb_assets.addItems(assets)
        if current:
            self.cb_assets.setEditText(current)

    def populate_nsfilter(self):
        """
        Populate namespace filter ComboBox.
        """
        self.cb_nsfilter.clear()
        ns_list = cmds.namespaceInfo(lon=True) or []
        ns_list = [ns for ns in ns_list if ns not in ('UI', 'shared')]
        self.cb_nsfilter.addItem(':')
        self.cb_nsfilter.addItems(ns_list)

    def populate_presets(self):
        """
        Populate the list widget with presets found in the specified paths.
        """
        self.list_widget.clear()
        preset_files = []

        if os.path.isdir(self.path):
            preset_files = [f for f in os.listdir(self.path) if f.endswith('.json')]

        if os.path.isdir(self.dynC_path):
            dynC_files = [f for f in os.listdir(self.dynC_path) if f.endswith('.json')]
            preset_files += dynC_files

        preset_files = list(set(preset_files))
        for preset in preset_files:
            item = QtWidgets.QListWidgetItem(preset.split('.')[0])
            self.list_widget.addItem(item)

    def save_preset(self):
        """
        Save the current Maya node attributes and dynamic constraint rig settings as a preset.

        This function collects attributes from selected node types, applies any namespace filters,
        and saves them as a JSON file in the specified path. If dynamic constraints are enabled,
        those settings are saved separately.

        Raises:
            OSError: If there is an error creating directories or saving files.

        Example:
            >>> preset_manager.save_preset()
        """
        try:
            # Retrieve selected nodes based on node types
            nodes = cmds.ls(type=self.node_types)
            if self.ns_filter != ':':
                nodes = [n for n in nodes if n.startswith(self.ns_filter + ':')]

            # Create attribute preset dictionary
            attr_dic = dwpreset.createAttrPreset(nodes)
            # Swap rule-matched values for special tokens ($RFSTART, ...)
            self._apply_token_rules(attr_dic)
            attr_dic['data_type'] = self.node_types
            full_path = os.path.join(self.path, f"{self.preset_name}.json")

            # Save the attribute presets
            make_chmod_dir(self.path)
            dwpreset.save_json(full_path, attr_dic)
            os.chmod(full_path, 0o777)

            # Save dynamic constraint rig presets if enabled
            if self.dynCRig:
                make_chmod_dir(self.dynC_path)
                full_dyn_path = dwnx.saveNConstraintRig(namespace=self.ns_filter,
                                                        path=self.dynC_path,
                                                        file=self.preset_name)
                os.chmod(full_dyn_path, 0o777)

            self.populate_presets()
        except OSError as e:
            print(f"Error saving preset: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

    def load_preset(self):
        """
        Load the selected preset: apply the saved attributes to the current
        scene nodes and, when the Dynamic Constraint Rig checkbox is ticked,
        rebuild the saved dynamicConstraint network from the dynC subfolder.
        """
        item = self.list_widget.currentItem()
        if not item:
            return
        preset_name = str(item.text())
        loaded = False

        full_path = os.path.join(self.path, preset_name + '.json')
        if os.path.isfile(full_path):
            data = dwpreset.load_json(full_path)
            for key, attrs in data.items():
                if key == 'data_type' or not isinstance(attrs, dict):
                    continue
                node = self._resolve_preset_node(key)
                if not node:
                    continue
                for attr, value in attrs.items():
                    if attr == 'nodeType':
                        continue
                    # Expand special tokens ($RFSTART, ...) at load time
                    if isinstance(value, str) and value in SPECIAL_TOKENS:
                        value = SPECIAL_TOKENS[value]()
                    plug = f'{node}.{attr}'
                    try:
                        if cmds.objExists(plug) and cmds.getAttr(plug, settable=True):
                            if isinstance(value, str):
                                cmds.setAttr(plug, value, type='string')
                            else:
                                cmds.setAttr(plug, value)
                    except Exception as e:
                        logger.warning(f'Could not set {plug}: {e}')
            loaded = True

        # Rebuild dynamic constraint rig if enabled
        if self.dynCRig:
            full_dyn_path = os.path.join(self.dynC_path, preset_name + '.json')
            if os.path.isfile(full_dyn_path):
                created = dwnx.createAllConstraintPresets(full_dyn_path,
                                                          targ_ns=self.ns_filter)
                print(f'Rebuilt {len(created)} dynamic constraint(s): {created}')
                loaded = True
            else:
                cmds.warning(f'No dynamic constraint preset found: {full_dyn_path}')

        if loaded:
            print('Preset loaded successfully!')
        else:
            cmds.warning(f'Nothing loaded for preset {preset_name} in {self.path}')

    def _resolve_preset_node(self, stored_name):
        """Resolve a namespace-stripped stored node name to a scene node.

        Tries the namespace filter first, then root, then an unambiguous
        any-namespace lookup.
        """
        if self.ns_filter != ':':
            candidate = f'{self.ns_filter}:{stored_name}'
            if cmds.objExists(candidate):
                return candidate
        if cmds.objExists(stored_name):
            return stored_name
        hits = cmds.ls(stored_name, recursive=True) or []
        if len(hits) == 1:
            return hits[0]
        if hits:
            logger.warning(f"'{stored_name}' is ambiguous across namespaces "
                           f"({hits}), skipped")
        return None

    @property
    def shot_mode(self):
        """
        True when presets are saved with the current Maya project (shot context).
        """
        return self.cb_mode.currentIndex() == 1

    @property
    def category(self):
        """
        Get the current asset category from the ComboBox.
        """
        return str(self.cb_types.currentText()).strip()

    @property
    def ns_filter(self):
        """
        Get the current namespace filter from the ComboBox.
        """
        return str(self.cb_nsfilter.currentText())

    @property
    def dynCRig(self):
        """
        Check if the dynamic constraint rig option is enabled.
        """
        return self.cb_dynC.isChecked()

    @property
    def path(self):
        """
        Get the current preset directory.

        Shot mode: current Maya project + data/attr_presets (zero config).
        Asset mode: asked to the pipe adapter; a broken adapter falls back
        to the DefaultProject filesystem layout instead of failing.
        """
        if self.shot_mode:
            workspace = cmds.workspace(query=True, rootDirectory=True)
            return os.path.join(workspace, *self.SHOT_SUBDIR.split('/'))
        try:
            return self.project.get_preset_dir(self.asset, category=self.category)
        except Exception:
            logger.error(f"get_preset_dir failed:\n{traceback.format_exc()}")
            fallback = dw_pipe_project.DefaultProject()
            return fallback.get_preset_dir(self.asset, category=self.category)

    @property
    def dynC_path(self):
        """
        Get the dynamic constraint rig path for saving/loading presets.
        """
        return os.path.join(self.path, 'dynC')

    @property
    def asset(self):
        """
        Get the selected asset from the ComboBox.
        """
        return str(self.cb_assets.currentText()).strip()

    @property
    def preset_name(self):
        """
        Get the preset name entered in the line edit widget.
        """
        return self.le_preset_name.text() or 'defaultPreset'


class TokenRulesDialog(QtWidgets.QDialog):
    """Edit the save-time tokenization rules.

    Each row is (node type or name pattern, attribute, token): at save time a
    stored value whose node matches the first field gets replaced by the
    token, expanded back to a scene value on load (SPECIAL_TOKENS).
    """

    HEADERS = ['Node type / pattern', 'Attribute', 'Token']

    def __init__(self, rules, parent=None):
        super(TokenRulesDialog, self).__init__(parent)
        self.setWindowTitle('Special Token Rules')
        self.resize(420, 220)

        layout = QtWidgets.QVBoxLayout(self)

        self.table = QtWidgets.QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        for rule in rules:
            self._add_row(rule)

        hl_buttons = QtWidgets.QHBoxLayout()
        pb_add = QtWidgets.QPushButton('Add')
        pb_remove = QtWidgets.QPushButton('Remove')
        pb_add.clicked.connect(self._on_add)
        pb_remove.clicked.connect(self._on_remove)
        hl_buttons.addWidget(pb_add)
        hl_buttons.addWidget(pb_remove)
        hl_buttons.addStretch()
        layout.addLayout(hl_buttons)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_row(self, rule=None):
        rule = rule or ['', '', list(SPECIAL_TOKENS.keys())[0]]
        row = self.table.rowCount()
        self.table.insertRow(row)

        item_match = QtWidgets.QTableWidgetItem(rule[0])
        item_attr = QtWidgets.QTableWidgetItem(rule[1])
        self.table.setItem(row, 0, item_match)
        self.table.setItem(row, 1, item_attr)

        cb_token = QtWidgets.QComboBox()
        cb_token.addItems(list(SPECIAL_TOKENS.keys()))
        index = cb_token.findText(rule[2])
        if index >= 0:
            cb_token.setCurrentIndex(index)
        self.table.setCellWidget(row, 2, cb_token)

    def _on_add(self):
        self._add_row()

    def _on_remove(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def rules(self):
        """Return the edited rules, dropping incomplete rows."""
        result = []
        for row in range(self.table.rowCount()):
            match_item = self.table.item(row, 0)
            attr_item = self.table.item(row, 1)
            cb_token = self.table.cellWidget(row, 2)
            match = match_item.text().strip() if match_item else ''
            attr = attr_item.text().strip() if attr_item else ''
            if match and attr and cb_token:
                result.append([match, attr, str(cb_token.currentText())])
        return result


'''
class AttributeDisplay(QtWidgets.QWidget):

    filter = '*'

    def __init__(self, data={}):
        super(AttributeDisplay, self).__init__()
        self.main_layout = QtWidgets.QVBoxLayout()

        # filter
        _hl_filter = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel('Filter :')
        label.setAlignment(QtCore.Qt.AlignBottom | QtCore.Qt.AlignRight)
        self._le_filter = QtWidgets.QLineEdit(self.filter)
        _hl_filter.addWidget(label)
        _hl_filter.addWidget(self._le_filter)
        label.setBuddy(self._le_filter)
        # QListview : nodes

        # QTableView : attributes + value
        header = ['attributes', 'values']
        table_model = MyTableModel(self, data_list, header)
        table_view = QtWidgets.QTableView()
        table_view.setModel(table_model)
        # set font
        font = QtGui.QFont("Courier New", 14)
        table_view.setFont(font)
        # set column width to fit contents (set font first!)
        table_view.resizeColumnsToContents()
        # enable sorting
        table_view.setSortingEnabled(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(table_view)
        self.setLayout(layout)

class MyTableModel(QtWidgets.QAbstractTableModel):
    def __init__(self, parent, mylist, header, *args):
        QtWidgets.QAbstractTableModel.__init__(self, parent, *args)
        self.mylist = mylist
        self.header = header
    def rowCount(self, parent):
        return len(self.mylist)
    def columnCount(self, parent):
        return len(self.mylist[0])
    def data(self, index, role):
        if not index.isValid():
            return None
        elif role != Qt.DisplayRole:
            return None
        return self.mylist[index.row()][index.column()]
    def headerData(self, col, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.header[col]
        return None
    def sort(self, col, order):
        """sort table by given column number col"""
        self.emit(QtCore.Signal("layoutAboutToBeChanged()"))
        self.mylist = sorted(self.mylist,
            key=operator.itemgetter(col))
        if order == Qt.DescendingOrder:
            self.mylist.reverse()
        self.emit(QtCore.Signal("layoutChanged()"))
'''


'''
try:
    presetman.deleteLater()
except:
    pass
presetman = PresetManager()
presetman.show()
'''







