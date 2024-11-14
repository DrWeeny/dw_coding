from pathlib import Path
from PySide6 import QtWidgets, QtGui, QtCore
from maya import cmds
import re
import dw_maya.dw_maya_utils as dwu


class ZivaBaseItem(QtGui.QStandardItem):
    """Base class for Ziva simulation items in the model-based structure."""

    def __init__(self, node, icon_paths, color_map):
        super().__init__(node)
        self.node = node
        self.icon_paths = icon_paths  # Dictionary with paths to icons
        self.color_map = color_map  # Dictionary mapping node types to colors
        self.setEditable(False)

        # Set display properties
        self.setText(self.short_name)
        self.setForeground(QtGui.QBrush(self.node_color))
        self.setIcon(self.node_icon)

    @property
    def short_name(self):
        return self.node.split('|')[-1].split(':')[-1]

    @property
    def node_type(self):
        return cmds.nodeType(self.node)

    @property
    def node_color(self):
        return QtGui.QColor(*self.color_map.get(self.node_type, (200, 200, 200)))

    @property
    def node_icon(self):
        return QtGui.QIcon(self.icon_paths.get(self.node_type, ""))

    @property
    def state_attr(self):
        if cmds.getAttr(f'{self.node}.enable', se=True):
            return 'enable'
        return 'visibility'

    @property
    def state(self):
        return cmds.getAttr(f'{self.node}.{self.state_attr}')

    def toggle_state(self):
        new_state = not self.state
        cmds.setAttr(f'{self.node}.{self.state_attr}', new_state)
        self.update_icon_state(new_state)

    def update_icon_state(self, state):
        self.setIcon(QtGui.QIcon(self.icon_paths['on' if state else 'off']))


class ZSolverTreeItem(ZivaBaseItem):
    """Tree item for Ziva solver-specific nodes."""

    def __init__(self, node, icon_paths, color_map, cache_dir):
        super().__init__(node, icon_paths, color_map)
        self.cache_dir = cache_dir
        self.setText(self.short_name)

    def get_cache_file(self, suffix='', iteration=0):
        suffix = f'_{suffix}' if suffix else ''
        return self.cache_dir / f"{self.short_name}{suffix}_v{iteration:03d}.abc"

    def get_next_iteration(self):
        files = list(self.cache_dir.glob(f"{self.short_name}_v*.abc"))
        versions = [int(f.stem.split('_v')[-1]) for f in files if '_v' in f.stem]
        return max(versions, default=0) + 1

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


