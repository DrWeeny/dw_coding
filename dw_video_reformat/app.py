"""dw_video_reformat entry point.

Run from anywhere::

    python dw_video_reformat/app.py

The folder of this file is the import root (flat ``from core import ...``),
so the app is launched as a script, not as ``python -m``.
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("dw_open_tools")
    app.setApplicationName("dw_video_reformat")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
