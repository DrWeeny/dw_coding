from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from config import AppConfig
from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)

    config = AppConfig.load()

    window = MainWindow(config)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
