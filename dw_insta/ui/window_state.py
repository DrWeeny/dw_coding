from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMainWindow, QTableView

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "window_settings.ini"

# QTableView column index -> settings key. Column 0 (Photos) is deliberately
# excluded: its width is always derived from the thumbnail size setting
# instead, so there's a single source of truth (see MainWindow._apply_thumb_size).
COLUMN_KEYS = {1: "col_date", 2: "col_caption", 3: "col_hashtags"}
DEFAULT_COLUMN_WIDTHS = {1: 90, 2: 500, 3: 200}
DEFAULT_SIZE = (1000, 940)
DEFAULT_THUMB_SIZE = 48


def get_thumb_size() -> int:
    return get_settings().value("thumb_size", DEFAULT_THUMB_SIZE, type=int)


def set_thumb_size(size: int) -> None:
    get_settings().setValue("thumb_size", size)


def get_hide_archived() -> bool:
    return get_settings().value("hide_archived", False, type=bool)


def set_hide_archived(hide: bool) -> None:
    get_settings().setValue("hide_archived", hide)


def get_settings() -> QSettings:
    return QSettings(str(SETTINGS_PATH), QSettings.Format.IniFormat)


def _is_on_screen(window: QMainWindow) -> bool:
    """True if the window's frame is at least partly visible on some
    currently-connected screen. Catches the case where a window position
    was saved on a multi-monitor setup and a monitor has since gone away
    (e.g. undocking a laptop), which would otherwise leave the window
    permanently off-screen and unreachable."""
    frame = window.frameGeometry()
    return any(screen.availableGeometry().intersects(frame) for screen in QGuiApplication.screens())


def reset_window_state(window: QMainWindow) -> None:
    width, height = DEFAULT_SIZE
    window.resize(width, height)
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        x = available.x() + max(0, (available.width() - width) // 2)
        y = available.y() + max(0, (available.height() - height) // 2)
        window.move(x, y)


def restore_window_state(window: QMainWindow, table: QTableView) -> None:
    settings = get_settings()

    geometry = settings.value("geometry")
    restored = False
    if isinstance(geometry, (QByteArray, bytes, bytearray)) and geometry:
        restored = window.restoreGeometry(geometry)

    if not restored or not _is_on_screen(window):
        reset_window_state(window)

    for col, key in COLUMN_KEYS.items():
        table.setColumnWidth(col, settings.value(key, DEFAULT_COLUMN_WIDTHS[col], type=int))


def save_window_state(window: QMainWindow, table: QTableView) -> None:
    settings = get_settings()
    settings.setValue("geometry", window.saveGeometry())
    for col, key in COLUMN_KEYS.items():
        settings.setValue(key, table.columnWidth(col))
