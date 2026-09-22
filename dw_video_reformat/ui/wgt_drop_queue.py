"""Drop zone + job queue: one row per video with its own progress bar."""
from __future__ import annotations

import pathlib

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
)

COL_FILE = 0
COL_FOLDER = 1
COL_STATUS = 2

STATUS_COLORS = {
    "done": QColor(60, 140, 60),
    "skipped": QColor(150, 130, 40),
    "cancelled": QColor(120, 120, 120),
    "failed": QColor(170, 50, 50),
}


class DropQueue(QTableWidget):
    """Table that accepts dropped files/folders and tracks per-row encode state."""

    paths_dropped = Signal(list)   # list[pathlib.Path], files and/or folders

    def __init__(self, parent=None):
        super().__init__(0, 3, parent)
        self.setAcceptDrops(True)
        self.setHorizontalHeaderLabels(["File", "Root folder", "Status"])
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        header = self.horizontalHeader()
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_FOLDER, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(COL_STATUS, 140)
        self._sources = []

    # ------------------------------------------------------------- drag/drop
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        paths = [
            pathlib.Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            self.paths_dropped.emit(paths)
        event.acceptProposedAction()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.rowCount() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(QColor(128, 128, 128))
            painter.drawText(
                self.viewport().rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Drop videos or folders here",
            )
            painter.end()

    # ----------------------------------------------------------------- queue
    def sources(self) -> list:
        return list(self._sources)

    def contains(self, path: pathlib.Path) -> bool:
        key = str(path.resolve()).lower()
        return any(str(s.path.resolve()).lower() == key for s in self._sources)

    def add_source(self, source) -> int:
        """Append an encode.Source: file column shows the path relative to its root."""
        row = self.rowCount()
        self.insertRow(row)
        file_item = QTableWidgetItem(str(source.relative))
        file_item.setToolTip(str(source.path))
        folder_item = QTableWidgetItem(str(source.root))
        folder_item.setToolTip(str(source.root))
        self.setItem(row, COL_FILE, file_item)
        self.setItem(row, COL_FOLDER, folder_item)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setFormat("queued")
        bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCellWidget(row, COL_STATUS, bar)
        self._sources.append(source)
        return row

    def remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.selectedIndexes()}, reverse=True)
        for row in rows:
            self.removeRow(row)
            del self._sources[row]
        self.viewport().update()

    def clear_all(self) -> None:
        self.setRowCount(0)
        self._sources = []
        self.viewport().update()

    def reset_progress(self) -> None:
        for row in range(self.rowCount()):
            bar = self.cellWidget(row, COL_STATUS)
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFormat("queued")
            bar.setStyleSheet("")
            bar.setToolTip("")

    # ---------------------------------------------------------------- status
    def set_running(self, row: int) -> None:
        bar = self.cellWidget(row, COL_STATUS)
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setFormat("%p%")

    def set_progress(self, row: int, fraction: float) -> None:
        bar = self.cellWidget(row, COL_STATUS)
        if fraction < 0:
            bar.setRange(0, 0)           # indeterminate: no duration known
            bar.setFormat("encoding")
            return
        bar.setRange(0, 100)
        bar.setValue(int(round(fraction * 100)))

    def set_finished(self, row: int, status: str, message: str) -> None:
        bar = self.cellWidget(row, COL_STATUS)
        bar.setRange(0, 100)
        bar.setValue(100 if status == "done" else 0)
        bar.setFormat(status)
        bar.setToolTip(message)
        color = STATUS_COLORS.get(status)
        if color is not None:
            bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {color.name()}; }}"
                f"QProgressBar {{ color: {'white' if status == 'done' else color.name()}; }}"
            )
