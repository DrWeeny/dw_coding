try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt, Signal, Slot
    from shiboken6 import wrapInstance
except ImportError:
    # Fallback for older Maya versions shipping PySide2
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Qt, Signal, Slot
    from shiboken2 import wrapInstance

from dataclasses import dataclass, field
from functools import partial
from typing import Optional, Dict, Set, List, Any
from datetime import datetime
from enum import Enum
from pathlib import Path
import maya.cmds as cmds
from dw_logger import get_logger
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dw_maya.dw_presets_io import dw_folder, dw_json
from dw_maya.DynEval.hub_keys import DynEvalKeys
from dw_maya.DynEval.sim_cmds.compat import qt_exec
from dw_maya.DynEval.sim_widget.wgt_base import DynEvalWidgetBase

logger = get_logger()


class PresetType(Enum):
    NUCLEUS = "nucleus"
    NCLOTH = "nCloth"
    NHAIR = "hairSystem"
    NRIGID = "nRigid"
    ZIVA = "zSolver"


@dataclass
class PresetInfo:
    """Enhanced preset info with protection and tracking."""
    name: str
    node_type: PresetType
    attributes: Dict[str, Any]
    version: str
    cache_name: Optional[str] = None
    solver: Optional[str] = None
    is_readonly: bool = False
    # True when a dynamicConstraint envelope was written next to the preset,
    # in the dynC subfolder PresetTool also reads.
    has_constraints: bool = False
    created_by: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)


