import sys, os
# ----- Edit sysPath -----#
import re

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from PySide2 import QtWidgets, QtGui, QtCore
from dw_maya.DynEval import ncloth_cmds, ziva_cmds


class CacheItem(QtWidgets.QTreeWidgetItem):
    '''
    Custom QTreeWidgetItem with Widgets
    '''

    color_maya_blue = QtGui.QColor(68, 78, 88)
    dark_geo_red = QtGui.QColor(128, 18, 18)
    dark_ncloth_green = QtGui.QColor(29, 128, 18)
    dark_abc_purple = QtGui.QColor(104, 66, 129)

    def __init__(self, name, cache_node, path, attached=False,
                       isvalid=True, _type='nCache', parent=None):
        '''
        parent (QTreeWidget) : Item's QTreeWidget parent.
        name   (str)         : Item's name. just an example.
        '''

        ## Init super class ( QtGui.QTreeWidgetItem )
        QtWidgets.QTreeWidgetItem.__init__(self, parent)

        self.setText(0, name)
        self.is_attached = attached

        # COLOR SETUP :
        if _type == 'nCache':
            self.color = self.dark_ncloth_green
        elif _type == 'geoCache':
            self.color = self.dark_geo_red
        elif _type == 'alembic':
            self.color = self.dark_abc_purple
        else:
            self.color = self.color_maya_blue

        self.cache_type = _type

        gradient = QtGui.QLinearGradient(0, 0, 0, 200)
        gradient.setColorAt(0.0, self.color)
        gradient.setColorAt(.2, QtGui.QColor(50, 50, 50, 0))

        if attached:
            self.set_attached()
        else:
            self.set_color()

        if isvalid:
            imgpath = rdPath + '../../ressources/pic_files'
            icon = QtGui.QIcon(os.path.join(imgpath, 'cache_approved.png'))
            self.setIcon(0, icon)


        self.path = path
        self.node = cache_node
        self.comment = ''

        if ncloth_cmds.cmds.nodeType(self.node) in ['zSolver',
                                                   'zSolverTransform']:
            self.mesh = None
        elif ncloth_cmds.cmds.nodeType(self.node) != 'hairSystem':
            self.mesh = ncloth_cmds.get_ncloth_mesh(cache_node)

    def set_attached(self):
        brush = QtGui.QBrush(self.color_maya_blue)
        brush.setStyle(QtCore.Qt.SolidPattern)
        self.setBackground(0, brush)
        self.is_attached = True

        font = QtGui.QFont()
        font.setPointSize(10)
        self.setFont(0, font)

    def set_color(self):
        brush = QtGui.QBrush(self.color)
        brush.setStyle(QtCore.Qt.SolidPattern)
        self.setBackground(0, brush)
        self.is_attached = False

        font = QtGui.QFont()
        font.setPointSize(8)
        self.setFont(0, font)

    @property
    def version(self):
        _file = self.path.split('/')[-1]
        p = re.compile('_v(\d{3})\.')
        r = p.search(_file)
        if r:
            return int(r.group(1))
