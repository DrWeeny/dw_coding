from PySide6 import QtWidgets, QtCore, QtGui
from dataclasses import dataclass, field
from typing import Optional, Dict, Set, List, Any
from datetime import datetime
from enum import Enum
from pathlib import Path
import maya.cmds as cmds
from dw_logger import get_logger
import re
import shutil
import tempfile
from dw_maya.dw_presets_io import dw_folder, dw_json

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
    created_by: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    last_modified: datetime = field(default_factory=datetime.now)


class PresetManager:
    """Manages simulation presets with versioning and metadata
     with recovery and protection."""

    BACKUP_RETENTION_DAYS = 30  # How long to keep backups

    def __init__(self, root_path: Optional[Path] = None):
        super().__init__()
        self.root_path = root_path or Path(dw_folder.get_folder())
        self.backup_path = self.root_path / '.backups'
        self.backup_path.mkdir(parents=True, exist_ok=True)

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

    def save_preset(self, nodes: List[str], preset_name: str, cache_name: Optional[str] = None) -> PresetInfo:
        """Save node attributes as a preset."""
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
                version=self._get_next_version(preset_name),
                cache_name=cache_name,
                solver=solver
            )

            # Save to file
            self._save_preset_to_file(preset_info)

            return preset_info

        except Exception as e:
            logger.error(f"Failed to save preset {preset_name}: {e}")
            raise

    def load_preset(self, preset_info: PresetInfo, target_nodes: List[str], blend: float = 1.0) -> bool:
        """Load and apply a preset to target nodes."""
        try:
            from dw_maya.dw_presets_io import dw_preset

            # Validate target nodes
            if not all(self._get_preset_type(node) == preset_info.node_type for node in target_nodes):
                raise ValueError("Target nodes must match preset type")

            # Apply preset attributes with blending
            for node in target_nodes:
                dw_preset.blendAttrDic(
                    srcNode=list(preset_info.attributes.keys())[0],
                    targetNode=node,
                    preset=preset_info.attributes,
                    blendValue=blend
                )

            self.current_preset = preset_info
            return True

        except Exception as e:
            logger.error(f"Failed to load preset {preset_info.name}: {e}")
            return False

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

    def _get_next_version(self, preset_name: str) -> str:
        """Get next available version number for preset."""
        existing = list(self.root_path.glob(f"{preset_name}_v*.json"))
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
                "solver": preset_info.solver
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
                solver=data["info"].get("solver")
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



class PresetWidget(QtWidgets.QWidget):
    """Widget for managing simulation presets."""

    preset_applied = QtCore.Signal(PresetInfo)  # Emitted when preset is applied

    def __init__(self, parent=None):
        super().__init__(parent)
        self.preset_manager = PresetManager()
        self._setup_ui()

    def _setup_ui(self):
        """Initialize UI components."""
        layout = QtWidgets.QVBoxLayout(self)

        # Preset list
        self.preset_list = QtWidgets.QTreeWidget()
        self.preset_list.setHeaderLabels(["Name", "Version", "Type"])
        self.preset_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
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
        self.save_btn.clicked.connect(self._save_preset)
        self.load_btn.clicked.connect(self._load_preset)
        self.delete_btn.clicked.connect(self._delete_preset)

    def _update_blend_label(self, value):
        """Update blend value label."""
        self.blend_label.setText(f"{value}%")

    def set_node(self, node):
        """Update preset list for current node."""
        self.current_node = node
        self._refresh_presets()

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
                preset.node_type.value
            ])
            item.setData(0, QtCore.Qt.UserRole, preset)
            self.preset_list.addTopLevelItem(item)

    def _save_preset(self):
        """Save current node settings as preset."""
        if not self.current_node:
            return

        name, ok = QtWidgets.QInputDialog.getText(
            self, "Save Preset", "Enter preset name:"
        )
        if ok and name:
            try:
                preset = self.preset_manager.save_preset(
                    [self.current_node],
                    name
                )
                self._refresh_presets()

                QtWidgets.QMessageBox.information(
                    self,
                    "Success",
                    f"Preset '{name}' saved successfully!"
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
                blend_value
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