class PresetManager:
    """Manages simulation presets with versioning and metadata
     with recovery and protection."""

    BACKUP_RETENTION_DAYS = 30  # How long to keep backups

    def __init__(self, root_path: Optional[Path] = None):
        super().__init__()
        self.root_path = Path(root_path) if root_path else self._resolve_root()
        self.backup_path = self.root_path / '.backups'
        self.backup_path.mkdir(parents=True, exist_ok=True)
        # Set by load_preset, read by the widget's delete confirmation.
        self.current_preset = None
        logger.info(f"PresetManager root: {self.root_path}")

    @staticmethod
    def _resolve_root() -> Path:
        """Preset root, guaranteed usable even with no scene open.

        dw_folder.get_folder() derives its path from the *saved* scene, and
        returns False on an untitled one - Path(False) then raised and took
        the whole Preset tab down with it. Falls back to the project, which
        exists whether or not the scene was ever saved, then to temp.
        """
        try:
            folder = dw_folder.get_folder()
        except Exception as e:
            logger.warning(f"PresetManager: get_folder failed ({e})")
            folder = None
        if folder and isinstance(folder, str):
            return Path(folder)

        import getpass
        user = getpass.getuser()

        try:
            project = cmds.workspace(query=True, rootDirectory=True)
            if project:
                root = Path(project) / 'json' / user
                logger.info(
                    f"PresetManager: scene not saved, using the project "
                    f"preset root {root}")
                return root
        except Exception as e:
            logger.warning(f"PresetManager: no workspace root ({e})")

        root = Path(tempfile.gettempdir()) / 'dw_presets' / user
        logger.warning(
            f"PresetManager: no scene and no project, falling back to {root}")
        return root

    def create_backup(self, preset_info: PresetInfo) -> Path:
        """Create backup of preset before modification."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = (self.backup_path /
                       f"{preset_info.name}_{preset_info.version}_{timestamp}.json")

        source_path = self.get_preset_file_path(preset_info)
        if source_path.exists():
            shutil.copy2(source_path, backup_file)
            return backup_file
        return None

    def restore_preset(self, backup_path: Path) -> PresetInfo:
        """Restore preset from backup."""
        # Extract original preset info from backup filename
        parts = backup_path.stem.split('_')
        name = parts[0]
        version = parts[1]

        # Load backup data
        preset_data = self._load_preset_file(backup_path)
        if not preset_data:
            raise ValueError(f"Invalid backup file: {backup_path}")

        # Create new preset with restored data
        preset_info = PresetInfo(
            name=name,
            version=version,
            **preset_data
        )

        # Save restored preset
        self._save_preset_to_file(preset_info)
        return preset_info

    def set_readonly(self, preset_info: PresetInfo, readonly: bool = True):
        """Set preset read-only status."""
        preset_path = self.get_preset_file_path(preset_info)
        if not preset_path.exists():
            raise ValueError(f"Preset not found: {preset_info.name}")

        # Update preset info
        preset_info.is_readonly = readonly

        # Update file system protection if possible
        try:
            import stat
            current_mode = preset_path.stat().st_mode
            if readonly:
                new_mode = current_mode & ~stat.S_IWRITE  # Remove write permission
            else:
                new_mode = current_mode | stat.S_IWRITE  # Add write permission
            preset_path.chmod(new_mode)
        except Exception as e:
            logger.warning(f"Could not set file system protection: {e}")

        # Save updated preset info
        self._save_preset_to_file(preset_info)

    def get_backups(self, preset_info: PresetInfo) -> List[Path]:
        """Get all available backups for a preset."""
        pattern = f"{preset_info.name}_{preset_info.version}_*.json"
        return sorted(
            self.backup_path.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

    def compare_presets(self, preset_a: PresetInfo, preset_b: PresetInfo) -> Dict[str, Any]:
        """Compare two presets and return differences."""
        differences = {
            'added': [],
            'removed': [],
            'modified': [],
            'unchanged': []
        }

        attrs_a = preset_a.attributes
        attrs_b = preset_b.attributes

        # Find all unique attributes
        all_attrs = set(attrs_a.keys()) | set(attrs_b.keys())

        for attr in all_attrs:
            if attr not in attrs_a:
                differences['added'].append({
                    'attr': attr,
                    'value': attrs_b[attr]
                })
            elif attr not in attrs_b:
                differences['removed'].append({
                    'attr': attr,
                    'value': attrs_a[attr]
                })
            elif attrs_a[attr] != attrs_b[attr]:
                differences['modified'].append({
                    'attr': attr,
                    'old_value': attrs_a[attr],
                    'new_value': attrs_b[attr]
                })
            else:
                differences['unchanged'].append(attr)

        return differences

    def save_preset(self,
                    nodes: List[str],
                    preset_name: str,
                    cache_name: Optional[str] = None,
                    constraints: Optional[List[str]] = None) -> PresetInfo:
        """Save node attributes as a preset.

        Args:
            nodes: every node in the save scope. The first one is the anchor -
                it decides the preset type, hence the folder it lands in.
            preset_name: file base name.
            cache_name: optional cache this preset belongs to.
            constraints: dynamicConstraint nodes to save alongside, as a
                separate dw_preset envelope in the dynC subfolder.
        """
        try:
            from dw_maya.dw_presets_io import dw_preset

            # Get node type and validate
            node_type = self._get_preset_type(nodes[0])
            if not node_type:
                raise ValueError(f"Unsupported node type for preset: {cmds.nodeType(nodes[0])}")

            # Create attribute preset
            preset_data = dw_preset.createAttrPreset(nodes)

            # Get solver name if applicable
            solver = self._get_solver_name(nodes[0])

            # Create preset info
            preset_info = PresetInfo(
                name=preset_name,
                node_type=node_type,
                attributes=preset_data,
                version=self._get_next_version(preset_name, node_type),
                cache_name=cache_name,
                solver=solver
            )

            if constraints:
                preset_info.has_constraints = self._save_constraints(preset_info,
                                                                     nodes[0],
                                                                     constraints)

            # Save to file
            self._save_preset_to_file(preset_info)

            return preset_info

        except Exception as e:
            logger.error(f"Failed to save preset {preset_name}: {e}")
            raise

    def _save_constraints(self,
                          preset_info: PresetInfo,
                          anchor_node: str,
                          constraints: List[str]) -> bool:
        """Write the constraint network beside the preset, PresetTool style.

        Same writer (saveNConstraintRig), same envelope and same dynC
        subfolder layout PresetTool uses, so a file written here can be
        rebuilt from either tool.
        """
        import dw_maya.dw_nucleus_utils as dwnx

        dyn_path = self.get_constraint_dir(preset_info)
        dyn_path.mkdir(parents=True, exist_ok=True)
        namespace = anchor_node.split(':')[0] if ':' in anchor_node else ':'

        try:
            dwnx.saveNConstraintRig(
                namespace=namespace,
                path=str(dyn_path),
                file=f"{preset_info.name}_{preset_info.version}",
                nconstraint=constraints,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save constraints for {preset_info.name}: {e}")
            return False

    def get_constraint_dir(self, preset_info: PresetInfo) -> Path:
        """Directory holding the constraint envelope for a preset."""
        return self.root_path / preset_info.node_type.value / 'dynC'

    def get_constraint_file_path(self, preset_info: PresetInfo) -> Path:
        """Constraint envelope path for a preset (may not exist)."""
        return (self.get_constraint_dir(preset_info) /
                f"{preset_info.name}_{preset_info.version}.json")

    def load_preset(self,
                    preset_info: PresetInfo,
                    target_nodes: List[str],
                    blend: float = 1.0,
                    with_constraints: bool = False) -> bool:
        """Load and apply a preset to target nodes.

        Two apply modes, because a preset can hold one node or a whole
        solver scope:

        - single entry + single target: applied to that target whatever it
          is called. This is the "copy these settings onto this cloth" case.
        - several entries: each is matched back to the scene by its stored
          (namespace-stripped) name, preferring the target's namespace.

        Constraints, when asked for and present, are rebuilt from the dynC
        envelope - the same call PresetTool makes.
        """
        try:
            from dw_maya.dw_presets_io import dw_preset

            entries = {key: value
                       for key, value in preset_info.attributes.items()
                       if isinstance(value, dict)}
            if not entries:
                raise ValueError(f"Preset {preset_info.name} holds no node entry")

            namespace = ':'
            if target_nodes and ':' in target_nodes[0]:
                namespace = target_nodes[0].split(':')[0]

            applied = 0
            if len(entries) == 1 and len(target_nodes) == 1:
                source = list(entries.keys())[0]
                if self._get_preset_type(target_nodes[0]) != preset_info.node_type:
                    raise ValueError("Target node must match preset type")
                dw_preset.blendAttrDic(
                    srcNode=source,
                    targetNode=target_nodes[0],
                    preset=preset_info.attributes,
                    blendValue=blend,
                )
                applied = 1
            else:
                for source in entries:
                    target = self._resolve_node(source, namespace)
                    if not target:
                        continue
                    dw_preset.blendAttrDic(
                        srcNode=source,
                        targetNode=target,
                        preset=preset_info.attributes,
                        blendValue=blend,
                    )
                    applied += 1

            if with_constraints and preset_info.has_constraints:
                self.load_constraints(preset_info, namespace)

            if not applied:
                logger.warning(f"Preset {preset_info.name}: no node matched in the scene")
                return False

            self.current_preset = preset_info
            return True

        except Exception as e:
            logger.error(f"Failed to load preset {preset_info.name}: {e}")
            return False

    def load_constraints(self, preset_info: PresetInfo, namespace: str = ':') -> List[str]:
        """Rebuild the saved dynamicConstraint network.

        Returns the created constraint transforms (empty when there is no
        constraint file for this preset).
        """
        import dw_maya.dw_nucleus_utils as dwnx

        constraint_file = self.get_constraint_file_path(preset_info)
        if not constraint_file.is_file():
            logger.warning(f"No constraint file for preset {preset_info.name}")
            return []

        created = dwnx.createAllConstraintPresets(str(constraint_file),
                                                  targ_ns=namespace)
        logger.info(f"Rebuilt {len(created)} constraint(s) from {constraint_file}")
        return created

    def _resolve_node(self, stored_name: str, namespace: str = ':') -> Optional[str]:
        """Resolve a namespace-stripped stored node name to a scene node.

        Same resolution order as PresetTool: the given namespace first, then
        root, then an unambiguous any-namespace lookup.
        """
        if namespace and namespace != ':':
            candidate = f"{namespace}:{stored_name}"
            if cmds.objExists(candidate):
                return candidate
        if cmds.objExists(stored_name):
            return stored_name

        hits = cmds.ls(stored_name, recursive=True) or []
        if len(hits) == 1:
            return hits[0]
        if hits:
            logger.warning(f"'{stored_name}' is ambiguous across namespaces "
                           f"({hits}), skipped")
        return None

    def get_presets_for_node(self, node: str) -> List[PresetInfo]:
        """Get all available presets for a given node type."""
        try:
            node_type = self._get_preset_type(node)
            if not node_type:
                return []

            presets = []
            preset_path = self.root_path / node_type.value

            if not preset_path.exists():
                return []

            for preset_file in preset_path.glob("*.json"):
                try:
                    preset_info = self._load_preset_info(preset_file)
                    if preset_info:
                        presets.append(preset_info)
                except Exception as e:
                    logger.warning(f"Failed to load preset {preset_file}: {e}")

            return sorted(presets, key=lambda x: x.version)

        except Exception as e:
            logger.error(f"Failed to get presets for {node}: {e}")
            return []

    def _get_preset_type(self, node: str) -> Optional[PresetType]:
        """Determine preset type from node."""
        node_type = cmds.nodeType(node)
        return next((pt for pt in PresetType if pt.value == node_type), None)

    def _get_solver_name(self, node: str) -> Optional[str]:
        """Get associated solver name for node."""
        try:
            if cmds.nodeType(node) in ['nCloth', 'hairSystem', 'nRigid']:
                connections = cmds.listConnections(node, type='nucleus')
                return connections[0] if connections else None
            elif cmds.nodeType(node) == 'zSolver':
                return node
        except:
            return None

    def _get_next_version(self, preset_name: str, node_type: PresetType) -> str:
        """Get next available version number for preset.

        Presets are written to root_path/<node_type>/, so the existing
        versions have to be looked up there - globbing root_path itself
        always returned v001 and silently overwrote the previous save.
        """
        preset_dir = self.root_path / node_type.value
        existing = list(preset_dir.glob(f"{preset_name}_v*.json"))
        if not existing:
            return "v001"

        versions = [int(re.search(r'v(\d{3})', p.stem).group(1)) for p in existing if re.search(r'v(\d{3})', p.stem)]
        return f"v{max(versions) + 1:03d}" if versions else "v001"

    def _save_preset_to_file(self, preset_info: PresetInfo):
        """Save preset info to file."""
        from dw_maya.dw_presets_io import dw_json

        preset_path = self.root_path / preset_info.node_type.value
        preset_path.mkdir(parents=True, exist_ok=True)

        file_path = preset_path / f"{preset_info.name}_{preset_info.version}.json"

        # Create preset data structure
        preset_data = {
            "info": {
                "name": preset_info.name,
                "type": preset_info.node_type.value,
                "version": preset_info.version,
                "cache_name": preset_info.cache_name,
                "solver": preset_info.solver,
                "has_constraints": preset_info.has_constraints,
                "is_readonly": preset_info.is_readonly,
                "created_at": preset_info.created_at.isoformat(),
                "last_modified": datetime.now().isoformat()
            },
            "attributes": preset_info.attributes
        }

        dw_json.save_json(str(file_path), preset_data)

    def _load_preset_info(self, preset_file: Path) -> Optional[PresetInfo]:
        """Load preset info from file."""
        from dw_maya.dw_presets_io import dw_json

        try:
            data = dw_json.load_json(str(preset_file))
            if not data or "info" not in data:
                return None

            return PresetInfo(
                name=data["info"]["name"],
                node_type=PresetType(data["info"]["type"]),
                attributes=data["attributes"],
                version=data["info"]["version"],
                cache_name=data["info"].get("cache_name"),
                solver=data["info"].get("solver"),
                is_readonly=data["info"].get("is_readonly", False),
                has_constraints=data["info"].get("has_constraints", False)
            )
        except Exception as e:
            logger.warning(f"Failed to parse preset file {preset_file}: {e}")
            return None


    def delete_preset(self, preset_info: PresetInfo) -> bool:
        """Delete a preset and its associated files.

        Args:
            preset_info: The preset to delete

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        try:
            # Construct preset file path
            preset_path = (self.root_path /
                           preset_info.node_type.value /
                           f"{preset_info.name}_{preset_info.version}.json")

            if not preset_path.exists():
                logger.warning(f"Preset file not found: {preset_path}")
                return False

            # Check for associated metadata files
            metadata_files = self._get_associated_files(preset_info)

            # Delete preset file
            preset_path.unlink()

            # Delete associated metadata files
            for meta_file in metadata_files:
                if meta_file.exists():
                    meta_file.unlink()

            logger.info(f"Successfully deleted preset: {preset_info.name}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete preset {preset_info.name}: {e}")
            return False


    def _get_associated_files(self, preset_info: PresetInfo) -> List[Path]:
        """Get all files associated with this preset (metadata, cache info, etc.).

        Args:
            preset_info: The preset to check for associated files

        Returns:
            List of paths to associated files
        """
        associated_files = []
        base_name = f"{preset_info.name}_{preset_info.version}"
        preset_dir = self.root_path / preset_info.node_type.value

        # Look for metadata files with same base name but different extensions
        for ext in ['.meta', '.cache', '.log']:
            meta_file = preset_dir / f"{base_name}{ext}"
            if meta_file.exists():
                associated_files.append(meta_file)

        # The constraint envelope written beside the preset
        constraint_file = self.get_constraint_file_path(preset_info)
        if constraint_file.exists():
            associated_files.append(constraint_file)

        # Check for cache-specific metadata if this preset is associated with a cache
        if preset_info.cache_name:
            cache_meta = preset_dir / 'cache_metadata' / f"{preset_info.cache_name}.json"
            if cache_meta.exists():
                associated_files.append(cache_meta)

        return associated_files


    def get_preset_file_path(self, preset_info: PresetInfo) -> Path:
        """Get the file path for a preset.

        Args:
            preset_info: The preset to get the path for

        Returns:
            Path to the preset file
        """
        return (self.root_path /
                preset_info.node_type.value /
                f"{preset_info.name}_{preset_info.version}.json")

    def get_presets_by_type(self, node_type: PresetType) -> List[PresetInfo]:
        """Get all presets for a specific node type.

        Args:
            node_type: PresetType enum value to filter by

        Returns:
            List of PresetInfo objects matching the type

        Example:
            >>> manager = PresetManager()
            >>> ncloth_presets = manager.get_presets_by_type(PresetType.NCLOTH)
        """
        try:
            # Get the type-specific directory
            type_dir = self.root_path / node_type.value
            if not type_dir.exists():
                return []

            presets = []
            # Find all JSON files in the type directory
            for preset_file in type_dir.glob("*.json"):
                try:
                    # Skip backup files if they're in this directory
                    if preset_file.name.startswith('.backup'):
                        continue

                    # Load and validate preset data
                    data = self._load_preset_file(preset_file)
                    if not data:
                        continue

                    # Verify the type matches (in case of miscategorized files)
                    if data.get('info', {}).get('type') != node_type.value:
                        logger.warning(
                            f"Preset file {preset_file} has mismatched type. "
                            f"Expected {node_type.value}, got {data.get('info', {}).get('type')}"
                        )
                        continue

                    # Extract version from filename or data
                    version = self._extract_version(preset_file.stem, data)

                    # Create PresetInfo object
                    preset_info = PresetInfo(
                        name=data['info']['name'],
                        node_type=node_type,
                        attributes=data.get('attributes', {}),
                        version=version,
                        cache_name=data['info'].get('cache_name'),
                        solver=data['info'].get('solver'),
                        is_readonly=data['info'].get('is_readonly', False),
                        has_constraints=data['info'].get('has_constraints', False),
                        created_by=data['info'].get('created_by'),
                        created_at=datetime.fromisoformat(data['info'].get('created_at', datetime.now().isoformat())),
                        last_modified=datetime.fromisoformat(
                            data['info'].get('last_modified', datetime.now().isoformat()))
                    )

                    presets.append(preset_info)

                except Exception as e:
                    logger.error(f"Failed to load preset {preset_file}: {e}")
                    continue

            # Sort presets by version and name
            return sorted(
                presets,
                key=lambda p: (p.name, self._version_to_int(p.version)),
                reverse=True  # Most recent versions first
            )

        except Exception as e:
            logger.error(f"Failed to get presets for type {node_type}: {e}")
            return []

    def _extract_version(self, filename: str, data: dict) -> str:
        """Extract version from filename or data."""
        # Try to get version from filename first
        version_match = re.search(r'_v(\d{3})', filename)
        if version_match:
            return f"v{version_match.group(1)}"

        # Fall back to data
        version = data.get('info', {}).get('version')
        if version:
            return version

        # Default to v001 if no version found
        return "v001"

    def _version_to_int(self, version: str) -> int:
        """Convert version string to integer for sorting."""
        try:
            # Extract numeric portion of version (e.g., "v001" -> 1)
            return int(re.search(r'v?(\d+)', version).group(1))
        except:
            return 0

    def _load_preset_file(self, file_path: Path) -> Optional[Dict]:
        """Load and validate preset file."""
        try:
            data = dw_json.load_json(file_path)

            # Basic validation of preset structure
            if not isinstance(data, dict):
                logger.warning(f"Invalid preset file format in {file_path}")
                return None

            if 'info' not in data or 'attributes' not in data:
                logger.warning(f"Missing required sections in preset file {file_path}")
                return None

            return data

        except Exception as e:
            logger.error(f"Error loading preset file {file_path}: {e}")
            return None

    def get_preset_statistics(self, node_type: PresetType) -> Dict[str, Any]:
        """Get statistics about presets of a specific type.

        Returns:
            Dictionary containing:
            - total_count: Total number of presets
            - readonly_count: Number of read-only presets
            - newest_preset: Most recently modified preset
            - oldest_preset: Oldest preset
            - size_on_disk: Total size of preset files
        """
        presets = self.get_presets_by_type(node_type)

        if not presets:
            return {
                'total_count': 0,
                'readonly_count': 0,
                'newest_preset': None,
                'oldest_preset': None,
                'size_on_disk': 0
            }

        # Calculate statistics
        readonly_count = sum(1 for p in presets if p.is_readonly)
        sorted_by_date = sorted(presets, key=lambda p: p.last_modified)

        # Calculate total size
        size = sum(
            self.get_preset_file_path(p).stat().st_size
            for p in presets
        )

        return {
            'total_count': len(presets),
            'readonly_count': readonly_count,
            'newest_preset': sorted_by_date[-1] if sorted_by_date else None,
            'oldest_preset': sorted_by_date[0] if sorted_by_date else None,
            'size_on_disk': size
        }



