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
import maya.cmds as cmds

# external
from . import ziva_leaf as zl
import dw_maya_utils as dwu

#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#

def rfx_set_filerule():
    fileRule = "fileCache"
    location = "cache/alembic"
    seq = os.environ['SEQ_NAME']
    shot = os.environ['SHOT_NAME']
    location += '/{}/{}'.format(seq, shot)

    ruleLocation = cmds.workspace(fileRuleEntry=fileRule)
    cmds.workspace(fileRule=[fileRule, location])

class ZSolverTreeItem(zl.ZSolverTreeItem):

    def __init__(self, name, parent=None, pattern=None):
        # nt.NucleusTreeItem.__init__(self, name, parent)
        super(ZSolverTreeItem, self).__init__(name, parent)

    @property
    def short_name(self):
        try:
            p = cmds.listRelatives(self.node, p=True)[0]
        except:
            p = self.node

        return p.split('|')[-1].split(':')[-1].rsplit('_', 1)[0]

    def set_filerule(self):
        rfx_set_filerule()


class FasciaTreeItem(ZSolverTreeItem):

    def __init__(self, solver, parent=None, pattern=None):
        super(FasciaTreeItem, self).__init__(solver, parent, pattern)

    @property
    def mesh_transform(self):

        hist = cmds.listHistory(self.solver,
                        breadthFirst=True,
                        future=True,
                        allFuture=True)
        zhist_tr = dwu.lsTr(hist)
        if not self.patt:
            self.patt = re.compile(':fascia_TISSUE$')
        fascia = [h for h in zhist_tr if self.patt.search(h)]

        return fascia[0]

    def alembic_target(self):
        ns = self.get_ns(self.node)
        target = ns + ':fasciaCacheDeformer'
        return target


class SkinTreeItem(ZSolverTreeItem):

    def __init__(self, solver, parent=None, pattern=None):
        super(SkinTreeItem, self).__init__(solver, parent, pattern)

    @property
    def mesh_transform(self):

        hist = cmds.listHistory(self.solver,
                        breadthFirst=True,
                        future=True,
                        allFuture=True)
        zhist_tr = dwu.lsTr(hist)
        if not self.patt:
            self.patt = re.compile(':midskin_REN$')
        fascia = [h for h in zhist_tr if self.patt.search(h)]

        return fascia[0]

    def alembic_target(self):
        ns = self.get_ns(self.node)
        target = ns + ':skinCacheDeformer'
        return target

