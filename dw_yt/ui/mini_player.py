from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from ui.waveform_widget import WaveformWidget
from ui.waveform_worker import WaveformWorker


class MiniPlayer(QWidget):
    """Play/pause/seek/volume for one track at a time, with a waveform
    scrub bar for jumping to a specific spot in the track."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._audio_output.setVolume(0.8)
        self._player.setAudioOutput(self._audio_output)

        self._player.playbackStateChanged.connect(self._update_play_button)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.positionChanged.connect(self._on_position_changed)

        self._waveform_worker: WaveformWorker | None = None
        self._current_path: str | None = None

        layout = QVBoxLayout(self)

        self.waveform = WaveformWidget()
        self.waveform.seek_requested.connect(self._on_seek_requested)
        layout.addWidget(self.waveform)

        controls_row = QHBoxLayout()

        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(32)
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._toggle_play)
        controls_row.addWidget(self.play_btn)

        self.title_label = QLabel("(nothing playing)")
        self.title_label.setMinimumWidth(160)
        controls_row.addWidget(self.title_label)

        controls_row.addStretch(1)

        self.time_label = QLabel("0:00 / 0:00")
        controls_row.addWidget(self.time_label)

        controls_row.addWidget(QLabel("Vol"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.valueChanged.connect(lambda v: self._audio_output.setVolume(v / 100))
        controls_row.addWidget(self.volume_slider)

        layout.addLayout(controls_row)

    def play(self, filepath: str, title: str) -> None:
        self._current_path = filepath
        self._player.setSource(QUrl.fromLocalFile(filepath))
        self.title_label.setText(title)
        self.play_btn.setEnabled(True)
        self._player.play()
        self._load_waveform(filepath)

    def current_path(self) -> str | None:
        return self._current_path

    def stop(self) -> None:
        """Stop and release the loaded file — needed before deleting it,
        since Windows keeps an open file locked while QMediaPlayer holds it."""
        self._player.stop()
        self._player.setSource(QUrl())
        self._current_path = None
        self.title_label.setText("(nothing playing)")
        self.play_btn.setEnabled(False)
        self.waveform.clear()

    def _load_waveform(self, filepath: str) -> None:
        self.waveform.clear(loading=True)

        # A stale worker (from a track we've since left) is left to finish
        # on its own; _on_waveform_ready/_failed no-op once source_path no
        # longer matches self._current_path, so it's harmless either way.
        worker = WaveformWorker(Path(filepath))
        worker.finished_ok.connect(lambda path, src=filepath: self._on_waveform_ready(src, path))
        worker.failed.connect(lambda src=filepath: self._on_waveform_failed(src))
        worker.finished.connect(worker.deleteLater)
        self._waveform_worker = worker
        worker.start()

    def _on_waveform_ready(self, source_path: str, image_path: Path) -> None:
        if source_path == self._current_path:  # ignore stale results from a track we've since left
            self.waveform.set_image(image_path)

    def _on_waveform_failed(self, source_path: str) -> None:
        if source_path == self._current_path:
            self.waveform.set_unavailable()

    def _on_seek_requested(self, fraction: float) -> None:
        duration = self._player.duration()
        if duration > 0:
            self._player.setPosition(int(fraction * duration))

    def _toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _update_play_button(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setText("⏸" if playing else "▶")

    def _on_duration_changed(self, _duration: int) -> None:
        self._update_time_label()

    def _on_position_changed(self, position: int) -> None:
        duration = self._player.duration()
        if duration > 0:
            self.waveform.set_progress(position / duration)
        self._update_time_label()

    def _update_time_label(self) -> None:
        pos = self._format_ms(self._player.position())
        dur = self._format_ms(self._player.duration())
        self.time_label.setText(f"{pos} / {dur}")

    @staticmethod
    def _format_ms(ms: int) -> str:
        seconds = max(ms, 0) // 1000
        return f"{seconds // 60}:{seconds % 60:02d}"
