import sys, os
import importlib

#ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import re
import os
import shutil
from PySide6 import QtWidgets, QtGui, QtCore  # Use PySide6 for Maya compatibility with Python 3

# External module imports (always required)
import dw_maya.dw_presets_io as dw_json
from dw_maya.dw_presets_io import make_dir

# Application mode variables
MODE = 0
MODE_MAYA = False
MODE_HOUDINI = False

def is_houdini():
    """Check if running in a Houdini environment."""
    global MODE_HOUDINI
    try:
        import hou
        MODE_HOUDINI = True
        return True
    except ImportError:
        return False

def is_maya():
    """Check if running in a Maya environment."""
    global MODE_MAYA
    try:
        import maya.cmds as cmds
        import maya.OpenMayaUI as omui
        from shiboken6 import wrapInstance  # Maya now uses shiboken6 with PySide6
        from . import ncloth_cmds
        from . import ziva_cmds
        from .dendrology.nucleus_leaf import *
        from .dendrology.rfx_nucleus_leaf import *
        from .dendrology.rfx_ziva_leaf import *
        from . import sim_widget
        MODE_MAYA = True
        return True
    except ImportError:
        return False

# Initialize environment mode
if is_houdini():
    # Houdini specific setup can be added here
    MODE=2
elif is_maya():
    # Maya specific setup can be added here
    MODE=0
else:
    MODE=1
    print("Warning: Running outside supported environments (Houdini or Maya). Limited functionality may be available.")

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


def get_houdini_window():
    """
    Get the main Houdini window.
    Returns:
        QWidget: The main Houdini window.
    """
    win = hou.ui.mainQtWindow()
    return win


def get_all_treeitems(tree_widget):
    """ 
    Get all QTreeWidgetItem objects from a given QTreeWidget.

    Args:
        tree_widget (QTreeWidget): The QTreeWidget instance to gather items from.

    Returns:
        list[QTreeWidgetItem]: A list of all QTreeWidgetItem objects in the tree.
    """
    items = []
    iterator = QtWidgets.QTreeWidgetItemIterator(tree_widget)

    while iterator.value():
        item = iterator.value()
        items.append(item)
        iterator += 1

    return items


