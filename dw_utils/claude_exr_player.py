#!/usr/bin/env python3
"""
EXR Sequence Player
A simple player for viewing EXR image sequences with playback controls.
"""

import sys
import os
import re
import glob
from pathlib import Path
from typing import Optional, List, Tuple
import numpy as np

try:
    import OpenImageIO as oiio
except ImportError:
    oiio = None

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QSlider, QFileDialog, QSpinBox, QComboBox,
        QStatusBar, QGroupBox, QCheckBox, QDoubleSpinBox, QSplitter,
        QMessageBox, QProgressBar
    )
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
    from PyQt6.QtGui import QImage, QPixmap, QKeySequence, QShortcut, QAction
except ImportError:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QSlider, QFileDialog, QSpinBox, QComboBox,
        QStatusBar, QGroupBox, QCheckBox, QDoubleSpinBox, QSplitter,
        QMessageBox, QProgressBar
    )
    from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
    from PyQt5.QtGui import QImage, QPixmap, QKeySequence, QShortcut
    from PyQt5.QtWidgets import QAction


def read_exr_with_oiio(filepath: str) -> Optional[np.ndarray]:
    """Read EXR file using OpenImageIO."""
    if oiio is None:
        return None

    inp = oiio.ImageInput.open(filepath)
    if inp is None:
        print(f"Error opening {filepath}: {oiio.geterror()}")
        return None

    spec = inp.spec()
    pixels = inp.read_image(format=oiio.FLOAT)
    inp.close()

    if pixels is None:
        return None

    # Reshape to height x width x channels
    pixels = pixels.reshape(spec.height, spec.width, spec.nchannels)
    return pixels


