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

    @staticmethod
    def _get_log_path() -> Path:
        """Get the appropriate log file path based on environment."""
        # Try to get Maya's script directory first
        try:
            maya_app_dir = Path(cmds.internalVar(userAppDir=True))
            log_dir = maya_app_dir / "logs" / "dw_tools"
        except Exception:
            # Fallback to user's home directory if not in Maya
            log_dir = Path.home() / ".dw_tools" / "logs"

        # Create logs directory if it doesn't exist
        log_dir.mkdir(parents=True, exist_ok=True)

        return log_dir / "dw_tools.log"

    def _setup_logger(self) -> logging.Logger:
        """Configure the main logger for DW Tools."""
        # Create logger
        logger = logging.getLogger("dw_tools")
        logger.setLevel(logging.INFO)

        # Clear any existing handlers
        logger.handlers = []

        # Create formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s - %(message)s'
        )
        simple_formatter = logging.Formatter(
            '%(levelname)s - %(message)s'
        )

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(simple_formatter)
        console_handler.setLevel(logging.INFO)
        logger.addHandler(console_handler)

        # File handler
        try:
            log_file = self._get_log_path()
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10MB
                backupCount=5  # Keep 5 backup files
            )
            file_handler.setFormatter(detailed_formatter)
            file_handler.setLevel(logging.DEBUG)  # More detailed in file
            logger.addHandler(file_handler)

            # Log the initialization
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


# Convenience function to get logger
def get_logger() -> logging.Logger:
    """Get the DW Tools logger instance."""
    return DWLogger.get_logger()