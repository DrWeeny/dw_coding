import os
import sys

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if rdPath not in sys.path:
    print(f"Adding {rdPath} to sys.path")
    sys.path.insert(0, rdPath)

# Maya-specific imports
import maya.cmds as cmds
from maya import OpenMayaUI as omui

# Shiboken and PySide6 for Maya 2022+
from shiboken6 import wrapInstance
from PySide6 import QtWidgets, QtCore, QtGui

# External utility imports
import dw_maya.dw_nucleus_utils as dwnx
import dw_maya.dw_presets_io as dwpreset


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
    path_parts = path.split('/')
    to_check = [path.rsplit('/', x)[0] for x in range(1, limiter + 1) if x <= len(path_parts)]
    to_process = []

    for dir_path in to_check:
        if not os.path.exists(dir_path):
            to_process.append(dir_path)

    # Create directory using external utility (dw_json)
    dwpreset.make_dir(path)

    # Set permission for each new directory
    for dir_path in to_process:
        os.chmod(dir_path, mode)


class PresetManager(QtWidgets.QMainWindow):
    type_list = ['character', 'prop']
    node_types = ['hairSystem', 'nCloth', 'nRigid', 'dynamicConstraint', 'nucleus', 'follicle']
    is_checked = [True, True, True, False, True, False]
    _proj = os.environ.get('PROJ_NAME', 'default_project')
    _asset = 'winnie'
    preset_name = 'presetName'

    def __init__(self, parent=None):
        if parent is None:
            parent = get_maya_main_window()
        super(PresetManager, self).__init__(parent)

        self._path = f"/people/abtidona/public/{self._proj}/assets/{{}}/{{}}/cfx/master/simRig/data/attr_presets/"
        self._dynC_path = f"/people/abtidona/public/{self._proj}/assets/{{}}/{{}}/cfx/master/simRig/data/attr_presets/dynC/"
        self._dynC_isChecked = False

        self.setGeometry(579, 515, 647, 181)
        self.setWindowTitle('Preset Manager')

        self.initUI()

    def initUI(self):
        self.centralwidget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.centralwidget)
        main_layout = QtWidgets.QVBoxLayout(self.centralwidget)
        central_layout = QtWidgets.QHBoxLayout()

        # Layout for saving presets
        vl_save = QtWidgets.QVBoxLayout()
        _width_01 = 180

        # Types ComboBox
        self.cb_types = QtWidgets.QComboBox()
        self.cb_types.setFixedWidth(_width_01)
        self.cb_types.addItems(self.type_list)
        vl_save.addWidget(self.cb_types)

        # Assets ComboBox
        self.cb_assets = QtWidgets.QComboBox()
        self.cb_assets.setFixedWidth(_width_01)
        vl_save.addWidget(self.cb_assets)

        # Preset Name Input
        self.le_preset_name = QtWidgets.QLineEdit()
        self.le_preset_name.setFixedWidth(_width_01)
        self.le_preset_name.setText('defaultPreset')
        p_maya = QtCore.QRegExp("[A-Za-z_0-9]{1,20}")
        validator_maya = QtGui.QRegExpValidator(p_maya, self)
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

        # Connections
        self.cb_types.activated.connect(self.update_assets)
        self.cb_assets.activated.connect(self.populate_presets)
        self.pb_save.clicked.connect(self.save_preset)
        self.pb_load.clicked.connect(self.load_preset)

    def populate_nsfilter(self):
        """
        Populate namespace filter ComboBox.
        """
        self.cb_nsfilter.clear()
        ns_list = cmds.namespaceInfo(lon=True)
        asset_ns = [ns for ns in ns_list if ns.startswith(self._asset)]
        self.cb_nsfilter.addItem(':')
        self.cb_nsfilter.addItems(asset_ns)

    def update_assets(self):
        """
        Update asset list in ComboBox based on project and sequence.
        """
        self.cb_assets.clear()
        asset_list = sorted(os.listdir(f'/work/{self._proj}/assets/{self.seq}'))
        self.cb_assets.addItems(asset_list)

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
        Save the selected attributes and dynamic constraints as presets.
        """
        # Retrieve selected nodes based on node types
        nodes = cmds.ls(type=self.node_types)
        if self.ns_filter != ':':
            nodes = [n for n in nodes if n.startswith(self.ns_filter + ':')]

        attr_dic = dwpreset.createAttrPreset(nodes)
        attr_dic['data_type'] = self.node_types
        full_path = self.path + self.preset_name + '.json'

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

    def load_preset(self):
        """
        Load the selected preset and apply the saved attributes to the current scene nodes.
        """
        item = self.list_widget.currentItem()
        if item:
            preset_name = str(item.text())
            nodes = cmds.ls(type=self.node_types)
            full_path = self.path + preset_name + '.json'
            if os.path.isfile(full_path):
                data = dwpreset.load_json(full_path)

                for node in nodes:
                    if node in data:
                        for attr, value in data[node].items():
                            cmds.setAttr(f'{node}.{attr}', value)

                print('Preset loaded successfully!')

    @property
    def seq(self):
        """
        Get the current sequence from the ComboBox.
        """
        return str(self.cb_types.currentText())

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
        Get the current path for saving/loading presets based on the project, sequence, and asset.
        """
        return self._path.format(self.seq, self.asset)

    @property
    def dynC_path(self):
        """
        Get the dynamic constraint rig path for saving/loading presets.
        """
        return self._dynC_path.format(self.seq, self.asset)

    @property
    def asset(self):
        """
        Get the selected asset from the ComboBox.
        """
        return str(self.cb_assets.currentText())

    @property
    def preset_name(self):
        """
        Get the preset name entered in the line edit widget.
        """
        return self.le_preset_name.text() or 'defaultPreset'


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







