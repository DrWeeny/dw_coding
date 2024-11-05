import sys, os
# ----- Edit sysPath -----#
rdPath = '/user_data/AMJB/coding/dw_tools/maya/DNEG2'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)
import re
import shutil

from . import sim_widgets
import dw_json

MODE = 0

try:
    import hou
    from PySide2 import QtWidgets, QtGui, QtCore

    MODE = 2
except:
    pass

if not MODE > 0:
    try:
        import maya.cmds as cmds
        from PySide2 import QtWidgets, QtGui, QtCore
        import maya.OpenMayaUI as omui
        import shiboken2

        from . import ncloth_cmds
        from SimTool.dendrology.nucleus_tree import *
        # from SimTool.dendrology.rfx_nucleus_tree import *
        from SimTool.dendrology.cache_tree import *
        import sim_widget

        MODE = 1
    except:
        pass

if MODE == 0:
    from PySide2 import QtWidgets, QtCore, QtGui

# ====================================================================
# WINDOW GETTER
# ====================================================================

def get_maya_window():
    """
    Get maya main window
    Returns:
        pointer

    """
    return shiboken2.wrapInstance(long(omui.MQtUtil.mainWindow()),
                                  QtWidgets.QWidget)

def get_houdini_window():
    """
    get houdini window
    Returns:
        pointer

    """
    win = hou.ui.mainQtWindow()
    return win


def make_dir(path):
    """
    create the full path if it is not existing
    :return: <<str>> path string
    """
    if not os.path.exists(path):
        os.makedirs(path)
    return path


def get_all_treeitems(QTreeWidget):
    """ Get all QTreeWidgetItem of given QTreeWidget
        :param QTreeWidget: QTreeWidget object
        :type QTreeWidget: QtGui.QTreeWidget
        :return: All QTreeWidgetItem list
        :rtype: list """
    items = []
    iterator = QtWidgets.QTreeWidgetItemIterator.All
    all_items = QtWidgets.QTreeWidgetItemIterator(QTreeWidget,
                                                 iterator) or None
    if all_items is not None:
        while all_items.value():
            item = all_items.value()
            items.append(item)
            all_items += 1
    return items


class SimUI(QtWidgets.QMainWindow):

    """
    The Sim UI embed a unified way to simulate different type of solvers
    """

    def __init__(self, parent=None):
        super(SimUI, self).__init__(parent)
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

        vl_cachemap.setStretch(0)

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

        self.dyn_eval_tree.itemClicked.connect(self.cache_map_sel)
        self.dyn_eval_tree.itemDoubleClicked.connect(self.select)
        # Mode Select
        self.cb_mode_picker.currentIndexChanged.connect(self.cache_map_on_change)

        self.cache_tree.cache_tree.itemClicked.connect(self.set_comment)

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

        menu.exec_(self.dyn_eval_tree.viewport().mapToGlobal(position))

    def createCache(self):
        # cacheDir cacheFile()
        dyn_items = self.dyn_eval_tree.selectedItems()
        ncloth = []
        futurdir = []
        tmpdir = ''
        if not dyn_items:
            cmds.warning('nothing selected')
            return
        for i in dyn_items:
            shape = i.node
            ncloth.append(shape)
            if tmpdir == '':
                tmpdir = i.cacheDir(0)
            cachePath = i.cacheFile()
            futurdir.append(cachePath)
        for path in futurdir:
            make_dir('/'.join(path.split('/')[:-1]))

        print(cachePath)

        cmds.waitCursor(state=1)
        ncloth_cmds.delete_caches(ncloth)
        cmds.waitCursor(state=0)
        caches = ncloth_cmds.create_cache(ncloth, tmpdir)

        mylist = os.listdir(tmpdir)

        # ===============================================================
        # Comment :
        json_metadata = i.metadata()
        current_iter = str(i.get_iter() + 1)
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
            self.cache_tree.build_cache_list()

    # GENERAL FUNCTION
    def set_comment(self):

        if self.edit_mode != 'cache':
            return

        dyn_item = self.dyn_eval_tree.currentItem()
        if not dyn_item:
            self.tab1_comment.setTitle(None)
            self.tab1_comment.setComment(None)
            return
        else:
            if dyn_item.node_type not in ['nCloth', 'hairSystem']:
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
        dyn_item = self.dyn_eval_tree.currentItem()

        if self.edit_mode == 'cache':
            # hide the map, show cache
            self.maps_tree.hide()
            self.cache_tree.show()
            # refresh the cache tree
            self.cache_tree.set_node(dyn_item)
            # set comment if there is
            self.set_comment()
        else:
            # show the map, hide cache
            self.cache_tree.hide()
            self.maps_tree.show()
            # refresh the map tree
            self.maps_tree.set_node(dyn_item)

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
            for nucleus in _sys[char]:
                # add nucleus
                tree_nucleus = NucleusTreeItem(nucleus, char_item)
                char_item.addChild(tree_nucleus)

                # ADD CLOTH AND HAIRSYS
                if 'nCloth' in _sys[char][nucleus]:
                    if _sys[char][nucleus]['nCloth']:
                        for cloth in _sys[char][nucleus]['nCloth']:
                            tree_cloth = ClothTreeItem(cloth, tree_nucleus)
                            tree_nucleus.addChild(tree_cloth)

                if 'nHair' in _sys[char][nucleus]:
                    if _sys[char][nucleus]['nHair']:
                        for cloth in _sys[char][nucleus]['nHair']:
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
        form = SimUI()
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
        simtoolui = SimUI(parent)
        simtoolui.show()
        return simtoolui


