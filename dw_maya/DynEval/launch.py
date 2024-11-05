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
import importlib

#ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

# Import UI modules
try:
    import DynEval.main_ui as simtool
    import DynEval.ncloth_cmds
    import DynEval.sim_widgets
except ImportError as e:
    print(f"Error importing simulation tool modules: {e}")
    raise

# Reload for Development Purposes
for module in (simtool, simtool.ncloth_cmds, simtool.sim_widgets):
    importlib.reload(module)


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#
try:
    ex.deleteLater()
except:
    pass
ex = simtool.SimUI()
ex.show()