class PresetWidget(DynEvalWidgetBase):
    """Widget for managing simulation presets.

    Follows the selection published by the tree (SELECTED_NODE) - the panel
    was previously built without any hub subscription, so set_node() was
    never called and current_node did not exist at all.
    """

    preset_applied = QtCore.Signal(PresetInfo)  # Emitted when preset is applied

    def __init__(self, hub, parent=None):
        super().__init__(hub, parent)
        self.current_node = None   # Maya node name (str)
        self.current_item = None   # tree item, kept for the parent/child scope
        self.preset_manager = PresetManager()
        self._setup_ui()
        self.subscribe(DynEvalKeys.SELECTED_NODE, self._on_node_selected)
        self.set_node(self.hub_get(DynEvalKeys.SELECTED_NODE))

    def _setup_ui(self):
        """Initialize UI components."""
        layout = QtWidgets.QVBoxLayout(self)

        # Current node the presets apply to
        self.node_label = QtWidgets.QLabel("No node selected")
        self.node_label.setWordWrap(True)
        layout.addWidget(self.node_label)

        # Preset list
        self.preset_list = QtWidgets.QTreeWidget()
        self.preset_list.setHeaderLabels(["Name", "Version", "Type", "nC"])
        self.preset_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.preset_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.preset_list.setToolTip(f"Preset root: {self.preset_manager.root_path}")
        layout.addWidget(self.preset_list)

        # Blend value slider
        blend_layout = QtWidgets.QHBoxLayout()
        self.blend_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.blend_slider.setRange(0, 100)
        self.blend_slider.setValue(100)
        self.blend_label = QtWidgets.QLabel("Blend: 100%")
        blend_layout.addWidget(QtWidgets.QLabel("Blend:"))
        blend_layout.addWidget(self.blend_slider)
        blend_layout.addWidget(self.blend_label)
        layout.addLayout(blend_layout)

        # Scope — what goes into a save besides the selected node itself.
        scope_box = QtWidgets.QGroupBox("Scope")
        scope_layout = QtWidgets.QVBoxLayout(scope_box)

        self.parent_check = QtWidgets.QCheckBox("Include parent")
        self.parent_check.setToolTip(
            "Save the whole branch above the selection too - the nCloth a "
            "collider hangs under, and the solver above it."
        )
        self.children_check = QtWidgets.QCheckBox("Include children")
        self.children_check.setToolTip(
            "Save everything nested under the selection: for a solver, all "
            "its cloths / hairs / colliders."
        )
        self.constraint_check = QtWidgets.QCheckBox("Include nConstraints")
        self.constraint_check.setToolTip(
            "Save the dynamicConstraint network of every cloth / hair in the "
            "scope, in the dynC subfolder. Same envelope as PresetTool, so "
            "either tool can rebuild it. On load, ticking this rebuilds them."
        )

        for check in (self.parent_check, self.children_check, self.constraint_check):
            scope_layout.addWidget(check)
        layout.addWidget(scope_box)

        # Action buttons
        button_layout = QtWidgets.QHBoxLayout()
        self.save_btn = QtWidgets.QPushButton("Save Preset")
        self.load_btn = QtWidgets.QPushButton("Load Preset")
        self.delete_btn = QtWidgets.QPushButton("Delete")

        for btn in (self.save_btn, self.load_btn, self.delete_btn):
            button_layout.addWidget(btn)
        layout.addLayout(button_layout)

        # Connect signals
        self.blend_slider.valueChanged.connect(self._update_blend_label)
        self.preset_list.itemSelectionChanged.connect(self._update_button_states)
        self.preset_list.customContextMenuRequested.connect(self._show_context_menu)
        self.save_btn.clicked.connect(self._save_preset)
        self.load_btn.clicked.connect(self._load_preset)
        self.delete_btn.clicked.connect(self._delete_preset)

    def _update_blend_label(self, value):
        """Update blend value label."""
        self.blend_label.setText(f"{value}%")

    def _on_node_selected(self, old_value, new_value):
        """Hub callback: tree selection changed."""
        self.set_node(new_value)

    def set_node(self, node):
        """Update preset list for current node.

        Accepts either a Maya node name or a tree item (BaseSimulationItem),
        since the hub publishes the item, not the node string.
        """
        node_name = getattr(node, 'node', node)
        if node_name is not None and not isinstance(node_name, str):
            logger.warning(f"PresetWidget: unusable selection {node!r}")
            node_name = None

        self.current_node = node_name
        self.current_item = node if node_name and node is not node_name else None
        self.node_label.setText(node_name or "No node selected")
        self._update_button_states()
        self._refresh_presets()

    def _update_button_states(self):
        """Enable actions only when they can actually run."""
        has_node = bool(self.current_node)
        has_selection = bool(self.preset_list.selectedItems())
        self.save_btn.setEnabled(has_node)
        self.load_btn.setEnabled(has_node and has_selection)
        self.delete_btn.setEnabled(has_selection)

        # A scope option nothing can be collected for is only confusing.
        item = self.current_item
        self.parent_check.setEnabled(bool(item is not None and item.parent()))
        self.children_check.setEnabled(bool(item is not None and item.rowCount()))

    # ------------------------------------------------------------------
    # SAVE SCOPE
    # ------------------------------------------------------------------

    def _scope_nodes(self) -> List[str]:
        """Nodes a save covers, anchor first (it decides the preset type)."""
        nodes = [self.current_node]
        item = self.current_item

        if item is not None:
            if self.parent_check.isChecked() and self.parent_check.isEnabled():
                nodes.extend(self._ancestor_nodes(item))
            if self.children_check.isChecked() and self.children_check.isEnabled():
                nodes.extend(self._descendant_nodes(item))

        return self._clean_nodes(nodes)

    def _constraint_nodes(self) -> List[str]:
        """dynamicConstraints to save with the preset.

        Looked up over the save scope, plus - when the anchor is a solver
        with children left out of the scope - its cloths and hairs, since a
        nucleus carries no constraint of its own and "the constraints of the
        selected solver" means the ones of what it simulates.
        """
        from dw_maya.DynEval.sim_cmds import preset_management

        lookup = self._scope_nodes()
        item = self.current_item
        if item is not None and not self.children_check.isChecked():
            lookup = self._clean_nodes(lookup + self._descendant_nodes(item))

        try:
            return preset_management.get_constraints(lookup)
        except Exception as e:
            logger.error(f"Constraint lookup failed: {e}")
            return []

    @staticmethod
    def _ancestor_nodes(item) -> List[str]:
        """Every tree item above this one, closest first."""
        nodes = []
        parent = item.parent()
        while parent is not None:
            node = getattr(parent, 'node', None)
            if node:
                nodes.append(node)
            parent = parent.parent()
        return nodes

    @classmethod
    def _descendant_nodes(cls, item) -> List[str]:
        """Every tree item below this one, depth first."""
        nodes = []
        for row in range(item.rowCount()):
            child = item.child(row, 0)
            if child is None:
                continue
            node = getattr(child, 'node', None)
            if node:
                nodes.append(node)
            nodes.extend(cls._descendant_nodes(child))
        return nodes

    @staticmethod
    def _clean_nodes(nodes: List[str]) -> List[str]:
        """Drop empties, duplicates and dead nodes, keeping order."""
        seen = set()
        cleaned = []
        for node in nodes:
            if not node or node in seen:
                continue
            seen.add(node)
            if cmds.objExists(node):
                cleaned.append(node)
            else:
                logger.warning(f"PresetWidget: skipping missing node {node}")
        return cleaned

    # ------------------------------------------------------------------
    # CONTEXT MENU
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos):
        """Right-click menu on the preset list.

        The preset root is derived from the scene (or falls back to the
        project / temp), so "where did that file go" is a fair question -
        every entry here answers it.
        """
        item = self.preset_list.itemAt(pos)
        preset = item.data(0, QtCore.Qt.UserRole) if item else None

        menu = QtWidgets.QMenu(self)

        if preset is not None:
            preset_file = self.preset_manager.get_preset_file_path(preset)
            action = menu.addAction("Reveal preset in explorer")
            action.triggered.connect(partial(self._reveal, preset_file))

            constraint_file = self.preset_manager.get_constraint_file_path(preset)
            action = menu.addAction("Reveal nConstraint file in explorer")
            action.setEnabled(constraint_file.is_file())
            action.triggered.connect(partial(self._reveal, constraint_file))

            action = menu.addAction("Copy path")
            action.triggered.connect(partial(self._copy_path, preset_file))

            menu.addSeparator()

        action = menu.addAction("Open preset root folder")
        action.triggered.connect(partial(self._reveal, self.preset_manager.root_path))

        action = menu.addAction("Copy preset root path")
        action.triggered.connect(partial(self._copy_path, self.preset_manager.root_path))

        qt_exec(menu, self.preset_list.viewport().mapToGlobal(pos))

    def _reveal(self, path: Path):
        """Show a file (selected) or a folder in the OS file browser."""
        path = Path(path)
        target = path if path.exists() else path.parent

        if not target.exists():
            QtWidgets.QMessageBox.warning(
                self,
                "Reveal",
                f"Path does not exist:\n{target}"
            )
            return

        try:
            if sys.platform == 'win32':
                if target.is_dir():
                    os.startfile(str(target))
                else:
                    # /select needs the whole thing as one string, quoted
                    subprocess.Popen(f'explorer /select,"{target}"')
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', '-R', str(target)])
            else:
                folder = target if target.is_dir() else target.parent
                subprocess.Popen(['xdg-open', str(folder)])
        except Exception as e:
            logger.error(f"Failed to reveal {target}: {e}")
            QtWidgets.QMessageBox.warning(
                self,
                "Reveal",
                f"Could not open the file browser:\n{e}"
            )

    def _copy_path(self, path: Path):
        """Put a path on the clipboard - handy when explorer is not around."""
        QtWidgets.QApplication.clipboard().setText(str(path))
        logger.info(f"Path copied to clipboard: {path}")

    def _refresh_presets(self):
        """Refresh preset list."""
        self.preset_list.clear()
        if not self.current_node:
            return

        presets = self.preset_manager.get_presets_for_node(self.current_node)
        for preset in presets:
            item = QtWidgets.QTreeWidgetItem([
                preset.name,
                preset.version,
                preset.node_type.value,
                "yes" if preset.has_constraints else ""
            ])
            node_count = sum(1 for v in preset.attributes.values() if isinstance(v, dict))
            item.setToolTip(0, f"{node_count} node(s) in this preset")
            item.setData(0, QtCore.Qt.UserRole, preset)
            self.preset_list.addTopLevelItem(item)

        self._update_button_states()

    def _save_preset(self):
        """Save current node settings as preset."""
        if not self.current_node:
            QtWidgets.QMessageBox.information(
                self,
                "Save Preset",
                "Select a simulation node in the tree first."
            )
            return

        if not cmds.objExists(self.current_node):
            QtWidgets.QMessageBox.warning(
                self,
                "Save Preset",
                f"Node no longer exists: {self.current_node}"
            )
            return

        nodes = self._scope_nodes()
        constraints = self._constraint_nodes() if self.constraint_check.isChecked() else []

        name, ok = QtWidgets.QInputDialog.getText(
            self, "Save Preset", "Enter preset name:"
        )
        if ok and name:
            try:
                preset = self.preset_manager.save_preset(
                    nodes,
                    name,
                    constraints=constraints
                )
                self._refresh_presets()

                detail = f"{len(nodes)} node(s)"
                if preset.has_constraints:
                    detail += f", {len(constraints)} constraint(s)"
                QtWidgets.QMessageBox.information(
                    self,
                    "Success",
                    f"Preset '{name}' {preset.version} saved.\n{detail}"
                )

            except Exception as e:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Error",
                    f"Failed to save preset: {e}"
                )

    def _load_preset(self):
        """Load selected preset."""
        selected = self.preset_list.selectedItems()
        if not selected or not self.current_node:
            return

        preset = selected[0].data(0, QtCore.Qt.UserRole)
        blend_value = self.blend_slider.value() / 100.0

        try:
            success = self.preset_manager.load_preset(
                preset,
                [self.current_node],
                blend_value,
                with_constraints=self.constraint_check.isChecked()
            )

            if success:
                self.preset_applied.emit(preset)
            else:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Error",
                    "Failed to load preset"
                )

        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self,
                "Error",
                f"Failed to load preset: {e}"
            )

    def _delete_preset(self):
        """Delete selected presets with confirmation and error handling."""
        selected_items = self.preset_list.selectedItems()
        if not selected_items:
            return

        # Confirm deletion
        presets_to_delete = [
            item.data(0, QtCore.Qt.UserRole) for item in selected_items
        ]

        message = (f"Delete {len(presets_to_delete)} preset(s)?\n\n" +
                   "\n".join(f"• {p.name} ({p.version})" for p in presets_to_delete))

        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm Delete",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No  # Default to No for safety
        )

        if reply != QtWidgets.QMessageBox.Yes:
            return

        # Track deletion results
        success_count = 0
        failed_deletes = []

        # Show progress dialog for multiple deletions
        progress = None
        if len(presets_to_delete) > 1:
            progress = QtWidgets.QProgressDialog(
                "Deleting presets...",
                "Cancel",
                0,
                len(presets_to_delete),
                self
            )
            progress.setWindowModality(QtCore.Qt.WindowModal)

        # Process deletions
        try:
            for i, preset in enumerate(presets_to_delete):
                if progress and progress.wasCanceled():
                    break

                try:
                    if self.preset_manager.delete_preset(preset):
                        success_count += 1
                    else:
                        failed_deletes.append(preset.name)
                except Exception as e:
                    logger.error(f"Error deleting preset {preset.name}: {e}")
                    failed_deletes.append(f"{preset.name} ({str(e)})")

                if progress:
                    progress.setValue(i + 1)

        finally:
            if progress:
                progress.close()

        # Refresh the preset list
        self._refresh_presets()

        # Show results
        if failed_deletes:
            QtWidgets.QMessageBox.warning(
                self,
                "Delete Results",
                f"Successfully deleted {success_count} preset(s).\n\n"
                f"Failed to delete {len(failed_deletes)} preset(s):\n" +
                "\n".join(f"• {name}" for name in failed_deletes)
            )
        else:
            QtWidgets.QMessageBox.information(
                self,
                "Delete Results",
                f"Successfully deleted {success_count} preset(s)."
            )

    def confirm_delete(self, presets: List[PresetInfo]) -> bool:
        """Show confirmation dialog for preset deletion.

        Args:
            presets: List of presets to be deleted

        Returns:
            bool: True if user confirmed deletion, False otherwise
        """
        current = self.preset_manager.current_preset

        # Add warning if trying to delete the currently loaded preset
        warning = ""
        if current and any(p.name == current.name for p in presets):
            warning = ("\n\nWARNING: You are about to delete one or more "
                       "currently loaded presets. This may affect your scene.")

        message = (f"Are you sure you want to delete {len(presets)} preset(s)?{warning}\n\n" +
                   "\n".join(f"• {p.name} ({p.version})" for p in presets))

        return QtWidgets.QMessageBox.question(
            self,
            "Confirm Delete",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        ) == QtWidgets.QMessageBox.Yes