def read_exr_with_cv2(filepath: str) -> Optional[np.ndarray]:
    """Read EXR file using OpenCV."""
    try:
        import cv2
        img = cv2.imread(filepath, cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
        if img is not None:
            # OpenCV reads as BGR, convert to RGB
            if len(img.shape) == 3 and img.shape[2] >= 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            return img.astype(np.float32)
    except ImportError:
        pass
    return None


def read_exr_with_imageio(filepath: str) -> Optional[np.ndarray]:
    """Read EXR file using imageio."""
    try:
        import imageio
        img = imageio.imread(filepath)
        return img.astype(np.float32)
    except Exception:
        pass
    return None


def read_exr(filepath: str) -> Optional[np.ndarray]:
    """Read EXR file using available library."""
    # Try OpenImageIO first (best EXR support)
    img = read_exr_with_oiio(filepath)
    if img is not None:
        return img

    # Try OpenCV
    img = read_exr_with_cv2(filepath)
    if img is not None:
        return img

    # Try imageio
    img = read_exr_with_imageio(filepath)
    if img is not None:
        return img

    return None


def find_sequence(filepath: str) -> Tuple[List[str], int, int]:
    """
    Find all files in a sequence given one file from the sequence.
    Returns (sorted list of files, start frame, end frame).
    """
    directory = os.path.dirname(filepath) or "."
    filename = os.path.basename(filepath)

    # Common sequence patterns: name.0001.exr, name_0001.exr, name0001.exr
    patterns = [
        (r'^(.+?)\.(\d+)\.(\w+)$', '{}.{:0{}d}.{}'),  # name.0001.exr
        (r'^(.+?)_(\d+)\.(\w+)$', '{}_{:0{}d}.{}'),  # name_0001.exr
        (r'^(.+?)(\d+)\.(\w+)$', '{}{:0{}d}.{}'),  # name0001.exr
    ]

    for pattern, fmt in patterns:
        match = re.match(pattern, filename)
        if match:
            prefix, frame_str, ext = match.groups()
            padding = len(frame_str)

            # Find all matching files
            files = []
            for f in os.listdir(directory):
                m = re.match(pattern, f)
                if m and m.group(1) == prefix and m.group(3) == ext:
                    files.append((int(m.group(2)), os.path.join(directory, f)))

            files.sort(key=lambda x: x[0])

            if files:
                frames = [f[0] for f in files]
                paths = [f[1] for f in files]
                return paths, min(frames), max(frames)

    # Single file
    return [filepath], 1, 1


def apply_tone_mapping(img: np.ndarray, exposure: float = 0.0,
                       gamma: float = 2.2, method: str = "reinhard") -> np.ndarray:
    """Apply tone mapping and exposure adjustment to HDR image."""
    # Apply exposure
    img = img * (2.0 ** exposure)

    # Ensure we have 3 channels for tone mapping
    if len(img.shape) == 2:
        img = np.stack([img, img, img], axis=-1)
    elif img.shape[2] == 1:
        img = np.repeat(img, 3, axis=-1)
    elif img.shape[2] == 4:
        # Keep alpha separate
        alpha = img[:, :, 3:4]
        img = img[:, :, :3]
    else:
        alpha = None

    if method == "reinhard":
        # Reinhard tone mapping
        img = img / (1.0 + img)
    elif method == "filmic":
        # Filmic tone mapping (ACES-like)
        a = 2.51
        b = 0.03
        c = 2.43
        d = 0.59
        e = 0.14
        img = np.clip((img * (a * img + b)) / (img * (c * img + d) + e), 0, 1)
    elif method == "linear":
        # Just clamp
        img = np.clip(img, 0, 1)

    # Apply gamma
    img = np.power(np.clip(img, 0, 1), 1.0 / gamma)

    # Recombine alpha if present
    if alpha is not None:
        alpha = np.clip(alpha, 0, 1)
        img = np.concatenate([img, alpha], axis=-1)

    return img


class ImageLoader(QThread):
    """Background thread for loading images."""
    image_loaded = pyqtSignal(int, np.ndarray)

    def __init__(self, filepath: str, frame_index: int):
        super().__init__()
        self.filepath = filepath
        self.frame_index = frame_index

    def run(self):
        img = read_exr(self.filepath)
        if img is not None:
            self.image_loaded.emit(self.frame_index, img)


class ImageViewer(QLabel):
    """Widget for displaying images with zoom and pan."""

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(640, 480)
        self.setStyleSheet("background-color: #1a1a1a;")
        self._pixmap = None
        self._zoom = 1.0

    def set_image(self, qimage: QImage):
        """Set the image to display."""
        self._pixmap = QPixmap.fromImage(qimage)
        self._update_display()

    def _update_display(self):
        """Update the displayed image."""
        if self._pixmap is None:
            return

        # Scale to fit while maintaining aspect ratio
        scaled = self._pixmap.scaled(
            self.size() * self._zoom,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.setPixmap(scaled)

    def resizeEvent(self, event):
        """Handle resize events."""
        super().resizeEvent(event)
        self._update_display()

    def set_zoom(self, zoom: float):
        """Set zoom level."""
        self._zoom = max(0.1, min(10.0, zoom))
        self._update_display()


class EXRPlayer(QMainWindow):
    """Main window for EXR sequence player."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("EXR Sequence Player")
        self.setMinimumSize(800, 600)

        # State
        self.sequence: List[str] = []
        self.current_frame = 0
        self.start_frame = 1
        self.end_frame = 1
        self.fps = 24.0
        self.playing = False
        self.cache: dict = {}
        self.max_cache_size = 100

        # Playback timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)

        self._setup_ui()
        self._setup_shortcuts()

    def _setup_ui(self):
        """Set up the user interface."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(5)

        # Image viewer
        self.viewer = ImageViewer()
        layout.addWidget(self.viewer, 1)

        # Controls panel
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        # Timeline slider
        timeline_layout = QHBoxLayout()
        self.frame_label = QLabel("Frame: 1")
        self.frame_label.setMinimumWidth(80)
        timeline_layout.addWidget(self.frame_label)

        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setMinimum(0)
        self.timeline.setMaximum(0)
        self.timeline.valueChanged.connect(self.on_timeline_changed)
        timeline_layout.addWidget(self.timeline)

        self.range_label = QLabel("1-1")
        self.range_label.setMinimumWidth(60)
        timeline_layout.addWidget(self.range_label)

        controls_layout.addLayout(timeline_layout)

        # Playback controls
        playback_layout = QHBoxLayout()

        self.btn_start = QPushButton("⏮")
        self.btn_start.setFixedWidth(40)
        self.btn_start.clicked.connect(self.go_to_start)
        playback_layout.addWidget(self.btn_start)

        self.btn_prev = QPushButton("⏪")
        self.btn_prev.setFixedWidth(40)
        self.btn_prev.clicked.connect(self.prev_frame)
        playback_layout.addWidget(self.btn_prev)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(60)
        self.btn_play.clicked.connect(self.toggle_play)
        playback_layout.addWidget(self.btn_play)

        self.btn_next = QPushButton("⏩")
        self.btn_next.setFixedWidth(40)
        self.btn_next.clicked.connect(self.next_frame)
        playback_layout.addWidget(self.btn_next)

        self.btn_end = QPushButton("⏭")
        self.btn_end.setFixedWidth(40)
        self.btn_end.clicked.connect(self.go_to_end)
        playback_layout.addWidget(self.btn_end)

        playback_layout.addSpacing(20)

        # FPS control
        playback_layout.addWidget(QLabel("FPS:"))
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(24)
        self.fps_spin.valueChanged.connect(self.on_fps_changed)
        playback_layout.addWidget(self.fps_spin)

        # Loop control
        self.loop_check = QCheckBox("Loop")
        self.loop_check.setChecked(True)
        playback_layout.addWidget(self.loop_check)

        playback_layout.addStretch()

        # Tone mapping controls
        playback_layout.addWidget(QLabel("Exposure:"))
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setRange(-10, 10)
        self.exposure_spin.setValue(0)
        self.exposure_spin.setSingleStep(0.1)
        self.exposure_spin.valueChanged.connect(self.update_display)
        playback_layout.addWidget(self.exposure_spin)

        playback_layout.addWidget(QLabel("Gamma:"))
        self.gamma_spin = QDoubleSpinBox()
        self.gamma_spin.setRange(0.1, 5)
        self.gamma_spin.setValue(2.2)
        self.gamma_spin.setSingleStep(0.1)
        self.gamma_spin.valueChanged.connect(self.update_display)
        playback_layout.addWidget(self.gamma_spin)

        playback_layout.addWidget(QLabel("Tonemap:"))
        self.tonemap_combo = QComboBox()
        self.tonemap_combo.addItems(["reinhard", "filmic", "linear"])
        self.tonemap_combo.currentTextChanged.connect(self.update_display)
        playback_layout.addWidget(self.tonemap_combo)

        # Open button
        self.btn_open = QPushButton("Open...")
        self.btn_open.clicked.connect(self.open_file)
        playback_layout.addWidget(self.btn_open)

        controls_layout.addLayout(playback_layout)
        layout.addWidget(controls)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready - Open an EXR file or sequence")

    def _setup_shortcuts(self):
        """Set up keyboard shortcuts."""
        QShortcut(QKeySequence("Space"), self, self.toggle_play)
        QShortcut(QKeySequence("Left"), self, self.prev_frame)
        QShortcut(QKeySequence("Right"), self, self.next_frame)
        QShortcut(QKeySequence("Home"), self, self.go_to_start)
        QShortcut(QKeySequence("End"), self, self.go_to_end)
        QShortcut(QKeySequence("Ctrl+O"), self, self.open_file)

    def open_file(self):
        """Open file dialog to select EXR file."""
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Open EXR File",
            "",
            "EXR Files (*.exr);;All Files (*)"
        )

        if filepath:
            self.load_sequence(filepath)

    def load_sequence(self, filepath: str):
        """Load an EXR sequence from a single file."""
        self.stop_playback()
        self.cache.clear()

        # Find sequence
        self.sequence, self.start_frame, self.end_frame = find_sequence(filepath)

        if not self.sequence:
            QMessageBox.warning(self, "Error", f"Could not load: {filepath}")
            return

        # Update UI
        self.timeline.setMaximum(len(self.sequence) - 1)
        self.range_label.setText(f"{self.start_frame}-{self.end_frame}")
        self.current_frame = 0
        self.timeline.setValue(0)

        # Load first frame
        self.update_display()

        seq_info = f"Loaded {len(self.sequence)} frames ({self.start_frame}-{self.end_frame})"
        self.status.showMessage(seq_info)
        self.setWindowTitle(f"EXR Player - {os.path.basename(filepath)}")

    def get_current_image(self) -> Optional[np.ndarray]:
        """Get the current frame's image data."""
        if not self.sequence or self.current_frame >= len(self.sequence):
            return None

        # Check cache
        if self.current_frame in self.cache:
            return self.cache[self.current_frame]

        # Load image
        filepath = self.sequence[self.current_frame]
        img = read_exr(filepath)

        if img is not None:
            # Cache it
            if len(self.cache) >= self.max_cache_size:
                # Remove oldest entry
                oldest = min(self.cache.keys())
                del self.cache[oldest]
            self.cache[self.current_frame] = img

        return img

    def update_display(self):
        """Update the displayed image."""
        img = self.get_current_image()

        if img is None:
            self.status.showMessage("Error loading frame")
            return

        # Apply tone mapping
        exposure = self.exposure_spin.value()
        gamma = self.gamma_spin.value()
        method = self.tonemap_combo.currentText()

        display = apply_tone_mapping(img, exposure, gamma, method)

        # Convert to 8-bit
        display = (display * 255).astype(np.uint8)

        # Create QImage
        h, w = display.shape[:2]
        if len(display.shape) == 2:
            qimage = QImage(display.data, w, h, w, QImage.Format.Format_Grayscale8)
        elif display.shape[2] == 3:
            qimage = QImage(display.data, w, h, w * 3, QImage.Format.Format_RGB888)
        elif display.shape[2] == 4:
            qimage = QImage(display.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
        else:
            return

        self.viewer.set_image(qimage)

        # Update frame label
        actual_frame = self.start_frame + self.current_frame
        self.frame_label.setText(f"Frame: {actual_frame}")

        # Preload next frames
        self._preload_frames()

    def _preload_frames(self):
        """Preload nearby frames in the background."""
        for offset in [1, 2, -1]:
            frame = self.current_frame + offset
            if 0 <= frame < len(self.sequence) and frame not in self.cache:
                # Simple sync load for now
                # Could be made async with QThread
                pass

    def on_timeline_changed(self, value: int):
        """Handle timeline slider changes."""
        if value != self.current_frame:
            self.current_frame = value
            self.update_display()

    def on_fps_changed(self, value: float):
        """Handle FPS changes."""
        self.fps = value
        if self.playing:
            self.timer.setInterval(int(1000 / self.fps))

    def toggle_play(self):
        """Toggle playback."""
        if self.playing:
            self.stop_playback()
        else:
            self.start_playback()

    def start_playback(self):
        """Start playback."""
        if not self.sequence:
            return

        self.playing = True
        self.btn_play.setText("⏸")
        self.timer.start(int(1000 / self.fps))

    def stop_playback(self):
        """Stop playback."""
        self.playing = False
        self.btn_play.setText("▶")
        self.timer.stop()

    def next_frame(self):
        """Go to next frame."""
        if not self.sequence:
            return

        self.current_frame += 1

        if self.current_frame >= len(self.sequence):
            if self.loop_check.isChecked():
                self.current_frame = 0
            else:
                self.current_frame = len(self.sequence) - 1
                self.stop_playback()

        self.timeline.setValue(self.current_frame)
        self.update_display()

    def prev_frame(self):
        """Go to previous frame."""
        if not self.sequence:
            return

        self.current_frame -= 1

        if self.current_frame < 0:
            if self.loop_check.isChecked():
                self.current_frame = len(self.sequence) - 1
            else:
                self.current_frame = 0

        self.timeline.setValue(self.current_frame)
        self.update_display()

    def go_to_start(self):
        """Go to first frame."""
        self.current_frame = 0
        self.timeline.setValue(0)
        self.update_display()

    def go_to_end(self):
        """Go to last frame."""
        if self.sequence:
            self.current_frame = len(self.sequence) - 1
            self.timeline.setValue(self.current_frame)
            self.update_display()

    def dragEnterEvent(self, event):
        """Handle drag enter events."""
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """Handle drop events."""
        urls = event.mimeData().urls()
        if urls:
            filepath = urls[0].toLocalFile()
            if filepath.lower().endswith('.exr'):
                self.load_sequence(filepath)


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # Dark theme
    from PyQt6.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)

    window = EXRPlayer()
    window.show()

    # Load file from command line if provided
    if len(sys.argv) > 1:
        window.load_sequence(sys.argv[1])

    sys.exit(app.exec())


if __name__ == "__main__":
    main()