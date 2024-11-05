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
import re

# internal
from maya import cmds, mel
from PySide2 import QtWidgets, QtGui, QtCore

# external
import dw_maya_utils as dwu

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#


#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#

class ZSolverTreeItem(QtWidgets.QTreeWidgetItem):

    # on and off icon should be above

    imgpath = rdPath + '/../../ressources/pic_files'
    if not os.path.isdir(imgpath):
        imgpath = rdPath + '/../ressources/pic_files'

    onIcon = QtGui.QIcon(os.path.join(imgpath, 'on.png'))
    offIcon = QtGui.QIcon(os.path.join(imgpath, 'off.png'))

    textColor = {'zSolverTransform': (194, 177, 109),
                 'zMaterial': (224, 255, 202),
                 'zAttachment': (0, 150, 255),
                 'zTet': (237, 150, 0)}

    iconList = {'zSolverTransform': '',
                 'zMaterial': '',
                 'zAttachment': '',
                 'zTet': ''}

    def __init__(self, name, parent=None, pattern=None):
        super(ZSolverTreeItem, self).__init__(parent)

        ## Column 0 - Text:

        if cmds.ls(name, type='zSolver'):
            self.node = cmds.listRelatives(name, p=True)[0]
        else:
            self.node = name

        b = QtGui.QBrush(self.node_color)
        self.setText(0, self.short_name)
        self.setForeground(0, b)
        self.setIcon(0, self.node_icon)

        ## Column 1 - picker pixmap:
        self.btn_state = QtWidgets.QPushButton()
        self.btn_state.setStyleSheet("background-color:rgba(1, 1, 1, 0);")

        self.btn_state.setGeometry(20, 20, 20, 20)
        self.set_state(self.state)
        # self.btn_state.setIconSize(QtCore.QSize(20, 20))
        self.treeWidget().setItemWidget(self, 1, self.btn_state)

        ## Signals
        self.btn_state.clicked.connect(self.button_pressed)

        self.solver_name = name
        self.namespace = self.get_ns(name)

    def get_ns(self, node_name):

        if ':' in node_name:
            return node_name.split(':')[0].split('|')[-1]
        else:
            return ''

    @property
    def short_name(self):
        try:
            p = cmds.listRelatives(self.node, p=True)[0]
        except:
            p = self.node

        return p.split('|')[-1].split(':')[-1]

    @property
    def short_solver(self):

        n = self.solver_name.split('|')[-1].split(':')[-1].replace('Shape', '')
        return n

    @property
    def state_attr(self):
        if cmds.getAttr('{}.enable'.format(self.node), se=True):
            return 'enable'
        else:
            # in dneg pipeline, it is visibility
            poss = cmds.listConnections('{}.enable'.format(self.node), p=1)
            for i in poss:
                if cmds.getAttr(i, se=True):
                    return i.split('.')[-1]

    @property
    def state(self):
        return cmds.getAttr('{}.{}'.format(self.node, self.state_attr))

    @property
    def node_type(self):
        return cmds.nodeType(self.node)

    @property
    def node_color(self):
        rgb = self.textColor[self.node_type]
        return QtGui.QColor(*rgb)

    @property
    def node_icon(self):
        iconPath = self.iconList[self.node_type]
        return QtGui.QIcon(iconPath)

    def set_state(self, state):
        cmds.setAttr('{}.{}'.format(self.node, self.state_attr), state)
        if state:
            self.btn_state.setIcon(self.onIcon)
        else:
            self.btn_state.setIcon(self.offIcon)
        self.btn_state.setIconSize(QtCore.QSize(20, 20))

    def button_pressed(self):
        '''
        Triggered when Item's button pressed.
        an example of using the Item's own values.
        '''
        self.set_state(abs(self.state - 1))

    def set_filerule(self):

        fileRule = "fileCache"
        location = "cache/ziva"

        ruleLocation = cmds.workspace(fileRuleEntry=fileRule)
        cmds.workspace(fileRule=[fileRule, location])

    def metadata(self, mode=1):
        '''
        used to store which cache is starred
        used to store comments
        used to set attach ones
        '''

        self.set_filerule()

        directory = cmds.workspace(fileRuleEntry='fileCache')
        directory = cmds.workspace(en=directory)
        if mode == 0:
            return directory + '/dynTmp/'

        directory += "/{}/{}/metadata.json".format(self.namespace,
                                                   self.short_solver)
        return directory.replace('//', '/')

    def cache_dir(self, mode=1):
        '''
        :return: str '../cache/ncache/nucleus/cloth/'
        '''

        self.set_filerule()
        directory = cmds.workspace(fileRuleEntry='fileCache')
        directory = cmds.workspace(en=directory)
        if mode == 0:
            return directory+'/dynTmp/'

        directory += "/{}/{}/{}/".format(self.namespace,
                                         self.short_solver,
                                         self.short_name)
        return directory.replace('//', '/')

    def cache_file(self, mode=1, suffix=''):
        '''

        :param mode: <<int>> 0=replace, 1=create
        :param suffix: <<str>>
        :return:
        '''
        path = self.cache_dir()
        iter = self.get_iter() + mode

        if suffix and suffix != '':
            path += self.short_name + '_' + suffix + '_v{:03d}.abc'.format(iter)
        else:
            path += self.short_name + '_' + '_v{:03d}.abc'.format(iter)

        return path.replace('__', '_')

    def get_cache_list(self):
        '''
        list all the caches already done
        :return: <<list>> of file
        '''
        path = self.cache_dir()
        if os.path.exists(path):
            files = os.listdir(path)
            cache = [x.replace('.abc', '') for x in files if x.endswith('.abc')]
            return sorted(cache)
        else:
            return None

    def get_iter(self):
        '''
        get current version number
        :return: <<int>>
        '''
        if os.path.exists(self.cache_dir()):
            output = os.listdir(self.cache_dir())
            if not output:
                return 0
            xml = [i for i in output if i.endswith('.abc')]
            pattern = 'v([0-9]{3})'
            iter = sorted([int(re.findall(pattern, i)[0]) for i in xml])[-1]
            return iter
        else:
            return 0

    @property
    def mesh_transform(self):

        hist = cmds.listHistory(self.solver_name,
                                breadthFirst=True,
                                future=True,
                                allFuture=True)
        zhist_tr = dwu.lsTr(hist)
        if self.patt:
            self.patt = re.compile(':fascia_TISSUE$')
            mesh = [h for h in zhist_tr if self.patt.search(h)]
        else:
            mesh = [h for h in zhist_tr if cmds.ls(h, dag=True, type='mesh')]

        return mesh[0]

    def get_meshes(self):
        zs = cmds.ls(self.solver_name, dag=True, type='zSolver')
        hist = cmds.listHistory(zs, future=True, bf=True, af=True)
        msh_exp = [h for h in hist if cmds.ls(h, dag=True, ni=True, type='mesh')]
        return msh_exp
