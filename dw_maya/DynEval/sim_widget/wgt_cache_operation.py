from PySide6 import QtWidgets, QtCore, QtGui
from dataclasses import dataclass
from enum import Enum, auto
from typing import List, Optional
from pathlib import Path
from maya import cmds


class CacheType(Enum):
    NCACHE = "nCache"
    GEOCACHE = "geoCache"
    ALEMBIC = "alembic"

@dataclass
class CacheInfo:
    """Data container for cache information."""
    name: str
    path: Path
    node: str
    version: int
    cache_type: CacheType
    is_valid: bool = True
    is_attached: bool = False
    mesh: Optional[str] = None


class CacheOperationStatus(Enum):
    SUCCESS = auto()
    FAILED = auto()
    IN_PROGRESS = auto()

@dataclass
class OperationResult:
    """Result of a cache operation."""
    status: CacheOperationStatus
    message: str
    cache_info: Optional[CacheInfo] = None
    error: Optional[Exception] = None

class CacheOperationManager:
    """Manages cache operations with progress feedback and error handling."""

    def __init__(self, parent_widget: QtWidgets.QWidget):
        self.parent = parent_widget
        self._setup_progress_dialog()

    def _setup_progress_dialog(self):
        """Initialize progress dialog."""
        self.progress = QtWidgets.QProgressDialog(self.parent)
        self.progress.setWindowModality(QtCore.Qt.WindowModal)
        self.progress.setAutoClose(True)
        self.progress.setAutoReset(True)

    def attach_caches(self, cache_infos: List[CacheInfo]) -> List[OperationResult]:
        """Attach multiple caches with progress tracking."""
        results = []
        self.progress.setLabelText("Attaching Caches...")
        self.progress.setMaximum(len(cache_infos))

        for i, cache_info in enumerate(cache_infos):
            if self.progress.wasCanceled():
                break

            try:
                if cache_info.cache_type == CacheType.ALEMBIC:
                    result = self._attach_abc_cache(cache_info)
                else:
                    result = self._attach_ncache(cache_info)
                results.append(result)

            except Exception as e:
                results.append(OperationResult(
                    status=CacheOperationStatus.FAILED,
                    message=f"Failed to attach {cache_info.name}",
                    cache_info=cache_info,
                    error=e
                ))

            self.progress.setValue(i + 1)

        return results

    def _attach_ncache(self, cache_info: CacheInfo) -> OperationResult:
        """Attach nCache to node."""
        try:
            # Delete existing caches
            cmds.waitCursor(state=1)
            from . import cache_management
            cache_management.delete_caches([cache_info.node])

            # Attach new cache
            cache_node = cache_management.attach_ncache(
                str(cache_info.path),
                cache_info.node
            )

            cmds.waitCursor(state=0)
            return OperationResult(
                status=CacheOperationStatus.SUCCESS,
                message=f"Successfully attached cache to {cache_info.node}",
                cache_info=cache_info
            )

        except Exception as e:
            cmds.waitCursor(state=0)
            raise

    def _attach_abc_cache(self, cache_info: CacheInfo) -> OperationResult:
        """Attach Alembic cache to node."""
        try:
            # Set the cache path on the alembic node
            abc_attr = f"{cache_info.node}.filename"
            cmds.setAttr(abc_attr, str(cache_info.path), type='string')

            return OperationResult(
                status=CacheOperationStatus.SUCCESS,
                message=f"Successfully attached Alembic cache to {cache_info.node}",
                cache_info=cache_info
            )

        except Exception as e:
            raise

    def detach_caches(self, cache_infos: List[CacheInfo]) -> List[OperationResult]:
        """Detach multiple caches with progress tracking."""
        results = []
        self.progress.setLabelText("Detaching Caches...")
        self.progress.setMaximum(len(cache_infos))

        for i, cache_info in enumerate(cache_infos):
            if self.progress.wasCanceled():
                break

            try:
                if cache_info.cache_type == CacheType.ALEMBIC:
                    result = self._detach_abc_cache(cache_info)
                else:
                    result = self._detach_ncache(cache_info)
                results.append(result)

            except Exception as e:
                results.append(OperationResult(
                    status=CacheOperationStatus.FAILED,
                    message=f"Failed to detach {cache_info.name}",
                    cache_info=cache_info,
                    error=e
                ))

            self.progress.setValue(i + 1)

        return results

    def _detach_ncache(self, cache_info: CacheInfo) -> OperationResult:
        """Detach nCache from node."""
        try:
            cmds.waitCursor(state=1)
            from . import cache_management
            cache_management.delete_caches([cache_info.node])
            cmds.waitCursor(state=0)

            return OperationResult(
                status=CacheOperationStatus.SUCCESS,
                message=f"Successfully detached cache from {cache_info.node}",
                cache_info=cache_info
            )

        except Exception as e:
            cmds.waitCursor(state=0)
            raise

    def _detach_abc_cache(self, cache_info: CacheInfo) -> OperationResult:
        """Detach Alembic cache from node."""
        try:
            # Clear the cache path
            abc_attr = f"{cache_info.node}.filename"
            cmds.setAttr(abc_attr, "", type='string')

            return OperationResult(
                status=CacheOperationStatus.SUCCESS,
                message=f"Successfully detached Alembic cache from {cache_info.node}",
                cache_info=cache_info
            )

        except Exception as e:
            raise

    def materialize_caches(self, cache_infos: List[CacheInfo]) -> List[OperationResult]:
        """Create materialized versions of cached meshes."""
        results = []
        self.progress.setLabelText("Materializing Caches...")
        self.progress.setMaximum(len(cache_infos))

        for i, cache_info in enumerate(cache_infos):
            if self.progress.wasCanceled():
                break

            try:
                if not cache_info.mesh:
                    raise ValueError(f"No mesh found for {cache_info.name}")

                from . import cache_management
                materialized_mesh = cache_management.materialize(
                    cache_info.mesh,
                    str(cache_info.path)
                )

                results.append(OperationResult(
                    status=CacheOperationStatus.SUCCESS,
                    message=f"Successfully materialized {cache_info.name}",
                    cache_info=cache_info
                ))

            except Exception as e:
                results.append(OperationResult(
                    status=CacheOperationStatus.FAILED,
                    message=f"Failed to materialize {cache_info.name}",
                    cache_info=cache_info,
                    error=e
                ))

            self.progress.setValue(i + 1)

        return results