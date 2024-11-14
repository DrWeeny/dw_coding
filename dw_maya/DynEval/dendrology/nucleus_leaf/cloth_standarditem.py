#!/usr/bin/env python
# ----------------------------------------------------------------------------#
# ------------------------------------------------------------------ HEADER --#

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

# ----------------------------------------------------------------------------#
# ----------------------------------------------------------------- IMPORTS --#

# built-in
import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

import re
from pathlib import Path


# internal
from PySide6 import QtCore, QtGui, QtWidget
from maya import cmds
from .base_standarditem import BaseSimulationItem
from dw_maya.DynEval import ncloth_cmds


class ClothTreeItem(BaseSimulationItem):
    """Tree item for cloth simulation nodes."""

    def __init__(self, name):
        super().__init__(name)
        self.setText(self.short_name)

        self.setData(self.state, QtCore.Qt.UserRole + 3)  # Toggle state data

    @property
    def short_name(self):
        """Display-friendly name."""
        return self.node.split('|')[-1].split(':')[-1].split('_cloth')[0]

    @property
    def state_attr(self):
        """Simulation state attribute."""
        return 'isDynamic'

    def cache_dir(self, mode=1):
        """Get cache directory path."""
        base_dir = Path(cmds.workspace(fileRuleEntry='fileCache')).resolve()
        sub_dir = Path(self.namespace, self.solver_name, self.short_name)
        return (base_dir / ('dynTmp' if mode == 0 else sub_dir)).as_posix()

    def cache_file(self, mode=1, suffix=''):
        """Construct cache filename."""
        iteration = self.get_iter() + mode
        suffix_text = f"_{suffix}" if suffix else ""
        cache_filename = f"{self.short_name}{suffix_text}_v{iteration:03d}.xml"
        return (Path(self.cache_dir()) / cache_filename).as_posix()

    def has_cache(self):
        """Check if the cache exists for the node."""
        # Custom logic based on requirements
        pass

    def get_cache_list(self):
        """List all available cache files."""
        path = Path(self.cache_dir())
        return sorted([file.stem for file in path.glob('*.xml')]) if path.exists() else []

    def get_iter(self):
        """Determine current cache iteration/version."""
        path = Path(self.cache_dir())
        if path.exists():
            versions = [int(file.stem.split('_v')[-1]) for file in path.glob('*.xml')]
            return max(versions, default=0)
        return 0

    def get_maps(self):
        """Retrieve available vertex maps for the node."""
        return ncloth_cmds.get_vtx_maps(self.node)

    def get_maps_mode(self):
        """Retrieve vertex map modes for each map."""
        return [ncloth_cmds.get_vtx_map_type(self.node, f"{map_name}MapType") for map_name in self.get_maps()]

