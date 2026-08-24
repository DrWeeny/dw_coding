from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from core.waveform import ensure_waveform_image


class WaveformWorker(QThread):
    finished_ok = Signal(Path)
    failed = Signal()

    def __init__(self, audio_path: Path, parent=None):
        super().__init__(parent)
        self.audio_path = audio_path

    def run(self) -> None:
        image_path = ensure_waveform_image(self.audio_path)
        if image_path:
            self.finished_ok.emit(image_path)
        else:
            self.failed.emit()
