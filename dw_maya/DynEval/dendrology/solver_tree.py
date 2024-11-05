#!/usr/bin/env python
#----------------------------------------------------------------------------#
#------------------------------------------------------------------ HEADER --#

"""
@author:
    abtidona

@description:
    this is a description

@applications:
    - groom
    - cfx
    - fur
"""

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#

# built-in
import sys, os
# ----- Edit sysPath -----#
rdPath = '/user_data/AMJB/coding/dw_tools/maya/DNEG2'
if not os.path.isdir(rdPath):
    rdPath = '/people/abtidona/public/dw_tools/maya/'
if not rdPath in sys.path:
    print "Add %r to sysPath" % rdPath
    sys.path.insert(0, rdPath)

# internal
from PySide2 import QtWidgets, QtCore, QtGui
# external

class SolverNode(object):

    """
    used to fill the model with any hierarchy of items

    Args:
        name (str): name of the node
        _type (str): type of tree item "character", "solver", "ncloth"...
        parent (object): SolverNode

    """

    def __init__(self, name, _type, parent=None):
        self._name = name
        self._node = _type
        self._children = []
        self._type = []
        # parent is Solver Node, it is the top item
        self._parent = parent

        if parent is not None:
            parent.add_child(self)

    def add_child(self, child, _type=None):
        self._children.append(child)
        self._type.append(_type)

    def name(self):
        return self._name

    def node(self):
        return self._node

    def child(self, row):
        return self._children[row]

    def node_type(self, row):
        return self._type[row]

    def child_count(self):
        return len(self._children)

    def parent(self):
        return self._parent

    def row(self):
        if self._parent is not None:
            return self._parent._children.index(self)

    def print_tree(self, tab_level=-1, _type=False):

        output = ""
        tab_level +=1

        for i in range(tab_level):
            output += "\t"
        if _type:
            output += "|======" + self._node + "\n"
        else:
            output += "|======" + self._name + "\n"

        for child in self._children:
            output += child.log(tab_level)

        tab_level -=1
        output += "\n"

        return output

    def __repr__(self):
        return self.print_tree()

#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#

class SolverModel(QtCore.QAbstractItemModel):

    imgpath = rdPath + '/../../ressources/pic_files'
    if not os.path.isdir(imgpath):
        imgpath = rdPath + '/../ressources/pic_files'

    onIcon = QtGui.QIcon(os.path.join(imgpath, 'on.png'))
    offIcon = QtGui.QIcon(os.path.join(imgpath, 'off.png'))
    textColor = {'nucleus': (194, 177, 109),
                 'nCloth': (224, 255, 202),
                 'nRigid': (0, 150, 255),
                 'hairSystem': (237, 150, 0),
                 'nConstraint': ''}
    iconList = {'nucleus': '',
                'nCloth': os.path.join(imgpath, 'ncloth.png'),
                'hairSystem': os.path.join(imgpath, 'nhair.png'),
                'nRigid': os.path.join(imgpath, 'collider.png'),
                'nConstraint': os.path.join(imgpath, 'nconstraint.png')}

    def __init__(self, root=object, parent=None):

        """

        Args:
            asset_names:
            _type:
            parent:

            asset_names = {'winnie' :
                                    {solver_name :
                                                [item_to_cache]}
                                                                }
        """


        super(SolverModel, self).__init__(parent)
        self.root_node = root

    def rowCount(self, parent):
        pass

    def columnCount(self, parent):
        pass

    def parent(self, index):
        node = index.internalPointer()
        parent_node = node.parent()

        if parent_node == self.root_node:
            return QtCore.QModelIndex()

        return self.createIndex(parent_node.row(),
                                 0,
                                 parent_node)

    def index(self, row, column, parent):
        pass

    def headerData(self, section, orientation, role):
        # in thi smethod we set the header

        if role == QtCore.Qt.DisplayRole:
            if orientation == QtCore.Qt.Horizontal:
                if not section:
                    return "Name"
                else:
                    return "I/O"
            else:
                return ""

    def data(self, index, role):
        # display data

        # if role == ToolTipRole

        if role == QtCore.Qt.DecorationRole:
            # will display the icon
            row = index.row()
            if self.asset_type in self.iconList:

                icon_path = self.iconList[self.asset_type]
                icon = QtGui.QIcon(icon_path)
                return icon
            return

        if role == QtCore.Qt.DisplayRole:
            row = index.row()
            column = index.column()
            if column == 0:
                value = self.__names[row]
                return value

        if role == QtCore.Qt.EditRole:
            row = index.row()
            column = index.column()
            if column == 0:
                return self.__names[row]
    """
    def flags(*args, **kwargs):
        # method for editable
        return QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable

    def setData(self, index, value, role=QtCore.Qt.EditRole):

        if role == QtCore.Qt.EditRole:
            row = index.row()
            # do ome update here
            self.dataChanged.emit(index, index)
            return True
        return False
    def insertRows(self, position, rows, parent):
        self.beginInsertRows(index=QtCore.QModelIndex(),
                             first=position, 
                             last=position + rows-1)

        # do insert
        for i in range(rows):
            self.__names.insert(position, "character_name")
        self.endInsertRows()
        return True

    def removeRows(self, position, rows, parent):
        self.beginRemoveRows()
        # remove
        for i in range(rows):
            value = self.__names[position]
            self.__names.remove(value)
        self.endRemoveRows()
        return True
    """

model = QtCore.QAbstractItemModel()
solver_tree = QtWidgets.QTreeView()

