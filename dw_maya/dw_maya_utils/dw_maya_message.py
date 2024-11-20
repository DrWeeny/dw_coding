"""Provides standardized message handling utilities for Maya.

A lightweight module to display messages, warnings and errors in Maya, supporting
both the cmds and OpenMaya APIs with integrated Python logging.

Functions:
    message(): Display informational messages
    warning(): Display warning messages
    error(): Display error messages

Main Features:
    - Unified interface for Maya messages across cmds and OpenMaya APIs
    - Integrated Python logging support
    - Type-safe message handling with enum types
    - Backwards compatibility with legacy message functions

Common Usage:
    >>> from dw_maya_utils import message, warning, error
    >>> message("Operation completed successfully")
    >>> warning("Scene contains unused nodes")
    >>> error("Invalid node name")

Version: 1.0.0

Author:
    DrWeeny
"""

import sys
from enum import Enum, auto

from maya import cmds, mel
import maya.OpenMaya as om

from dw_logger import get_logger

# Configure logging
logger = get_logger()


class MessageType(Enum):
    """Enum for different types of Maya messages."""
    INFO = auto()
    WARNING = auto()
    ERROR = auto()


class MayaMessageHandler:
    """Handles displaying messages in Maya using either cmds or OpenMaya API."""

    @staticmethod
    def display_message(
            message: str,
            msg_type: MessageType,
            use_api: bool = False,
            log_message: bool = True
    ) -> None:
        """Display a message in Maya using either cmds or OpenMaya API.

        Args:
            message: The message text to display
            msg_type: Type of message (INFO, WARNING, ERROR)
            use_api: Whether to use OpenMaya API instead of cmds
            log_message: Whether to also log the message using Python logging

        Raises:
            ValueError: If an invalid message type is provided
        """
        if log_message:
            if msg_type == MessageType.ERROR:
                logger.error(message)
            elif msg_type == MessageType.WARNING:
                logger.warning(message)
            else:
                logger.info(message)

        if use_api:
            if msg_type == MessageType.ERROR:
                om.MGlobal.displayError(message)
            elif msg_type == MessageType.WARNING:
                om.MGlobal.displayWarning(message)
            else:
                om.MGlobal.displayInfo(message)
        else:
            if msg_type == MessageType.ERROR:
                cmds.error(message)
            elif msg_type == MessageType.WARNING:
                cmds.warning(message)
            else:
                sys.stdout.write(f"{message}\n")


def message(text: str, use_api: bool = False) -> None:
    """Display an info message in Maya.

    Args:
        text: The message to display
        use_api: Whether to use OpenMaya API instead of cmds
    """
    MayaMessageHandler.display_message(text, MessageType.INFO, use_api)


def warning(text: str, use_api: bool = False) -> None:
    """Display a warning message in Maya.

    Args:
        text: The warning message to display
        use_api: Whether to use OpenMaya API instead of cmds
    """
    MayaMessageHandler.display_message(text, MessageType.WARNING, use_api)


def error(text: str, use_api: bool = False) -> None:
    """Display an error message in Maya.

    Args:
        text: The error message to display
        use_api: Whether to use OpenMaya API instead of cmds
    """
    MayaMessageHandler.display_message(text, MessageType.ERROR, use_api)
