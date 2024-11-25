from pathlib import Path
import logging
from maya import cmds
from logging.handlers import RotatingFileHandler


class DWLogger:
    """
    Centralized logging configuration for DW Tools.
    Implements singleton pattern to ensure consistent logging across the toolkit.
    """
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DWLogger, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._initialized = True
            self.logger = self._setup_logger()
            self._debug_mode = False

    @property
    def debug_mode(self) -> bool:
        """Get current debug mode state"""
        return self._debug_mode

    @debug_mode.setter
    def debug_mode(self, value: bool):
        """Set debug mode and update handlers"""
        self._debug_mode = value
        level = logging.DEBUG if value else logging.INFO

        # Update console handler level
        for handler in self.logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler):
                handler.setLevel(level)

        # Log the change
        self.logger.info(f"Debug mode {'enabled' if value else 'disabled'}")

    @staticmethod
    def _get_log_path() -> Path:
        """Get the appropriate log file path based on environment."""
        try:
            maya_app_dir = Path(cmds.internalVar(userAppDir=True))
            log_dir = maya_app_dir / "logs" / "dw_tools"
        except Exception:
            log_dir = Path.home() / ".dw_tools" / "logs"

        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "dw_tools.log"

    def _setup_logger(self) -> logging.Logger:
        """Configure the main logger for DW Tools."""
        logger = logging.getLogger("dw_tools")
        logger.setLevel(logging.DEBUG)  # Set to DEBUG to allow all levels

        # Clear existing handlers
        logger.handlers = []

        # Create formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        simple_formatter = logging.Formatter(
            '%(levelname)s - %(message)s'
        )

        # Console handler (starts at INFO by default)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(simple_formatter)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)

        # File handler (always at DEBUG for troubleshooting)
        try:
            log_file = self._get_log_path()
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10MB
                backupCount=5
            )
            file_handler.setFormatter(detailed_formatter)
            file_handler.setLevel(logging.DEBUG)
            logger.addHandler(file_handler)

            logger.info(f"DW Tools log file initialized at: {log_file}")
        except Exception as e:
            logger.warning(f"Could not initialize log file: {str(e)}")

        return logger

    @classmethod
    def get_logger(cls) -> logging.Logger:
        """Get the configured logger instance."""
        if cls._instance is None:
            cls()
        return cls._instance.logger

    @classmethod
    def set_debug(cls, enabled: bool = True):
        """Class method to set debug mode"""
        if cls._instance is None:
            cls()
        cls._instance.debug_mode = enabled


# Convenience functions
def get_logger() -> logging.Logger:
    """Get the DW Tools logger instance."""
    return DWLogger.get_logger()


def set_debug(enabled: bool = True):
    """Enable/disable debug mode"""
    DWLogger.set_debug(enabled)