class DynEvalUI(QtWidgets.QMainWindow):

    """
    The Sim UI embed a unified way to simulate different type of solvers
    """
    save_preset = True

    def __init__(self, parent=None):
        super(DynEvalUI, self).__init__(parent)
        self.setGeometry(867, 546, 900, 400)
        self.setWindowTitle('UI for Dynamic systems')
        self.initUI()

    def initUI(self):

        """
        There is a tree node representing the solver
        A middle widget with maps, cache list or deformer stack
        A third widget with all the tabs and tools

        Returns:

        """

        self.edit_mode = 'cache'  # cache maps
        self.cache_mode = 'override' or 'increment'

        self.centralwidget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.centralwidget)
        main_layout = QtWidgets.QHBoxLayout()

        # =====================================================================
        # TREE WITH ALL THE HIERARCHY =========================================
        vl_dyneval = QtWidgets.QVBoxLayout()
        self.dyn_eval_tree = QtWidgets.QTreeWidget()
        self.dyn_eval_tree.setObjectName("dyn_hierarchy")
        # enable multiple selection
        self.dyn_eval_tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.dyn_eval_tree.setColumnCount(2)
        self.dyn_eval_tree.setHeaderLabels(["Name", "I/O"])
        self.dyn_eval_tree.setMinimumWidth(280)
        self.dyn_eval_tree.setMaximumWidth(300)
        self.dyn_eval_tree.setExpandsOnDoubleClick(False)
        # make last header 'I/O' not stretchable
        header = self.dyn_eval_tree.header()
        header.setStretchLastSection(False)
        # To be more clear
        self.dyn_eval_tree.setAlternatingRowColors(True)
        self.dyn_eval_tree.setColumnWidth(0, 250)
        self.dyn_eval_tree.setColumnWidth(1, 25)

        # Create a contextual menu
        self.dyn_eval_tree.installEventFilter(self)
        self.dyn_eval_tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.dyn_eval_tree.customContextMenuRequested.connect(self.context_main)

        self.build_tree()

        # =====================================================================
        # TREE WITH ALL THE CACHE OR ALL THE MAPS PAINTABLE ===================
        # radio box : cache / maps
        # tree widget
        # TODO : make a widget in order to teatoff
        vl_cachemap = QtWidgets.QVBoxLayout()

        self.cb_mode_picker = QtWidgets.QComboBox()
        self.cb_mode_picker.addItem("Cache List")
        self.cb_mode_picker.addItem("Map List")
        # todo : deformer list
        self.cb_mode_picker.setCurrentIndex(0)

        self.cache_tree = sim_widget.CacheTree()
        self.maps_tree = sim_widget.MapTree()
        self.maps_tree.hide()
        self.cache_tree.setMinimumHeight(365)
        self.maps_tree.setMinimumHeight(365)
        vl_cachemap.addStretch(True)
        vl_cachemap.setMargin(2)

        # =====================================================================
        # TABS ================================================================
        # number 01:
        # Initialize tab screen
        self.vl_tabs = QtWidgets.QVBoxLayout()
        self.tabs = QtWidgets.QTabWidget()
        self.tab1_comment = sim_widget.CommentEditor(None)
        self.tab2 = QtWidgets.QWidget()
        self.tab3 = QtWidgets.QWidget()
        self.tab4 = QtWidgets.QWidget()
        self.tab5 = QtWidgets.QWidget()
        self.tab6 = QtWidgets.QWidget()
        self.tab7 = QtWidgets.QWidget()

        self.tabs.resize(200, 500)

        # Add tabs
        self.tabs.addTab(self.tab1_comment, "comments")
        self.tabs.addTab(self.tab2, "paint")
        self.tabs.addTab(self.tab3, "presets")
        self.tabs.addTab(self.tab4, "attributes")
        self.tabs.addTab(self.tab7, "wedging")
        self.tabs.addTab(self.tab5, "sim rig")
        self.tabs.addTab(self.tab6, "utils")

        # Add tabs to widget
        self.vl_tabs.addWidget(self.tabs)

        # =====================================================================
        # SET LAYOUT AND WIDGET ===============================================
        main_layout.addLayout(vl_dyneval)
        main_layout.addLayout(vl_cachemap)
        main_layout.addLayout(self.vl_tabs)
        vl_dyneval.addWidget(self.dyn_eval_tree)
        vl_cachemap.addWidget(self.cb_mode_picker)
        vl_cachemap.addWidget(self.maps_tree)
        vl_cachemap.addWidget(self.cache_tree)
        self.centralwidget.setLayout(main_layout)

        # =====================================================================
        # SIGNAL ==============================================================
        # First Tree Widget

        self.dyn_eval_tree.itemSelectionChanged.connect(self.cache_map_sel)
        self.dyn_eval_tree.itemDoubleClicked.connect(self.select)
        # Mode Select
        self.cb_mode_picker.currentIndexChanged.connect(self.cache_map_on_change)

        self.cache_tree.cache_tree.itemSelectionChanged.connect(self.set_comment)
        self.tab1_comment.save.connect(self.save_comment)

    def context_main(self, position):

        '''
        Contextual menu, for all the items in the main tree :
        # Refresh
        # Create Cache : nCache, Abc, Geometry
        # Advanced Option for Cache : cacheable attributes, sim rate, x
        # Save Preset
        # Restore Preset
        # Show nRigid show NConstraint
        # Find Documentation by Characters
        # smart activation
        # select Rest Mesh select Input Mesh

        :param position: <<QPos>>
        '''

        items = self.dyn_eval_tree.selectedItems()
        menu = QtWidgets.QMenu(self)

        # Open Documentation
        docu = QtWidgets.QMenu('documentation', self)
        char = QtWidgets.QAction(self)
        char.setText('Winnie PlaceHolder')
        docu.addAction(char)
        menu.addMenu(docu)

        # Contextual Menu depending of selection
        if not items:
            menu.exec_(self.dyn_eval_tree.viewport().mapToGlobal(position))
            return

        # see what type of Item we had : nCloth, Nucleus, nHairSystem, Ziva...
        _types = [i.node_type for i in items]
        # Are they all from the same type
        types_uniq = list(set(_types))
        if len(types_uniq) == 1:
            # if from the same type add cache methods Label
            lock = QtWidgets.QWidgetAction(self)
            lock.setDefaultWidget(QtWidgets.QLabel(' '*7+'Cache Methods :'))
            menu.addAction(lock)
            # Add Ncache
            if 'nCloth' in types_uniq or 'hairSystem' in types_uniq:
                lock = QtWidgets.QAction(self)
                lock.setText('create nCache for sel')
                lock.triggered.connect(self.createCache)
                menu.addAction(lock)
                menu.addSeparator()
            # Add GeoCache : geocache should work elsewhere in the hierarchy
            # if same topo
            if 'nCloth' in types_uniq or 'nRigid' in types_uniq:
                lock = QtWidgets.QAction(self)
                lock.setText('create geocache for sel')
                menu.addAction(lock)
                menu.addSeparator()

            if 'zSolverTransform' in types_uniq:
                lock = QtWidgets.QAction(self)
                lock.setText('create Alembic for sel')
                lock.triggered.connect(self.createZAbcCache)
                menu.addAction(lock)
                menu.addSeparator()

        menu.exec_(self.dyn_eval_tree.viewport().mapToGlobal(position))

    def createZAbcCache(self):
        dyn_items = self.dyn_eval_tree.selectedItems()
        suffix = ''
        _iter_list = sorted([str(i.get_iter() + 1) for i in dyn_items])
        current_iter = int(_iter_list[-1])

        meshes = []
        futurdir = []

        for i in dyn_items:
            shape = i.get_meshes()
            meshes += shape
            if current_iter != i.get_iter():
                mode = current_iter - i.get_iter()
            else:
                mode = 1 # increment the cache by one
            cachePath = i.cache_file(mode, suffix)
            futurdir.append(cachePath)

        # even if an abc cache of one item, it should have only one abc
        # we support multiple selection if we cache muscle + skin
        futurdir = list(set(futurdir))
        meshes = list(set(meshes))
        print(futurdir)
        caches = ziva_cmds.create_cache(futurdir[0], meshes)
        if len(futurdir) > 1:
            for file in futurdir:
                limi = len(file.split('/')) - 4
                dw_json.make_chmod_dir(file.rsplit('/', 1)[0],
                                       limi)
                shutil.copyfile(caches, file)
                os.chmod(file, 0777)

        # ===============================================================
        # Comment :
        for i in dyn_items:
            json_metadata = i.metadata()

            solver = i.solver_name
            json_recap_dic = {'comment': {}}
            comment = self.tab1_comment.getComment() or None
            if comment:
                json_recap_dic['comment'][solver] = {}
                json_recap_dic['comment'][solver][current_iter] = comment

                if os.path.isfile(json_metadata):
                    dw_json.updateJson(json_metadata, dict(json_recap_dic))
                else:
                    dw_json.saveJson(json_metadata, dict(json_recap_dic))

            # PRESET AUTO SAVE :

            if self.save_preset:
                json_preset_dic = {'preset': {}}
                current_preset = ziva_cmds.get_preset(solver)
                json_preset_dic['preset'][solver] = {}
                json_preset_dic['preset'][solver][current_iter] = current_preset

            if os.path.isfile(json_metadata):
                dw_json.updateJson(json_metadata, dict(json_preset_dic))
            else:
                dw_json.saveJson(json_metadata, dict(json_preset_dic))

        # ===============================================================

        # ===============================================================
        # attach cache
        for i in dyn_items:
            abc = i.alembic_target() + '.filename'
            cmds.setAttr(abc, i.cache_file(0, suffix), type='string')

        # ===============================================================
        if self.edit_mode == 'cache':
            cmds.evalDeferred('dwsimui.cache_tree.build_cache_list()')

    def createCache(self):
        # cacheDir cacheFile()
        dyn_items = self.dyn_eval_tree.selectedItems()
        ncloth = []
        futurdir = []
        tmpdir = ''

        _iter_list = sorted([str(i.get_iter() + 1) for i in dyn_items])
        current_iter = _iter_list[-1]

        if not dyn_items:
            cmds.warning('nothing selected')
            return
        for i in dyn_items:
            shape = i.node
            ncloth.append(shape)
            if tmpdir == '':
                tmpdir = i.cache_dir(0)
            if current_iter != i.get_iter():
                mode = int(current_iter) - i.get_iter()
            else:
                mode = 1 # increment the cache by one
            cachePath = i.cache_file(mode)
            futurdir.append(cachePath)
        for path in futurdir:
            make_dir('/'.join(path.split('/')[:-1]))

        print(cachePath)

        cmds.waitCursor(state=1)
        ncloth_cmds.delete_caches(ncloth)
        cmds.waitCursor(state=0)
        caches = ncloth_cmds.create_cache(ncloth, tmpdir)

        # ===============================================================
        # Comment + preset:
        json_metadata = i.metadata()

        solver = i.solver_name
        json_recap_dic = {'comment': {}}
        comment = self.tab1_comment.getComment() or None
        if comment:
            json_recap_dic['comment'][solver] = {}
            json_recap_dic['comment'][solver][current_iter] = comment

            if os.path.isfile(json_metadata):
                dw_json.updateJson(json_metadata, dict(json_recap_dic))
            else:
                dw_json.saveJson(json_metadata, dict(json_recap_dic))
        # ===============================================================

        # ===============================================================
        # attach cache
        mylist = os.listdir(tmpdir)

        for cache in zip(caches, futurdir, ncloth):
            det = [c for c in mylist if c.startswith(cache[0])]
            for fileName in det:
                src = tmpdir + fileName
                currext = src.split('.')[-1]
                dst = cache[1].replace('.xml', '.' + currext)
                shutil.move(src, dst)
            try:
                cmd = "simtool.ncloth_cmds.attach_ncache('{}', '{}')"
                cmds.evalDeferred(cmd.format(cache[1],
                                             cache[2]))
            except:
                cmds.evalDeferred(
                    "ncloth_cmds.attach_ncache('{}', '{}')".format(cache[1],
                                                                 cache[2]))
        # ===============================================================
        if self.edit_mode == 'cache':
            cmds.evalDeferred('dwsimui.cache_tree.build_cache_list()')

    # GENERAL FUNCTION
    def save_comment(self, comment):
        item = self.dyn_eval_tree.currentItem()
        # ===============================================================
        # Comment :
        json_metadata = item.metadata()
        solver = item.solver_name

        sel_caches = self.cache_tree.cache_tree.selectedItems()

        json_recap_dic = {'comment': {}}
        if comment:
            for cache in sel_caches:
                json_recap_dic['comment'][solver] = {}
                json_recap_dic['comment'][solver][cache.version] = comment

                if os.path.isfile(json_metadata):
                    dw_json.updateJson(json_metadata, dict(json_recap_dic))
                else:
                    dw_json.saveJson(json_metadata, dict(json_recap_dic))
        # ===============================================================

    def set_comment(self):

        _types = ['zSolverTransform', 'nCloth', 'hairSystem']

        if self.edit_mode != 'cache':
            return

        dyn_item = self.dyn_eval_tree.currentItem()
        if not dyn_item:
            self.tab1_comment.setTitle(None)
            self.tab1_comment.setComment(None)
            return
        else:
            if dyn_item.node_type not in _types:
                self.tab1_comment.setTitle(None)
                self.tab1_comment.setComment(None)
                return

        cache_item = self.cache_tree.selected()
        if cache_item:
            name = cache_item.text(0)
            p = re.compile('v([0-9]{3})')
            _iter = str(int(p.search(name).group(0)[1:]))
            solver = dyn_item.solver_name
            metadata = dyn_item.metadata()

            self.tab1_comment.setTitle(dyn_item.short_name)
            self.tab1_comment.setComment('')

            if os.path.isfile(metadata):
                data = dw_json.loadJson(metadata)
                if not solver in data['comment']:
                    return
                if not _iter in data['comment'][solver]:
                    return
                comm = data['comment'][solver][_iter]
                self.tab1_comment.setComment(comm)

    def cache_map_on_change(self):
        mode = self.cb_mode_picker.currentIndex()
        if mode == 0:
            self.edit_mode = 'cache'
        else:
            self.edit_mode = 'maps'

        self.cache_map_sel()

    def cache_map_sel(self):
        # find the current node
        dyn_item = self.dyn_eval_tree.selectedItems()

        if self.edit_mode == 'cache':
            # hide the map, show cache
            self.maps_tree.hide()
            self.cache_tree.show()
            # refresh the cache tree
            self.cache_tree.set_node(dyn_item)
            self.cache_tree.select(0)
            # set comment if there is
            self.set_comment()
        else:
            # show the map, hide cache
            self.cache_tree.hide()
            self.maps_tree.show()
            # refresh the map tree
            self.maps_tree.set_node(dyn_item[0])


    def select(self):
        dyn_item = self.dyn_eval_tree.currentItem()
        if dyn_item.node:
            filter = ['nRigid', 'dynamicConstraint']
            if dyn_item.node_type in filter:
                transform = cmds.listRelatives(dyn_item.node, p=1)
            elif dyn_item.node_type == 'nCloth':
                # transform = cmds.listRelatives(item.node, p=1)
                transform = dyn_item.mesh_transform
            else:
                transform = dyn_item.node
            ncloth_cmds.cmds.select(transform, r=True)

    def guess_sel_tree_item(self, type='nCloth', sel_input=None):

        all_items = get_all_treeitems(self.dyn_eval_tree)
        if type == 'refresh':
            selected = sel_input
        elif type == 'nCloth':
            selected = ncloth_cmds.get_nucleus_sh_from_sel()
        elif type == 'hairSystem':
            selected = ncloth_cmds.get_nucleus_sh_from_sel()
        if selected:
            for item in all_items:
                if item.node == selected:
                    # Auto-select cloth node in the UI
                    self.dyn_eval_tree.setCurrentItem(item)

                    # DW - expand the parents
                    if item.parent():
                        item.parent().setExpanded(True)
                    if item.parent().parent():
                        item.parent().parent().setExpanded(True)
                    return True
        return False

    def build_tree(self):

        self.dyn_eval_tree.clear()

        items = []

        _sys = ncloth_cmds.dw_get_hierarchy()
        for char in _sys.keys():
            # char are the characters name
            char_item = CharacterTreeItem(str(char), self.dyn_eval_tree)
            nucleus_list = ncloth_cmds.sort_list_by_outliner(_sys[char])
            for nucleus in nucleus_list:
                # add nucleus
                tree_nucleus = NucleusTreeItem(nucleus, char_item)
                char_item.addChild(tree_nucleus)

                # ADD CLOTH AND HAIRSYS
                if 'nCloth' in _sys[char][nucleus]:
                    if _sys[char][nucleus]['nCloth']:
                        ncloth_nodes = _sys[char][nucleus]['nCloth']
                        ncloth_list = ncloth_cmds.sort_list_by_outliner(ncloth_nodes)
                        for cloth in ncloth_list:
                            tree_cloth = ClothTreeItem(cloth, tree_nucleus)
                            tree_nucleus.addChild(tree_cloth)

                if 'nHair' in _sys[char][nucleus]:
                    if _sys[char][nucleus]['nHair']:
                        nhair_nodes = _sys[char][nucleus]['nHair']
                        nhair_list = ncloth_cmds.sort_list_by_outliner(nhair_nodes)
                        for cloth in nhair_list:
                            tree_hair = HairTreeItem(cloth, tree_nucleus)
                            tree_nucleus.addChild(tree_hair)

                # ADD NRIGID
                if _sys[char][nucleus]['nRigid']:
                    for nrigid in _sys[char][nucleus]['nRigid']:
                        #tree_rigid = NRigidTreeItem(nrigid, tree_nucleus)
                        tree_rigid = NRigidTreeItem(nrigid, tree_nucleus)
                        tree_nucleus.addChild(tree_rigid)

                #
                #     # charItem.addChild(tree_cloth)
                #
                # for hair in _sys[char][nucleus]['nHair']:
                #     tree_hair = HairTreeItem(hair, tree_nucleus)
                #     # charItem.addChild(tree_hair)

            items.append(char_item)

        ziva_sys = ziva_cmds.rfx_sys()

        for char in ziva_sys.keys():
            # char are the characters name
            char_item = CharacterTreeItem(str(char), self.dyn_eval_tree)
            muscle_list = ziva_sys[char]['muscle']
            if muscle_list:
                muscle_list = ncloth_cmds.sort_list_by_outliner(muscle_list)
                # MUSCLES
                for muscle in muscle_list:
                    tree_fascia = FasciaTreeItem(muscle, char_item)
                    char_item.addChild(tree_fascia)

            skin_list = ziva_sys[char]['skin']
            if skin_list:
                skin_list = ncloth_cmds.sort_list_by_outliner(skin_list)
                # MUSCLES
                for skin in skin_list:
                    tree_skin = SkinTreeItem(skin, char_item)
                    char_item.addChild(tree_skin)

            items.append(char_item)

        self.dyn_eval_tree.addTopLevelItems(items)

    def reconnect(self, signal, newhandler=None, oldhandler=None):
        '''
        NB: the loop is needed for safely disconnecting a specific handler,
            because it may have been connected multple times, and disconnect
            only removes one connection at a time
        '''
        while True:
            try:
                if oldhandler is not None:
                    signal.disconnect(oldhandler)
                else:
                    signal.disconnect()
            except TypeError:
                break
        if newhandler is not None:
            signal.connect(newhandler)


