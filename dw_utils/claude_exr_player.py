#!/usr/bin/env python3
"""
EXR Sequence Player with Drawing/Annotation Support
A player for viewing EXR image sequences with playback controls and frame markup tools.
Inspired by RV and KeyframePro annotation workflows.
"""

import sys
import os
import re
import json
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from dataclasses import dataclass, field
from enum import Enum
import numpy as np

try:
    import OpenImageIO as oiio
except ImportError:
    oiio = None

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QFileDialog, QSpinBox, QComboBox,
    QStatusBar, QCheckBox, QDoubleSpinBox, QMessageBox, QColorDialog,
    QToolBar, QInputDialog
)
from PySide6.QtCore import Qt, QTimer, Signal, QPointF, QRectF, QSize
from PySide6.QtGui import (
    QImage, QPixmap, QKeySequence, QShortcut, QAction, QPainter, QPen,
    QColor, QPainterPath, QCursor, QFont, QPalette
)


# =============================================================================
# Drawing Data Structures
# =============================================================================

class DrawingTool(Enum):
    NONE = "none"
    FREEHAND = "freehand"
    LINE = "line"
    ARROW = "arrow"
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    TEXT = "text"
    ERASER = "eraser"


@dataclass
class Stroke:
    """A single drawing stroke."""
    tool: str
    points: List[Tuple[float, float]]  # Normalized 0-1 coordinates
    color: Tuple[int, int, int, int] = (255, 0, 0, 255)
    width: float = 3.0
    text: str = ""  # For text annotations

    def to_dict(self) -> dict:
        return {
            'tool': self.tool,
            'points': self.points,
            'color': self.color,
            'width': self.width,
            'text': self.text
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Stroke':
        return cls(
            tool=data['tool'],
            points=[tuple(p) for p in data['points']],
            color=tuple(data['color']),
            width=data['width'],
            text=data.get('text', '')
        )


@dataclass
class FrameAnnotation:
    """Annotations for a single frame."""
    frame: int
    strokes: List[Stroke] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'frame': self.frame,
            'strokes': [s.to_dict() for s in self.strokes]
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'FrameAnnotation':
        return cls(
            frame=data['frame'],
            strokes=[Stroke.from_dict(s) for s in data['strokes']]
        )


class AnnotationManager:
    """Manages annotations across all frames."""

    def __init__(self):
        self.annotations: Dict[int, FrameAnnotation] = {}
        self.global_strokes: List[Stroke] = []

    def get_annotation(self, frame: int) -> FrameAnnotation:
        if frame not in self.annotations:
            self.annotations[frame] = FrameAnnotation(frame=frame)
        return self.annotations[frame]

    def add_stroke(self, frame: int, stroke: Stroke, global_stroke: bool = False):
        if global_stroke:
            self.global_strokes.append(stroke)
        else:
            self.get_annotation(frame).strokes.append(stroke)

    def get_strokes(self, frame: int, include_global: bool = True) -> List[Stroke]:
        strokes = []
        if include_global:
            strokes.extend(self.global_strokes)
        if frame in self.annotations:
            strokes.extend(self.annotations[frame].strokes)
        return strokes

    def clear_frame(self, frame: int):
        if frame in self.annotations:
            self.annotations[frame].strokes.clear()

    def clear_all(self):
        self.annotations.clear()
        self.global_strokes.clear()

    def undo_last(self, frame: int) -> bool:
        if frame in self.annotations and self.annotations[frame].strokes:
            self.annotations[frame].strokes.pop()
            return True
        return False

    def has_annotations(self, frame: int) -> bool:
        return frame in self.annotations and len(self.annotations[frame].strokes) > 0

    def get_annotated_frames(self) -> List[int]:
        return sorted([f for f, a in self.annotations.items() if a.strokes])

    def save(self, filepath: str):
        data = {
            'version': 1,
            'global_strokes': [s.to_dict() for s in self.global_strokes],
            'annotations': [a.to_dict() for a in self.annotations.values() if a.strokes]
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    def load(self, filepath: str):
        with open(filepath, 'r') as f:
            data = json.load(f)

        self.clear_all()
        self.global_strokes = [Stroke.from_dict(s) for s in data.get('global_strokes', [])]
        for ann_data in data.get('annotations', []):
            ann = FrameAnnotation.from_dict(ann_data)
            self.annotations[ann.frame] = ann


# =============================================================================
# EXR Reading
# =============================================================================

def read_exr_with_oiio(filepath: str) -> Optional[np.ndarray]:
    if oiio is None:
        return None
    inp = oiio.ImageInput.open(filepath)
    if inp is None:
        return None
    spec = inp.spec()
    pixels = inp.read_image(format=oiio.FLOAT)
    inp.close()
    if pixels is None:
        return None
    return pixels.reshape(spec.height, spec.width, spec.nchannels)


def read_exr_with_cv2(filepath: str) -> Optional[np.ndarray]:
    try:
        import cv2
        img = cv2.imread(filepath, cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
        if img is not None:
            if len(img.shape) == 3 and img.shape[2] >= 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            return img.astype(np.float32)
    except ImportError:
        pass
    return None


def read_exr_with_imageio(filepath: str) -> Optional[np.ndarray]:
    try:
        import imageio
        return imageio.imread(filepath).astype(np.float32)
    except Exception:
        pass
    return None


def read_exr(filepath: str) -> Optional[np.ndarray]:
    for reader in [read_exr_with_oiio, read_exr_with_cv2, read_exr_with_imageio]:
        img = reader(filepath)
        if img is not None:
            return img
    return None


def find_sequence(filepath: str) -> Tuple[List[str], int, int]:
    directory = os.path.dirname(filepath) or "."
    filename = os.path.basename(filepath)

    patterns = [
        (r'^(.+?)\.(\d+)\.(\w+)$', '{}.{:0{}d}.{}'),
        (r'^(.+?)_(\d+)\.(\w+)$', '{}_{:0{}d}.{}'),
        (r'^(.+?)(\d+)\.(\w+)$', '{}{:0{}d}.{}'),
    ]

    for pattern, fmt in patterns:
        match = re.match(pattern, filename)
        if match:
            prefix, frame_str, ext = match.groups()
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

    return [filepath], 1, 1


def apply_tone_mapping(img: np.ndarray, exposure: float = 0.0,
                       gamma: float = 2.2, method: str = "reinhard") -> np.ndarray:
    img = img * (2.0 ** exposure)

    if len(img.shape) == 2:
        img = np.stack([img, img, img], axis=-1)
    elif img.shape[2] == 1:
        img = np.repeat(img, 3, axis=-1)
    elif img.shape[2] == 4:
        alpha = img[:, :, 3:4]
        img = img[:, :, :3]
    else:
        alpha = None

    if method == "reinhard":
        img = img / (1.0 + img)
    elif method == "filmic":
        a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
        img = np.clip((img * (a * img + b)) / (img * (c * img + d) + e), 0, 1)
    elif method == "linear":
        img = np.clip(img, 0, 1)

    img = np.power(np.clip(img, 0, 1), 1.0 / gamma)

    if alpha is not None:
        img = np.concatenate([img, np.clip(alpha, 0, 1)], axis=-1)

    return img


# =============================================================================
# Drawing Canvas Widget
# =============================================================================

class DrawingCanvas(QLabel):
    """Widget for displaying images with drawing overlay."""

    stroke_completed = Signal(Stroke)
    text_requested = Signal(QPointF)

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(640, 480)
        self.setStyleSheet("background-color: #1a1a1a;")
        self.setMouseTracking(True)

        self._base_pixmap: Optional[QPixmap] = None
        self._display_rect = QRectF()

        self.tool = DrawingTool.NONE
        self.pen_color = QColor(255, 50, 50, 255)
        self.pen_width = 3.0
        self.drawing = False
        self.current_points: List[QPointF] = []

        self.strokes: List[Stroke] = []

        self.onion_skin_enabled = False
        self.onion_frames: List[Tuple[QPixmap, float]] = []

    def set_image(self, qimage: QImage):
        self._base_pixmap = QPixmap.fromImage(qimage)
        self._update_display_rect()
        self.update()

    def set_strokes(self, strokes: List[Stroke]):
        self.strokes = strokes
        self.update()

    def set_onion_frames(self, frames: List[Tuple[QImage, float]]):
        self.onion_frames = [(QPixmap.fromImage(img), opacity) for img, opacity in frames]
        self.update()

    def _update_display_rect(self):
        if self._base_pixmap is None:
            return

        widget_size = self.size()
        img_size = self._base_pixmap.size()

        scale = min(
            widget_size.width() / img_size.width(),
            widget_size.height() / img_size.height()
        )

        scaled_width = img_size.width() * scale
        scaled_height = img_size.height() * scale

        x = (widget_size.width() - scaled_width) / 2
        y = (widget_size.height() - scaled_height) / 2

        self._display_rect = QRectF(x, y, scaled_width, scaled_height)

    def _widget_to_normalized(self, pos: QPointF) -> Tuple[float, float]:
        if self._display_rect.width() == 0 or self._display_rect.height() == 0:
            return (0, 0)
        x = (pos.x() - self._display_rect.x()) / self._display_rect.width()
        y = (pos.y() - self._display_rect.y()) / self._display_rect.height()
        return (x, y)

    def _normalized_to_widget(self, nx: float, ny: float) -> QPointF:
        x = self._display_rect.x() + nx * self._display_rect.width()
        y = self._display_rect.y() + ny * self._display_rect.height()
        return QPointF(x, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display_rect()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(26, 26, 26))

        if self._base_pixmap is None:
            return

        # Onion skin
        if self.onion_skin_enabled:
            for pixmap, opacity in self.onion_frames:
                painter.setOpacity(opacity)
                scaled = pixmap.scaled(
                    int(self._display_rect.width()),
                    int(self._display_rect.height()),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                painter.drawPixmap(int(self._display_rect.x()), int(self._display_rect.y()), scaled)

        # Main image
        painter.setOpacity(1.0)
        scaled = self._base_pixmap.scaled(
            int(self._display_rect.width()),
            int(self._display_rect.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        painter.drawPixmap(int(self._display_rect.x()), int(self._display_rect.y()), scaled)

        # Existing strokes
        for stroke in self.strokes:
            self._draw_stroke(painter, stroke)

        # Current stroke
        if self.drawing and self.current_points:
            current_stroke = Stroke(
                tool=self.tool.value,
                points=[(p.x(), p.y()) for p in self.current_points],
                color=(self.pen_color.red(), self.pen_color.green(),
                       self.pen_color.blue(), self.pen_color.alpha()),
                width=self.pen_width
            )
            self._draw_stroke(painter, current_stroke, in_progress=True)

    def _draw_stroke(self, painter: QPainter, stroke: Stroke, in_progress: bool = False):
        if not stroke.points:
            return

        color = QColor(*stroke.color)
        pen = QPen(color, stroke.width, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if in_progress:
            points = [QPointF(p[0], p[1]) for p in stroke.points]
        else:
            points = [self._normalized_to_widget(p[0], p[1]) for p in stroke.points]

        tool = stroke.tool

        if tool in ["freehand", "eraser"]:
            if len(points) > 1:
                path = QPainterPath(points[0])
                for p in points[1:]:
                    path.lineTo(p)
                painter.drawPath(path)

        elif tool == "line":
            if len(points) >= 2:
                painter.drawLine(points[0], points[-1])

        elif tool == "arrow":
            if len(points) >= 2:
                p1, p2 = points[0], points[-1]
                painter.drawLine(p1, p2)

                import math
                angle = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
                arrow_size = stroke.width * 4

                arrow_p1 = QPointF(
                    p2.x() - arrow_size * math.cos(angle - math.pi / 6),
                    p2.y() - arrow_size * math.sin(angle - math.pi / 6)
                )
                arrow_p2 = QPointF(
                    p2.x() - arrow_size * math.cos(angle + math.pi / 6),
                    p2.y() - arrow_size * math.sin(angle + math.pi / 6)
                )

                arrow_path = QPainterPath(p2)
                arrow_path.lineTo(arrow_p1)
                arrow_path.moveTo(p2)
                arrow_path.lineTo(arrow_p2)
                painter.drawPath(arrow_path)

        elif tool == "rectangle":
            if len(points) >= 2:
                rect = QRectF(points[0], points[-1]).normalized()
                painter.drawRect(rect)

        elif tool == "ellipse":
            if len(points) >= 2:
                rect = QRectF(points[0], points[-1]).normalized()
                painter.drawEllipse(rect)

        elif tool == "text" and stroke.text:
            if points:
                font = QFont("Arial", int(stroke.width * 4))
                painter.setFont(font)
                painter.drawText(points[0], stroke.text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.tool != DrawingTool.NONE:
            if self.tool == DrawingTool.TEXT:
                self.text_requested.emit(event.position())
            else:
                self.drawing = True
                self.current_points = [event.position()]
                self.update()

    def mouseMoveEvent(self, event):
        if self.drawing:
            pos = event.position()
            if self.tool in [DrawingTool.FREEHAND, DrawingTool.ERASER]:
                self.current_points.append(pos)
            else:
                if len(self.current_points) > 1:
                    self.current_points[-1] = pos
                else:
                    self.current_points.append(pos)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drawing:
            self.drawing = False

            if self.current_points:
                normalized_points = [self._widget_to_normalized(p) for p in self.current_points]
                stroke = Stroke(
                    tool=self.tool.value,
                    points=normalized_points,
                    color=(self.pen_color.red(), self.pen_color.green(),
                           self.pen_color.blue(), self.pen_color.alpha()),
                    width=self.pen_width
                )
                self.stroke_completed.emit(stroke)

            self.current_points.clear()
            self.update()


# =============================================================================
# Main Player Window
# =============================================================================

class EXRPlayer(QMainWindow):
    """Main window for EXR sequence player with drawing support."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("EXR Sequence Player")
        self.setMinimumSize(1024, 768)

        self.sequence: List[str] = []
        self.current_frame = 0
        self.start_frame = 1
        self.end_frame = 1
        self.fps = 24.0
        self.playing = False
        self.cache: dict = {}
        self.max_cache_size = 100

        self.annotations = AnnotationManager()
        self.global_drawing = False

        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)

        self._setup_ui()
        self._setup_toolbar()
        self._setup_shortcuts()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(5)

        self.canvas = DrawingCanvas()
        self.canvas.stroke_completed.connect(self.on_stroke_completed)
        self.canvas.text_requested.connect(self.on_text_requested)
        layout.addWidget(self.canvas, 1)

        # Timeline
        timeline_widget = QWidget()
        timeline_layout = QVBoxLayout(timeline_widget)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_layout.setSpacing(2)

        self.marker_bar = QLabel()
        self.marker_bar.setFixedHeight(8)
        self.marker_bar.setStyleSheet("background-color: #333;")
        timeline_layout.addWidget(self.marker_bar)

        slider_layout = QHBoxLayout()
        self.frame_label = QLabel("Frame: 1")
        self.frame_label.setMinimumWidth(100)
        slider_layout.addWidget(self.frame_label)

        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.setMinimum(0)
        self.timeline.setMaximum(0)
        self.timeline.valueChanged.connect(self.on_timeline_changed)
        slider_layout.addWidget(self.timeline)

        self.range_label = QLabel("1-1")
        self.range_label.setMinimumWidth(60)
        slider_layout.addWidget(self.range_label)

        timeline_layout.addLayout(slider_layout)
        layout.addWidget(timeline_widget)

        # Playback controls
        controls = QWidget()
        playback_layout = QHBoxLayout(controls)
        playback_layout.setContentsMargins(0, 0, 0, 0)

        for text, callback in [
            ("⏮", self.go_to_start),
            ("⏪", self.prev_frame),
            ("▶", self.toggle_play),
            ("⏩", self.next_frame),
            ("⏭", self.go_to_end),
        ]:
            btn = QPushButton(text)
            btn.setFixedWidth(40 if text != "▶" else 60)
            btn.clicked.connect(callback)
            if text == "▶":
                self.btn_play = btn
            playback_layout.addWidget(btn)

        playback_layout.addSpacing(10)

        playback_layout.addWidget(QLabel("FPS:"))
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(24)
        self.fps_spin.valueChanged.connect(self.on_fps_changed)
        playback_layout.addWidget(self.fps_spin)

        self.loop_check = QCheckBox("Loop")
        self.loop_check.setChecked(True)
        playback_layout.addWidget(self.loop_check)

        playback_layout.addSpacing(10)

        self.onion_check = QCheckBox("Onion")
        self.onion_check.toggled.connect(self.toggle_onion_skin)
        playback_layout.addWidget(self.onion_check)

        playback_layout.addStretch()

        playback_layout.addWidget(QLabel("Exp:"))
        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setRange(-10, 10)
        self.exposure_spin.setValue(0)
        self.exposure_spin.setSingleStep(0.25)
        self.exposure_spin.valueChanged.connect(self.update_display)
        playback_layout.addWidget(self.exposure_spin)

        playback_layout.addWidget(QLabel("γ:"))
        self.gamma_spin = QDoubleSpinBox()
        self.gamma_spin.setRange(0.1, 5)
        self.gamma_spin.setValue(2.2)
        self.gamma_spin.setSingleStep(0.1)
        self.gamma_spin.valueChanged.connect(self.update_display)
        playback_layout.addWidget(self.gamma_spin)

        self.tonemap_combo = QComboBox()
        self.tonemap_combo.addItems(["reinhard", "filmic", "linear"])
        self.tonemap_combo.currentTextChanged.connect(self.update_display)
        playback_layout.addWidget(self.tonemap_combo)

        btn_open = QPushButton("Open...")
        btn_open.clicked.connect(self.open_file)
        playback_layout.addWidget(btn_open)

        layout.addWidget(controls)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready - Open an EXR file or sequence")

    def _setup_toolbar(self):
        toolbar = QToolBar("Drawing Tools")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, toolbar)

        self.tool_actions = {}
        tools = [
            (DrawingTool.NONE, "Select", "V"),
            (DrawingTool.FREEHAND, "Brush", "B"),
            (DrawingTool.LINE, "Line", "L"),
            (DrawingTool.ARROW, "Arrow", "A"),
            (DrawingTool.RECTANGLE, "Rect", "R"),
            (DrawingTool.ELLIPSE, "Ellipse", "E"),
            (DrawingTool.TEXT, "Text", "T"),
            (DrawingTool.ERASER, "Eraser", "X"),
        ]

        for tool, name, shortcut in tools:
            action = QAction(name, self)
            action.setCheckable(True)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda checked, t=tool: self.set_tool(t))
            toolbar.addAction(action)
            self.tool_actions[tool] = action

        self.tool_actions[DrawingTool.NONE].setChecked(True)

        toolbar.addSeparator()

        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(32, 32)
        self.color_btn.setStyleSheet("background-color: #ff3232; border: 2px solid #666;")
        self.color_btn.clicked.connect(self.pick_color)
        toolbar.addWidget(self.color_btn)

        toolbar.addWidget(QLabel(" Size:"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(1, 50)
        self.size_spin.setValue(3)
        self.size_spin.valueChanged.connect(lambda v: setattr(self.canvas, 'pen_width', v))
        toolbar.addWidget(self.size_spin)

        toolbar.addSeparator()

        self.global_action = QAction("Global", self)
        self.global_action.setCheckable(True)
        self.global_action.setToolTip("Draw on all frames")
        self.global_action.toggled.connect(lambda v: setattr(self, 'global_drawing', v))
        toolbar.addAction(self.global_action)

        toolbar.addSeparator()

        undo_action = QAction("Undo", self)
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(self.undo_stroke)
        toolbar.addAction(undo_action)

        clear_action = QAction("Clear", self)
        clear_action.triggered.connect(self.clear_frame_annotations)
        toolbar.addAction(clear_action)

        clear_all_action = QAction("Clear All", self)
        clear_all_action.triggered.connect(self.clear_all_annotations)
        toolbar.addAction(clear_all_action)

        toolbar.addSeparator()

        save_action = QAction("Save", self)
        save_action.setShortcut("Ctrl+Shift+S")
        save_action.triggered.connect(self.save_annotations)
        toolbar.addAction(save_action)

        load_action = QAction("Load", self)
        load_action.triggered.connect(self.load_annotations)
        toolbar.addAction(load_action)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Space"), self, self.toggle_play)
        QShortcut(QKeySequence("Left"), self, self.prev_frame)
        QShortcut(QKeySequence("Right"), self, self.next_frame)
        QShortcut(QKeySequence("Home"), self, self.go_to_start)
        QShortcut(QKeySequence("End"), self, self.go_to_end)
        QShortcut(QKeySequence("Ctrl+O"), self, self.open_file)
        QShortcut(QKeySequence("["), self, lambda: self.size_spin.setValue(max(1, self.size_spin.value() - 1)))
        QShortcut(QKeySequence("]"), self, lambda: self.size_spin.setValue(min(50, self.size_spin.value() + 1)))

    def set_tool(self, tool: DrawingTool):
        self.canvas.tool = tool
        for t, action in self.tool_actions.items():
            action.setChecked(t == tool)

        if tool in [DrawingTool.ERASER, DrawingTool.TEXT]:
            self.canvas.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        elif tool == DrawingTool.NONE:
            self.canvas.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        else:
            self.canvas.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    def pick_color(self):
        color = QColorDialog.getColor(self.canvas.pen_color, self, "Select Drawing Color")
        if color.isValid():
            self.canvas.pen_color = color
            self.color_btn.setStyleSheet(f"background-color: {color.name()}; border: 2px solid #666;")

    def on_stroke_completed(self, stroke: Stroke):
        actual_frame = self.start_frame + self.current_frame
        self.annotations.add_stroke(actual_frame, stroke, self.global_drawing)
        self.update_annotation_markers()
        self.update_display()

    def on_text_requested(self, pos: QPointF):
        text, ok = QInputDialog.getText(self, "Add Text", "Enter annotation text:")
        if ok and text:
            normalized = self.canvas._widget_to_normalized(pos)
            stroke = Stroke(
                tool="text",
                points=[normalized],
                color=(self.canvas.pen_color.red(), self.canvas.pen_color.green(),
                       self.canvas.pen_color.blue(), self.canvas.pen_color.alpha()),
                width=self.canvas.pen_width,
                text=text
            )
            actual_frame = self.start_frame + self.current_frame
            self.annotations.add_stroke(actual_frame, stroke, self.global_drawing)
            self.update_annotation_markers()
            self.update_display()

    def undo_stroke(self):
        actual_frame = self.start_frame + self.current_frame
        if self.annotations.undo_last(actual_frame):
            self.update_annotation_markers()
            self.update_display()

    def clear_frame_annotations(self):
        actual_frame = self.start_frame + self.current_frame
        self.annotations.clear_frame(actual_frame)
        self.update_annotation_markers()
        self.update_display()

    def clear_all_annotations(self):
        reply = QMessageBox.question(
            self, "Clear All", "Clear all annotations?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.annotations.clear_all()
            self.update_annotation_markers()
            self.update_display()

    def save_annotations(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "Save Annotations", "", "JSON Files (*.json)")
        if filepath:
            self.annotations.save(filepath)
            self.status.showMessage(f"Saved annotations to {filepath}")

    def load_annotations(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Load Annotations", "", "JSON Files (*.json)")
        if filepath:
            self.annotations.load(filepath)
            self.update_annotation_markers()
            self.update_display()
            self.status.showMessage(f"Loaded annotations from {filepath}")

    def update_annotation_markers(self):
        if not self.sequence:
            return
        annotated = self.annotations.get_annotated_frames()
        if annotated:
            markers = ", ".join(str(f) for f in annotated[:10])
            if len(annotated) > 10:
                markers += f"... ({len(annotated)} total)"
            self.marker_bar.setText(f" ✏ {markers}")
            self.marker_bar.setStyleSheet("background-color: #553333; color: #ff9999; font-size: 10px;")
        else:
            self.marker_bar.setText("")
            self.marker_bar.setStyleSheet("background-color: #333;")

    def toggle_onion_skin(self, enabled: bool):
        self.canvas.onion_skin_enabled = enabled
        self.update_display()

    def open_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open EXR File", "", "EXR Files (*.exr);;All Files (*)"
        )
        if filepath:
            self.load_sequence(filepath)

    def load_sequence(self, filepath: str):
        self.stop_playback()
        self.cache.clear()

        self.sequence, self.start_frame, self.end_frame = find_sequence(filepath)

        if not self.sequence:
            QMessageBox.warning(self, "Error", f"Could not load: {filepath}")
            return

        self.timeline.setMaximum(len(self.sequence) - 1)
        self.range_label.setText(f"{self.start_frame}-{self.end_frame}")
        self.current_frame = 0
        self.timeline.setValue(0)

        self.update_display()
        self.update_annotation_markers()

        self.status.showMessage(f"Loaded {len(self.sequence)} frames ({self.start_frame}-{self.end_frame})")
        self.setWindowTitle(f"EXR Player - {os.path.basename(filepath)}")

    def get_frame_image(self, index: int) -> Optional[np.ndarray]:
        if not self.sequence or index < 0 or index >= len(self.sequence):
            return None

        if index in self.cache:
            return self.cache[index]

        filepath = self.sequence[index]
        img = read_exr(filepath)

        if img is not None:
            if len(self.cache) >= self.max_cache_size:
                oldest = min(self.cache.keys())
                del self.cache[oldest]
            self.cache[index] = img

        return img

    def get_current_image(self) -> Optional[np.ndarray]:
        return self.get_frame_image(self.current_frame)

    def _create_qimage(self, display: np.ndarray) -> Optional[QImage]:
        h, w = display.shape[:2]
        if len(display.shape) == 2:
            return QImage(display.data, w, h, w, QImage.Format.Format_Grayscale8)
        elif display.shape[2] == 3:
            return QImage(display.data, w, h, w * 3, QImage.Format.Format_RGB888)
        elif display.shape[2] == 4:
            return QImage(display.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
        return None

    def update_display(self):
        img = self.get_current_image()
        if img is None:
            self.status.showMessage("Error loading frame")
            return

        exposure = self.exposure_spin.value()
        gamma = self.gamma_spin.value()
        method = self.tonemap_combo.currentText()

        display = apply_tone_mapping(img, exposure, gamma, method)
        display = (display * 255).astype(np.uint8)
        display = np.ascontiguousarray(display)

        qimage = self._create_qimage(display)
        if qimage:
            self.canvas.set_image(qimage)

        actual_frame = self.start_frame + self.current_frame
        strokes = self.annotations.get_strokes(actual_frame)
        self.canvas.set_strokes(strokes)

        # Onion skin
        if self.canvas.onion_skin_enabled:
            onion_frames = []
            for offset, opacity in [(-2, 0.15), (-1, 0.3), (1, 0.3), (2, 0.15)]:
                idx = self.current_frame + offset
                if 0 <= idx < len(self.sequence):
                    onion_img = self.get_frame_image(idx)
                    if onion_img is not None:
                        onion_display = apply_tone_mapping(onion_img, exposure, gamma, method)
                        onion_display = (onion_display * 255).astype(np.uint8)
                        onion_display = np.ascontiguousarray(onion_display)
                        oq = self._create_qimage(onion_display)
                        if oq:
                            onion_frames.append((oq, opacity))
            self.canvas.set_onion_frames(onion_frames)
        else:
            self.canvas.set_onion_frames([])

        annotation_indicator = " ✏" if self.annotations.has_annotations(actual_frame) else ""
        self.frame_label.setText(f"Frame: {actual_frame}{annotation_indicator}")

    def on_timeline_changed(self, value: int):
        if value != self.current_frame:
            self.current_frame = value
            self.update_display()

    def on_fps_changed(self, value: float):
        self.fps = value
        if self.playing:
            self.timer.setInterval(int(1000 / self.fps))

    def toggle_play(self):
        if self.playing:
            self.stop_playback()
        else:
            self.start_playback()

    def start_playback(self):
        if not self.sequence:
            return
        self.playing = True
        self.btn_play.setText("⏸")
        self.timer.start(int(1000 / self.fps))

    def stop_playback(self):
        self.playing = False
        self.btn_play.setText("▶")
        self.timer.stop()

    def next_frame(self):
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
        self.current_frame = 0
        self.timeline.setValue(0)
        self.update_display()

    def go_to_end(self):
        if self.sequence:
            self.current_frame = len(self.sequence) - 1
            self.timeline.setValue(self.current_frame)
            self.update_display()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

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

    if len(sys.argv) > 1:
        window.load_sequence(sys.argv[1])

    sys.exit(app.exec())


if __name__ == "__main__":
    main()