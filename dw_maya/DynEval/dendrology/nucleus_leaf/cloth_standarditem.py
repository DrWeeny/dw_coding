from pathlib import Path
try:
    from PySide6 import QtCore
except ImportError:
    # Fallback for older Maya versions shipping PySide2
    from PySide2 import QtCore
# internal
from maya import cmds
from .base_standarditem import BaseSimulationItem
from dw_maya.DynEval import sim_cmds
from dw_logger import get_logger

from dw_maya.dw_maya_utils import lsTr

logger = get_logger()


class ClothTreeItem(BaseSimulationItem):
    """Tree item for cloth simulation nodes."""

    def __init__(self, name):
        super().__init__(name)
        self.setText(self.display_name)
        self._setup_item()

    @property
    def short_name(self):
        """Display-friendly name."""
        return self.node.split('|')[-1].split(':')[-1].split('_cloth')[0]

    @property
    def state_attr(self):
        """Simulation state attribute."""
        return 'isDynamic'

    @property
    def mesh_transform(self):
        """Transform of the simulated output mesh, or None if unresolved.

        Primary: downstream mesh from outputMesh (the visible sim mesh).
        Fallback: the input mesh via dw_core.get_mesh_from_nucx_node —
        both shapes live under the same transform in a standard setup.
        """
        try:
            hist = cmds.listHistory(self.node + '.outputMesh', lf=False, f=True) or []
            shapes = [i for i in hist if cmds.nodeType(i) == 'mesh' and len(i.split('.')) == 1]
            if shapes:
                transforms = lsTr(shapes[0], long=True)
                if transforms:
                    return transforms[0]
        except Exception as e:
            logger.warning(f"mesh_transform lookup failed for {self.node!r}: {e}")

        try:
            from dw_maya.dw_nucleus_utils.dw_core import get_mesh_from_nucx_node
            return get_mesh_from_nucx_node(self.node)
        except Exception as e:
            logger.warning(f"input-mesh fallback failed for {self.node!r}: {e}")
            return None

    def _get_current_state(self) -> bool:
        """Get current state from Maya with error handling."""
        try:
            return bool(cmds.getAttr(f"{self.node}.{self.state_attr}"))
        except Exception as e:
            logger.warning(f"Failed to get state for {self.node}: {e}")
            return False

    def set_state(self, state: bool) -> None:
        """Set nCloth dynamic state."""
        try:
            logger.debug(f"Setting {self.node_type} state - Node: {self.node}, State: {state}")

            # Update Maya attribute
            cmds.setAttr(f"{self.node}.{self.state_attr}", state)

            # Update item data
            self.setData(state, self.CUSTOM_ROLES['STATE'])

            # Update model
            if self.model():
                parent_index = self.parent().index() if self.parent() else QtCore.QModelIndex()
                state_index = self.model().index(self.row(), 1, parent_index)
                if state_index.isValid():
                    self.model().setData(state_index, state, QtCore.Qt.UserRole + 3)

            logger.debug(f"Successfully set {self.node_type} state for {self.node}")

        except Exception as e:
            logger.error(f"Failed to set state for {self.node_type} {self.node}: {e}")
            raise

    # cache_dir() inherited from BaseSimulationItem
    # (<fileCache>/<namespace>/<solver>/<short_name>, empty parts skipped)

    def cache_file(self, mode=1, suffix=''):
        """Construct cache filename."""
        iteration = self.get_iter() + mode
        suffix_text = f"_{suffix}" if suffix else ""
        cache_filename = f"{self.short_name}{suffix_text}_v{iteration:03d}.xml"
        return str(Path(self.cache_dir()) / cache_filename)

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
        if not path.exists():
            return 0
        versions = []
        for file in path.glob('*.xml'):
            tail = file.stem.rsplit('_v', 1)[-1]
            if tail.isdigit():
                versions.append(int(tail))
        return max(versions, default=0)

    def get_maps(self):
        """Retrieve available vertex maps for the node."""
        return sim_cmds.get_vtx_maps(self.node)

    def get_maps_mode(self):
        """Retrieve vertex map modes for each map."""
        return [sim_cmds.get_vtx_map_type(self.node, f"{map_name}MapType") for map_name in self.get_maps()]