class PresetRecoveryDialog(QtWidgets.QDialog):
    """Dialog for managing preset backups and recovery."""

    def __init__(self, preset_manager: PresetManager, parent=None):
        super().__init__(parent)
        self.preset_manager = preset_manager
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Preset Recovery")
        layout = QtWidgets.QVBoxLayout(self)

        # Backup list
        self.backup_list = QtWidgets.QTreeWidget()
        self.backup_list.setHeaderLabels(["Preset", "Version", "Backup Date"])
        layout.addWidget(self.backup_list)

        # Preview area
        self.preview_text = QtWidgets.QTextEdit()
        self.preview_text.setReadOnly(True)
        layout.addWidget(self.preview_text)

        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        self.restore_btn = QtWidgets.QPushButton("Restore Selected")
        self.delete_btn = QtWidgets.QPushButton("Delete Backup")
        button_layout.addWidget(self.restore_btn)
        button_layout.addWidget(self.delete_btn)
        layout.addLayout(button_layout)

        # Connect signals
        self.backup_list.itemSelectionChanged.connect(self._update_preview)
        self.restore_btn.clicked.connect(self._restore_backup)
        self.delete_btn.clicked.connect(self._delete_backup)

    def _update_preview(self):
        """Update preview text when backup selection changes."""
        selected_items = self.backup_list.selectedItems()
        if not selected_items:
            self.preview_text.clear()
            self.restore_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            return

        backup_path = selected_items[0].data(0, QtCore.Qt.UserRole)
        try:
            data = dw_json.load_json(backup_path)

            # Format preview text
            preview = []
            preview.append(f"Backup from: {backup_path.stat().st_mtime}")
            preview.append(f"Preset Name: {data.get('info', {}).get('name', 'Unknown')}")
            preview.append(f"Node Type: {data.get('info', {}).get('type', 'Unknown')}")
            preview.append("\nAttributes:")

            # Show first few attributes as preview
            attributes = data.get('attributes', {})
            for i, (attr, value) in enumerate(attributes.items()):
                if i >= 10:  # Limit preview to 10 attributes
                    preview.append("... (more attributes)")
                    break
                preview.append(f"  {attr}: {value}")

            self.preview_text.setPlainText("\n".join(preview))
            self.restore_btn.setEnabled(True)
            self.delete_btn.setEnabled(True)

        except Exception as e:
            self.preview_text.setPlainText(f"Error loading backup: {e}")
            self.restore_btn.setEnabled(False)

    def _restore_backup(self):
        """Restore selected backup."""
        selected_items = self.backup_list.selectedItems()
        if not selected_items:
            return

        backup_path = selected_items[0].data(0, QtCore.Qt.UserRole)

        # Confirm restoration
        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm Restore",
            f"Restore preset from backup?\nThis will overwrite the current preset.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )

        if reply == QtWidgets.QMessageBox.Yes:
            try:
                self.preset_manager.restore_preset(backup_path)
                QtWidgets.QMessageBox.information(
                    self,
                    "Success",
                    "Preset restored successfully!"
                )
                self.accept()  # Close dialog
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to restore preset: {e}"
                )

    def _delete_backup(self):
        """Delete selected backup."""
        selected_items = self.backup_list.selectedItems()
        if not selected_items:
            return

        backup_path = selected_items[0].data(0, QtCore.Qt.UserRole)

        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm Delete",
            "Delete this backup?\nThis cannot be undone.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )

        if reply == QtWidgets.QMessageBox.Yes:
            try:
                backup_path.unlink()
                self._refresh_backups()  # Refresh the list
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to delete backup: {e}"
                )

    def show_for_preset(self, preset_info: PresetInfo):
        """Show recovery dialog for specific preset."""
        self._current_preset = preset_info
        self._refresh_backups()
        self.show()

    def _refresh_backups(self):
        """Refresh backup list."""
        self.backup_list.clear()
        backups = self.preset_manager.get_backups(self._current_preset)

        for backup_path in backups:
            timestamp = datetime.fromtimestamp(backup_path.stat().st_mtime)
            item = QtWidgets.QTreeWidgetItem([
                self._current_preset.name,
                self._current_preset.version,
                timestamp.strftime('%Y-%m-%d %H:%M:%S')
            ])
            item.setData(0, QtCore.Qt.UserRole, backup_path)
            self.backup_list.addTopLevelItem(item)



