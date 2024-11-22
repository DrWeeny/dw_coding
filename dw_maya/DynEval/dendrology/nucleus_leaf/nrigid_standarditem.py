import re
import os
# internal
from PySide6 import QtCore, QtGui, QtWidgets
import maya.cmds as cmds

# external
from .base_standarditem import BaseSimulationItem
from dw_maya.DynEval import sim_cmds
import dw_maya.dw_maya_utils as dwu
from dw_logger import get_logger

logger = get_logger()

class NRigidTreeItem(BaseSimulationItem):
    """Item class for nRigid simulation nodes."""

    def __init__(self, name):
        super().__init__(name)
        self.setText(self.short_name)
        self.setIcon(QtGui.QIcon("path/to/rigid_icon.png"))

        self._setup_item()


    @property
    def short_name(self):
        """Returns a clean short name without suffixes for better readability."""
        transform = dwu.lsTr(self.node)
        if transform:
            shortname = transform[0].split('|')[-1].split(':')[-1].split('_collider')[0]
            shortname = re.sub(r'_nRigid(Shape)?\d+$', '', shortname)
        else:
            shortname = self.node.split('|')[-1].split(':')[-1].split('_collider')[0]
            shortname = re.sub(r'_nRigid(Shape)?\d+$', '', shortname)

        return shortname

    @property
    def mesh_transform(self):
        """Gets the associated mesh transform for the nRigid node."""
        connected_meshes = [
            i for i in cmds.listConnections(f"{self.node}.inputMesh", sh=True)
            if cmds.nodeType(i) == 'mesh' and len(i.split('.')) == 1
        ]
        return dwu.lsTr(connected_meshes[0], long=True)[0] if connected_meshes else None

    @property
    def state_attr(self):
        """Override to use correct attribute for nRigid."""
        return 'isDynamic'

    def set_state(self, state: bool) -> None:
        """Set nRigid dynamic state."""
        try:
            cmds.setAttr(f"{self.node}.{self.state_attr}", state)
            super().set_state(state)

        except Exception as e:
            print(f"NRIGID ERROR: Failed to set state: {e}")
            logger.error(f"Failed to set state for nRigid {self.node}: {e}")
            raise


    def cache_dir(self, mode=1):
        """Returns the directory path for cache files."""
        base_dir = cmds.workspace(fileRuleEntry='fileCache')
        cache_subdir = f"/{self.namespace}/{self.solver_name}/{self.short_name}/"
        return os.path.join(base_dir, 'dynTmp' if mode == 0 else cache_subdir).replace('//', '/')

    def cache_file(self, mode=1, suffix=''):
        """Generates the file path for the cache file based on the iteration."""
        path = self.cache_dir()
        iteration = self.get_iter() + mode
        suffix_text = f'_{suffix}' if suffix else ''
        cache_file = f"{self.short_name}{suffix_text}_v{iteration:03d}.xml"
        return os.path.join(path, cache_file).replace('__', '_')

    def get_cache_list(self):
        """Lists all existing cache files."""
        path = self.cache_dir()
        return sorted(
            [file.replace('.xml', '') for file in os.listdir(path) if file.endswith('.xml')],
            reverse=True
        ) if os.path.exists(path) else []

    def get_iter(self):
        """Retrieves the latest iteration version number."""
        path = self.cache_dir()
        if os.path.exists(path):
            versions = [
                int(re.search(r'v(\d{3})', file).group(1))
                for file in os.listdir(path) if file.endswith('.xml')
            ]
            return max(versions, default=0)
        return 0

    def get_maps(self):
        """Retrieves the vertex maps associated with this node."""
        return sim_cmds.get_vtx_maps(self.node)

    def get_maps_mode(self):
        """Retrieves the vertex map modes (types) for the maps associated with this node."""
        return [
            sim_cmds.get_vtx_map_type(self.node, f"{map_name}MapType")
            for map_name in self.get_maps()
        ]