def show_ui():
    if MODE == 0:
        # Create the Qt Application
        app = QtWidgets.QApplication(sys.argv)
        # Create and show the form
        form = DynEvalUI()
        form.show()
        # Run the main Qt loop
        sys.exit(app.exec_())
    else:
        if MODE == 1:
            parent = get_maya_window()
        if MODE == 2:
            parent = get_houdini_window()

        try:
            simtoolui.deleteLater()
        except:
            pass
        simtoolui = DynEvalUI(parent)
        simtoolui.show()
        return simtoolui


class CharacterTreeItem(QtWidgets.QTreeWidgetItem):
    """
    Placeholder item for the character node at the top of the tree.
    Contains character name and optional details like node type and short name.

    Args:
        name (str): Name of the character or item.
        parent (QTreeWidgetItem): Parent item in the QTreeWidget.
    """

    def __init__(self, name, parent):
        super().__init__(parent)

        # Set item font and text
        font = QtGui.QFont()
        font.setBold(True)
        self.setText(0, name)
        self.setFont(0, font)

        # Initialize attributes
        self.name = name
        self.node = None  # Can be linked to a character's node in the scene
        self.node_type = None  # e.g., for specifying types like "rig" or "simulation"
        self.short_name = name.split('|')[-1]  # Optional: just the final part of the name
        self.characterName = name


