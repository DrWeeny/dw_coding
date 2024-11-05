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
from . import nucleus_leaf as nt

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#


#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

class NucleusTreeItem(nt.NucleusTreeItem):

    def __init__(self, name, parent):
        # nt.NucleusTreeItem.__init__(self, name, parent)
        super(NucleusTreeItem, self).__init__(name, parent)


class ClothTreeItem(nt.ClothTreeItem):

    def __init__(self, name, parent):
        # nt.ClothTreeItem.__init__(self, name, parent)
        # NucleusTreeItem.__init__(self, name, parent)
        super(ClothTreeItem, self).__init__(name, parent)

    @property
    def short_name(self):
        '''
        a nice string to not make pollution in the ui
        :return: str
        '''

        shortname = self.node.split('|')[-1].split(':')[-1].split('_cloth')[0]
        return shortname

class HairTreeItem(nt.HairTreeItem):
    def __init__(self, name, parent):
        # nt.ClothTreeItem.__init__(self, name, parent)
        super(HairTreeItem, self).__init__(name, parent)

    @property
    def short_name(self):
        '''
        a nice string to not make pollution in the ui
        :return: str
        '''
        name = self.node.split('|')[-1].split(':')[-1].split('_hairsys')[0]
        numberDetection = re.findall('\d+', self.node.split('_hairsys')[-1])
        name = name.split('_furball')[0]
        if numberDetection:
            name = name + numberDetection[0]
        return name