class CharacterTreeItem(QtWidgets.QTreeWidgetItem):
    '''
    placeHolder on top of the tree
    will have description of the character icons or info
    this is builded auto for shots but not in rig scene
    '''

    def __init__(self, name, parent):
        '''
        parent (QTreeWidget) : Item's QTreeWidget parent.
        name   (str)         : Item's name. just an example.
        '''

        ## Init super class ( QtGui.QTreeWidgetItem )
        QtWidgets.QTreeWidgetItem.__init__(self, parent)

        font = QtGui.QFont()
        font.setBold(True)
        self.setText(0, name)
        self.setFont(0, font)
        self.name = name
        self.node = None
        self.node_type = None
        self.short_name = name
        self.characterName = name


class ColorTextButton(QtWidgets.QWidget):

    def __init__(self, text, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        _main = QtWidgets.QStackedLayout()
        _main.setStackingMode(QtWidgets.QStackedLayout.StackAll)
        _lb = QtWidgets.QLabel(text)
        _lb.setGeometry(0, 0, 200, 10)
        self.button = QtWidgets.QPushButton()
        self.button.setGeometry(0, 0, 200, 10)
        self.button.setStyleSheet("background-color:rgba(121, 121, 121, 60);")
        _main.addWidget(_lb)
        _main.addWidget(self.button)
        self.setGeometry(0, 0, 200, 10)
        # _main.setMargin(25)
        self.setLayout(_main)

    @property
    def clicked(self):
        return self.button.clicked

    @property
    def setStyleSheet(self):
        return self.button.setStyleSheet

class MapEdit(QtWidgets.QWidget):

    def __init__(self):
        QtWidgets.QWidget.__init__(self)
        _vl_main = QtWidgets.QVBoxLayout()

        self.rbVtxRange = QtWidgets.QRadioButton("Range")
        self.rbVtxRange.setChecked(True)
        _vl_main.addWidget(self.rbVtxRange)

        self.rbVtxValue = QtWidgets.QRadioButton("Value")
        self.rbVtxValue.setChecked(True)
        _vl_main.addWidget(self.rbVtxValue)

        # Widget select range
        _hl_range = QtWidgets.QHBoxLayout()
        _hl_rangeMax = QtWidgets.QHBoxLayout() # this layout is used to hide maxRange lineEdit

        self_leMinRange = QtWidgets.QLineEdit()
        self_leMaxRange = QtWidgets.QLineEdit()

        _hl_rangeMax.addWidget(self._leMaxRange)



# try:
#     ex.deleteLater()
# except:
#     pass
# ex = SimUI()
# ex.show()

