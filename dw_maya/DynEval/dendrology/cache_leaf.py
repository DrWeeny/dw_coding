from dataclasses import dataclass
from typing import Optional, List, Dict, Union
from enum import Enum
from PySide6 import QtWidgets, QtGui, QtCore
from pathlib import Path
import maya.cmds as cmds
from dw_logger import get_logger

logger = get_logger()


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


class CacheColors:
    """Color definitions for different cache types."""
    MAYA_BLUE = QtGui.QColor(68, 78, 88)
    GEO_RED = QtGui.QColor(128, 18, 18)
    NCLOTH_GREEN = QtGui.QColor(29, 128, 18)
    ABC_PURPLE = QtGui.QColor(104, 66, 129)

    @classmethod
    def get_color(cls, cache_type: CacheType) -> QtGui.QColor:
        return {
            CacheType.NCACHE: cls.NCLOTH_GREEN,
            CacheType.GEOCACHE: cls.GEO_RED,
            CacheType.ALEMBIC: cls.ABC_PURPLE
        }.get(cache_type, cls.MAYA_BLUE)


class CacheItem(QtWidgets.QTreeWidgetItem):
    """Enhanced tree widget item for caches."""

    def __init__(self, cache_info: CacheInfo):
        super().__init__()
        self.cache_info = cache_info
        self._setup_display()

    def _setup_display(self):
        """Configure item display properties."""
        self.setText(0, self.cache_info.name)
        self.setText(1, f"v{self.cache_info.version:03d}")

        # Set background color based on type and state
        color = CacheColors.get_color(self.cache_info.cache_type)
        if self.cache_info.is_attached:
            color = CacheColors.MAYA_BLUE

        brush = QtGui.QBrush(color)
        brush.setStyle(QtCore.Qt.SolidPattern)
        self.setBackground(0, brush)
        self.setBackground(1, brush)

        # Set font based on state
        font = QtGui.QFont()
        font.setPointSize(10 if self.cache_info.is_attached else 8)
        self.setFont(0, font)
        self.setFont(1, font)

        # Set validity icon
        if self.cache_info.is_valid:
            self.setIcon(0, self._get_validity_icon())

    def _get_validity_icon(self) -> QtGui.QIcon:
        """Get the appropriate icon for cache validity."""
        return QtGui.QIcon(str(Path(__file__).parent / "icons" / "cache_approved.png"))

    @property
    def cache_path(self) -> Path:
        return self.cache_info.path