"""Parameter panel: every field maps to one EncodeSettings attribute."""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core import encode


class ParamsPanel(QWidget):
    """Form over EncodeSettings, persisted through QSettings between runs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self.load_settings()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        video_box = QGroupBox("Video")
        video_form = QFormLayout(video_box)

        self.container = QComboBox()
        self.container.addItems(encode.CONTAINERS)
        video_form.addRow("Container", self.container)

        self.codec = QComboBox()
        for label, name in encode.VIDEO_CODECS.items():
            self.codec.addItem(label, name)
        video_form.addRow("Codec", self.codec)

        self.crf = QSpinBox()
        self.crf.setRange(0, 51)
        self.crf.setToolTip("Constant rate factor: lower = better quality / bigger file. 18 is visually lossless for x264.")
        video_form.addRow("Quality (CRF)", self.crf)

        self.preset = QComboBox()
        self.preset.addItems(encode.PRESETS)
        self.preset.setToolTip("Encoder speed/size trade-off. Slower presets compress better at the same CRF.")
        video_form.addRow("Preset", self.preset)

        self.pixel_format = QComboBox()
        self.pixel_format.addItems(encode.PIXEL_FORMATS)
        self.pixel_format.setToolTip("yuv420p is the only format every player accepts.")
        video_form.addRow("Pixel format", self.pixel_format)

        self.max_width = QSpinBox()
        self.max_width.setRange(0, 16384)
        self.max_width.setSingleStep(2)
        self.max_width.setSpecialValueText("source")
        self.max_width.setToolTip("Downscale to this width when the source is wider. Never upscales.")
        video_form.addRow("Max width", self.max_width)

        self.fps = QDoubleSpinBox()
        self.fps.setRange(0.0, 240.0)
        self.fps.setDecimals(3)
        self.fps.setSpecialValueText("source")
        video_form.addRow("Frame rate", self.fps)

        layout.addWidget(video_box)

        self.audio_box = QGroupBox("Audio")
        self.audio_box.setCheckable(True)
        audio_form = QFormLayout(self.audio_box)

        self.audio_codec = QComboBox()
        for label, name in encode.AUDIO_CODECS.items():
            self.audio_codec.addItem(label, name)
        audio_form.addRow("Codec", self.audio_codec)

        self.audio_bitrate = QSpinBox()
        self.audio_bitrate.setRange(32, 512)
        self.audio_bitrate.setSingleStep(32)
        self.audio_bitrate.setSuffix(" kbps")
        audio_form.addRow("Bitrate", self.audio_bitrate)

        layout.addWidget(self.audio_box)

        output_box = QGroupBox("Output")
        output_form = QFormLayout(output_box)

        self.suffix = QLineEdit()
        self.suffix.setPlaceholderText("e.g. _h264")
        self.suffix.setToolTip("Appended to the file name before the extension.")
        output_form.addRow("Name suffix", self.suffix)

        self.faststart = QCheckBox("Web-ready (moov atom first)")
        output_form.addRow(self.faststart)

        self.overwrite = QCheckBox("Overwrite existing output")
        output_form.addRow(self.overwrite)

        layout.addWidget(output_box)
        layout.addStretch(1)

    # --------------------------------------------------------------- settings
    def settings(self) -> encode.EncodeSettings:
        return encode.EncodeSettings(
            container=self.container.currentText(),
            video_codec=self.codec.currentData(),
            crf=self.crf.value(),
            preset=self.preset.currentText(),
            pixel_format=self.pixel_format.currentText(),
            max_width=self.max_width.value(),
            fps=self.fps.value(),
            audio_enabled=self.audio_box.isChecked(),
            audio_codec=self.audio_codec.currentData(),
            audio_bitrate=self.audio_bitrate.value(),
            faststart=self.faststart.isChecked(),
            overwrite=self.overwrite.isChecked(),
            suffix=self.suffix.text().strip(),
        )

    def apply_settings(self, settings: encode.EncodeSettings) -> None:
        self.container.setCurrentText(settings.container)
        index = self.codec.findData(settings.video_codec)
        self.codec.setCurrentIndex(max(index, 0))
        self.crf.setValue(settings.crf)
        self.preset.setCurrentText(settings.preset)
        self.pixel_format.setCurrentText(settings.pixel_format)
        self.max_width.setValue(settings.max_width)
        self.fps.setValue(settings.fps)
        self.audio_box.setChecked(settings.audio_enabled)
        index = self.audio_codec.findData(settings.audio_codec)
        self.audio_codec.setCurrentIndex(max(index, 0))
        self.audio_bitrate.setValue(settings.audio_bitrate)
        self.faststart.setChecked(settings.faststart)
        self.overwrite.setChecked(settings.overwrite)
        self.suffix.setText(settings.suffix)

    def load_settings(self) -> None:
        store = QSettings("dw_open_tools", "dw_video_reformat")
        defaults = encode.EncodeSettings()
        loaded = encode.EncodeSettings(
            container=store.value("container", defaults.container),
            video_codec=store.value("video_codec", defaults.video_codec),
            crf=int(store.value("crf", defaults.crf)),
            preset=store.value("preset", defaults.preset),
            pixel_format=store.value("pixel_format", defaults.pixel_format),
            max_width=int(store.value("max_width", defaults.max_width)),
            fps=float(store.value("fps", defaults.fps)),
            audio_enabled=_to_bool(store.value("audio_enabled", defaults.audio_enabled)),
            audio_codec=store.value("audio_codec", defaults.audio_codec),
            audio_bitrate=int(store.value("audio_bitrate", defaults.audio_bitrate)),
            faststart=_to_bool(store.value("faststart", defaults.faststart)),
            overwrite=_to_bool(store.value("overwrite", defaults.overwrite)),
            suffix=store.value("suffix", defaults.suffix),
        )
        self.apply_settings(loaded)

    def save_settings(self) -> None:
        store = QSettings("dw_open_tools", "dw_video_reformat")
        for key, value in vars(self.settings()).items():
            store.setValue(key, value)

    def reset_defaults(self) -> None:
        self.apply_settings(encode.EncodeSettings())


def _to_bool(value) -> bool:
    # QSettings hands back "true"/"false" strings on some platforms
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes")
    return bool(value)
