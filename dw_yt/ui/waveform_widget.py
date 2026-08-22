from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class WaveformWidget(QWidget):
    """A visual scrub bar: shows the track's waveform and lets you click or
    drag to jump straight to a spot in it — for finding a specific small
    bit inside a track rather than scrubbing blind."""

    seek_requested = Signal(float)  # fraction 0..1

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(90)
        self.setMinimumWidth(200)
        self._pixmap: Optional[QPixmap] = None
        self._loading = False
        self._progress = 0.0

    def clear(self, loading: bool = False) -> None:
        self._pixmap = None
        self._loading = loading
        self._progress = 0.0
        self.update()

    def set_image(self, path: Path) -> None:
        self._pixmap = QPixmap(str(path))
        self._loading = False
        self.update()

    def set_unavailable(self) -> None:
        self._loading = False
        self.update()

    def set_progress(self, fraction: float) -> None:
        self._progress = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = self.rect()

        if self._pixmap is None or self._pixmap.isNull():
            painter.fillRect(rect, self.palette().alternateBase())
            painter.setPen(QPen(self.palette().mid().color()))
            text = "Loading waveform..." if self._loading else "Click to seek"
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        else:
            painter.drawPixmap(rect, self._pixmap)

        x = int(rect.width() * self._progress)
        painter.setPen(QPen(Qt.GlobalColor.red, 2))
        painter.drawLine(x, 0, x, rect.height())

    def _seek_from_event(self, event: QMouseEvent) -> None:
        fraction = max(0.0, min(1.0, event.position().x() / max(self.width(), 1)))
        self.seek_requested.emit(fraction)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._seek_from_event(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._seek_from_event(event)
