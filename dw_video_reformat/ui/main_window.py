"""Main window: drop queue on the left, param panel on the right."""
from __future__ import annotations

import pathlib

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core import encode
from ui import encode_worker
from ui import wgt_drop_queue
from ui import wgt_params


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("dw_video_reformat")
        self.setAcceptDrops(True)
        self._worker = None
        self._build()
        self._restore_geometry()
        if not encode.ffmpeg_available():
            self.statusBar().showMessage("ffmpeg not found on PATH - encoding will fail")
            self.start_btn.setEnabled(False)

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        splitter = QSplitter()
        root.addWidget(splitter, 1)

        # left: queue + its buttons
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.queue = wgt_drop_queue.DropQueue()
        self.queue.paths_dropped.connect(self.add_paths)
        left_layout.addWidget(self.queue, 1)

        queue_btns = QHBoxLayout()
        self.add_btn = QPushButton("Add files...")
        self.add_btn.clicked.connect(self._on_add_files)
        self.remove_btn = QPushButton("Remove selected")
        self.remove_btn.clicked.connect(self.queue.remove_selected)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.queue.clear_all)
        queue_btns.addWidget(self.add_btn)
        queue_btns.addWidget(self.remove_btn)
        queue_btns.addWidget(self.clear_btn)
        queue_btns.addStretch(1)
        left_layout.addLayout(queue_btns)
        splitter.addWidget(left)

        # right: params
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.params = wgt_params.ParamsPanel()
        right_layout.addWidget(self.params, 1)
        self.reset_btn = QPushButton("Reset defaults")
        self.reset_btn.clicked.connect(self.params.reset_defaults)
        right_layout.addWidget(self.reset_btn)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        self.splitter = splitter

        # bottom: run controls
        run_bar = QHBoxLayout()
        self.summary = QLabel("")
        run_bar.addWidget(self.summary, 1)
        self.open_btn = QPushButton("Open output folder")
        self.open_btn.clicked.connect(self._on_open_output)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.start_btn = QPushButton("Start")
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self._on_start)
        run_bar.addWidget(self.open_btn)
        run_bar.addWidget(self.cancel_btn)
        run_bar.addWidget(self.start_btn)
        root.addLayout(run_bar)

        self.statusBar()

    # ------------------------------------------------------------ persistence
    def _restore_geometry(self) -> None:
        store = QSettings("dw_open_tools", "dw_video_reformat")
        geometry = store.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1000, 560)
        splitter_state = store.value("window/splitter")
        if splitter_state is not None:
            self.splitter.restoreState(splitter_state)

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            answer = QMessageBox.question(
                self, "dw_video_reformat", "An encode is running. Cancel it and quit?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._worker.cancel()
            self._worker.wait(10_000)
        store = QSettings("dw_open_tools", "dw_video_reformat")
        store.setValue("window/geometry", self.saveGeometry())
        store.setValue("window/splitter", self.splitter.saveState())
        self.params.save_settings()
        super().closeEvent(event)

    # -------------------------------------------------------------- drag/drop
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [
            pathlib.Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        self.add_paths(paths)
        event.acceptProposedAction()

    # ------------------------------------------------------------------ queue
    def add_paths(self, paths: list) -> None:
        added = 0
        for source in encode.collect_videos(paths):
            if self.queue.contains(source.path):
                continue
            self.queue.add_source(source)
            added += 1
        if added == 0:
            self.statusBar().showMessage("No new video files in the dropped items", 4000)
        else:
            self.statusBar().showMessage(f"Added {added} video(s)", 4000)
        self.queue.viewport().update()

    def _on_add_files(self) -> None:
        exts = " ".join(f"*{ext}" for ext in sorted(encode.VIDEO_EXTS))
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add videos", "", f"Videos ({exts});;All files (*)"
        )
        if files:
            self.add_paths([pathlib.Path(f) for f in files])

    def _on_open_output(self) -> None:
        sources = self.queue.sources()
        if not sources:
            return
        rows = {index.row() for index in self.queue.selectedIndexes()}
        source = sources[min(rows)] if rows else sources[0]
        folder = source.root / encode.OUT_SUBFOLDER
        if not folder.is_dir():
            folder = source.root
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # -------------------------------------------------------------------- run
    def _on_start(self) -> None:
        sources = self.queue.sources()
        if not sources:
            self.statusBar().showMessage("Queue is empty", 4000)
            return
        settings = self.params.settings()
        self.params.save_settings()
        self.queue.reset_progress()
        self._set_running(True)
        self._done = 0
        self._failed = 0
        self.summary.setText(f"0 / {len(sources)}")

        self._worker = encode_worker.EncodeWorker(sources, settings, self)
        self._worker.job_started.connect(self.queue.set_running)
        self._worker.job_progress.connect(self.queue.set_progress)
        self._worker.job_finished.connect(self._on_job_finished)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.statusBar().showMessage("Cancelling...")

    def _on_job_finished(self, row: int, status: str, message: str) -> None:
        self.queue.set_finished(row, status, message)
        if status == "done":
            self._done += 1
        elif status == "failed":
            self._failed += 1
        total = self.queue.rowCount()
        text = f"{self._done} / {total} done"
        if self._failed:
            text += f", {self._failed} failed"
        self.summary.setText(text)

    def _on_all_done(self) -> None:
        self._set_running(False)
        self.statusBar().showMessage(f"Finished: {self.summary.text()}", 8000)
        self._worker = None

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.add_btn.setEnabled(not running)
        self.remove_btn.setEnabled(not running)
        self.clear_btn.setEnabled(not running)
        self.reset_btn.setEnabled(not running)
        self.params.setEnabled(not running)
        self.queue.setAcceptDrops(not running)
        self.setAcceptDrops(not running)