class ColorTextButton(QtWidgets.QWidget):
    """
    A custom widget with a clickable button overlaid by a text label.
    Args:
        text (str): Text to display on the label.
        parent (QWidget, optional): Parent widget, if any.
    """

    def __init__(self, text, parent=None):
        super().__init__(parent)

        # Main stacked layout
        main_layout = QtWidgets.QStackedLayout()
        main_layout.setStackingMode(QtWidgets.QStackedLayout.StackAll)

        # Label displaying text
        self.label = QtWidgets.QLabel(text)
        self.label.setAlignment(QtCore.Qt.AlignCenter)

        # Button overlay
        self.button = QtWidgets.QPushButton()
        self.button.setStyleSheet("background-color: rgba(121, 121, 121, 60);")

        # Add to layout
        main_layout.addWidget(self.label)
        main_layout.addWidget(self.button)
        self.setLayout(main_layout)

    def clicked(self, function):
        """
        Connect a function to the button's clicked signal.
        Args:
            function (callable): Function to call on button click.
        """
        self.button.clicked.connect(function)

    def setStyleSheet(self, style):
        """
        Apply a stylesheet to the button.
        Args:
            style (str): Stylesheet string to apply.
        """
        self.button.setStyleSheet(style)


class MapEdit(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        # Main layout
        main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(main_layout)

        # Radio buttons for choosing edit mode
        self.rbVtxRange = QtWidgets.QRadioButton("Range")
        self.rbVtxRange.setChecked(True)
        main_layout.addWidget(self.rbVtxRange)

        self.rbVtxValue = QtWidgets.QRadioButton("Value")
        main_layout.addWidget(self.rbVtxValue)

        # Widget range selection
        self.range_layout = QtWidgets.QHBoxLayout()

        self.leMinRange = QtWidgets.QLineEdit()
        self.leMaxRange = QtWidgets.QLineEdit()

        self.range_layout.addWidget(QtWidgets.QLabel("Min:"))
        self.range_layout.addWidget(self.leMinRange)
        self.range_layout.addWidget(QtWidgets.QLabel("Max:"))
        self.range_layout.addWidget(self.leMaxRange)

        main_layout.addLayout(self.range_layout)

        # Update range visibility based on selection
        self.rbVtxRange.toggled.connect(self.update_range_visibility)
        self.rbVtxValue.toggled.connect(self.update_range_visibility)

        # Initialize visibility
        self.update_range_visibility()

    def update_range_visibility(self):
        """
        Toggle visibility of min and max range line edits based on radio selection.
        """
        is_range_mode = self.rbVtxRange.isChecked()
        self.leMinRange.setVisible(is_range_mode)
        self.leMaxRange.setVisible(is_range_mode)

# try:
#     ex.deleteLater()
# except:
#     pass
# ex = DynEvalUI()
# ex.show()