class PresetCompareDialog(QtWidgets.QDialog):
    """Dialog for comparing presets with visualization."""

    def __init__(self, preset_manager: PresetManager, parent=None):
        super().__init__(parent)
        self.preset_manager = preset_manager
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("Compare Presets")
        layout = QtWidgets.QVBoxLayout(self)

        # Preset selection
        selection_layout = QtWidgets.QHBoxLayout()
        self.preset_a_combo = QtWidgets.QComboBox()
        self.preset_b_combo = QtWidgets.QComboBox()
        selection_layout.addWidget(QtWidgets.QLabel("Compare:"))
        selection_layout.addWidget(self.preset_a_combo)
        selection_layout.addWidget(QtWidgets.QLabel("with:"))
        selection_layout.addWidget(self.preset_b_combo)
        layout.addLayout(selection_layout)

        # Differences view
        self.diff_view = QtWidgets.QTreeWidget()
        self.diff_view.setHeaderLabels(["Attribute", "Preset A", "Preset B"])
        layout.addWidget(self.diff_view)

        # Blend controls
        blend_layout = QtWidgets.QHBoxLayout()
        self.blend_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.blend_slider.setRange(0, 100)
        self.blend_slider.setValue(50)
        blend_layout.addWidget(QtWidgets.QLabel("Blend:"))
        blend_layout.addWidget(self.blend_slider)
        blend_layout.addWidget(QtWidgets.QLabel("A"))
        blend_layout.addWidget(self.blend_slider)
        blend_layout.addWidget(QtWidgets.QLabel("B"))
        layout.addLayout(blend_layout)

        # Apply button
        self.apply_btn = QtWidgets.QPushButton("Apply Blend")
        layout.addWidget(self.apply_btn)

        # Connect signals
        self.preset_a_combo.currentIndexChanged.connect(self._update_comparison)
        self.preset_b_combo.currentIndexChanged.connect(self._update_comparison)
        self.blend_slider.valueChanged.connect(self._update_blend_preview)
        self.apply_btn.clicked.connect(self._apply_blend)

    def _update_comparison(self):
        """Update comparison view when preset selection changes."""
        preset_a = self.preset_a_combo.currentData(QtCore.Qt.UserRole)
        preset_b = self.preset_b_combo.currentData(QtCore.Qt.UserRole)

        if not preset_a or not preset_b:
            return

        self.diff_view.clear()

        # Get differences
        differences = self.preset_manager.compare_presets(preset_a, preset_b)

        # Add modified attributes
        for diff in differences['modified']:
            item = QtWidgets.QTreeWidgetItem([
                diff['attr'],
                str(diff['old_value']),
                str(diff['new_value'])
            ])
            item.setBackground(1, QtGui.QColor(255, 235, 235))  # Light red
            item.setBackground(2, QtGui.QColor(235, 255, 235))  # Light green
            self.diff_view.addTopLevelItem(item)

        # Add new attributes
        for diff in differences['added']:
            item = QtWidgets.QTreeWidgetItem([
                diff['attr'],
                "(not set)",
                str(diff['value'])
            ])
            item.setBackground(2, QtGui.QColor(235, 255, 235))
            self.diff_view.addTopLevelItem(item)

        # Add removed attributes
        for diff in differences['removed']:
            item = QtWidgets.QTreeWidgetItem([
                diff['attr'],
                str(diff['value']),
                "(not set)"
            ])
            item.setBackground(1, QtGui.QColor(255, 235, 235))
            self.diff_view.addTopLevelItem(item)

        self.diff_view.resizeColumnToContents(0)

    def _update_blend_preview(self):
        """Update preview based on blend slider value."""
        blend_value = self.blend_slider.value() / 100.0
        preset_a = self.preset_a_combo.currentData(QtCore.Qt.UserRole)
        preset_b = self.preset_b_combo.currentData(QtCore.Qt.UserRole)

        if not preset_a or not preset_b:
            return

        # Update values in diff view
        root = self.diff_view.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            attr_name = item.text(0)

            # Get values from both presets
            value_a = preset_a.attributes.get(attr_name)
            value_b = preset_b.attributes.get(attr_name)

            if isinstance(value_a, (int, float)) and isinstance(value_b, (int, float)):
                # Calculate blended value
                blended = value_a * (1 - blend_value) + value_b * blend_value
                item.setText(3, f"{blended:.2f}")

    def _apply_blend(self):
        """Apply the current blend to the active preset."""
        preset_a = self.preset_a_combo.currentData(QtCore.Qt.UserRole)
        preset_b = self.preset_b_combo.currentData(QtCore.Qt.UserRole)

        if not preset_a or not preset_b:
            return

        blend_value = self.blend_slider.value() / 100.0

        try:
            # Create new blended preset
            blended_attributes = {}

            # Blend numeric attributes
            for attr in set(preset_a.attributes) | set(preset_b.attributes):
                value_a = preset_a.attributes.get(attr, 0)
                value_b = preset_b.attributes.get(attr, 0)

                if isinstance(value_a, (int, float)) and isinstance(value_b, (int, float)):
                    blended_attributes[attr] = value_a * (1 - blend_value) + value_b * blend_value
                else:
                    # For non-numeric attributes, use the value closer to the blend
                    blended_attributes[attr] = value_b if blend_value > 0.5 else value_a

            # Create new preset with blended values
            new_name = f"{preset_a.name}_blend_{preset_b.name}"
            blended_preset = PresetInfo(
                name=new_name,
                node_type=preset_a.node_type,
                attributes=blended_attributes,
                version="v001"
            )

            # Save the blended preset
            self.preset_manager.save_preset(blended_preset)

            QtWidgets.QMessageBox.information(
                self,
                "Success",
                f"Created blended preset: {new_name}"
            )

            self.accept()  # Close dialog

        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to create blended preset: {e}"
            )

    def populate_presets(self, node_type: PresetType):
        """Populate preset combo boxes with available presets."""
        presets = self.preset_manager.get_presets_by_type(node_type)

        for combo in (self.preset_a_combo, self.preset_b_combo):
            combo.clear()
            for preset in presets:
                combo.addItem(f"{preset.name} ({preset.version})", preset)
