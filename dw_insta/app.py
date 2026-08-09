from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from config import AppConfig
from ui.main_window import MainWindow
from ui.today_widget import TodayTray


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # keep running in the tray after the window is closed

    config = AppConfig.load()

    window = MainWindow(config)
    window.show()

    tray = TodayTray(config, app, main_window=window)
    tray.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
