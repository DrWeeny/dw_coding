from __future__ import annotations

import os
import sys

# Qt Multimedia's bundled FFmpeg backend dumps raw libav output (stream
# info, decoder warnings) straight to the console — harmless but noisy,
# and not something Qt's own logging rules can filter since it bypasses
# QLoggingCategory entirely. The native Windows Media Foundation backend
# plays the same files with no console spam.
os.environ.setdefault("QT_MEDIA_BACKEND", "windows")

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
