from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig
from core import database
from core.downloader import TrackResult
from core.library_scan import sync_library
from ui.download_worker import DownloadWorker
from ui.library_view import LibraryPanel
from ui.link_utils import extract_links
from ui.queue_row import QueueRow
from ui.tag_input import TagLineEdit


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.setWindowTitle("dw_yt")
        self.resize(760, 560)

        database.init_db()

        self._queue: list[QListWidgetItem] = []
        self._worker: DownloadWorker | None = None
        self._current_item: QListWidgetItem | None = None

        self._build_ui()
        self.setAcceptDrops(True)

        paste_shortcut = QShortcut(QKeySequence.StandardKey.Paste, self)
        paste_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        paste_shortcut.activated.connect(self._paste_links)

        if not self.config.download_dir:
            self._choose_folder()
        else:
            self._sync_library()

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        queue_tab = QWidget()
        layout = QVBoxLayout(queue_tab)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Download to:"))
        self.dir_label = QLabel(self.config.download_dir or "(no folder set)")
        dir_row.addWidget(self.dir_label, stretch=1)
        choose_btn = QPushButton("Choose Folder...")
        choose_btn.clicked.connect(self._choose_folder)
        dir_row.addWidget(choose_btn)
        open_btn = QPushButton("Open Folder")
        open_btn.clicked.connect(self._open_folder)
        dir_row.addWidget(open_btn)
        layout.addLayout(dir_row)

        hint = QLabel(
            "Paste (Ctrl+V) or drag links anywhere in this window to queue them — "
            "no need to click into a box first. Works with a whole block of links at once. "
            "Nothing downloads until you hit Start."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        tags_row = QHBoxLayout()
        tags_row.addWidget(QLabel("Tags for next paste/drop:"))
        self.tags_input = TagLineEdit()
        self.tags_input.setPlaceholderText("e.g. vlog, japan")
        tags_row.addWidget(self.tags_input, stretch=1)
        layout.addLayout(tags_row)

        add_row = QHBoxLayout()
        self.bulk_checkbox = QCheckBox("Bulk mode (download entire playlist)")
        self.bulk_checkbox.setToolTip(
            "When checked, a pasted/dropped playlist link downloads every track in it.\n"
            "Off by default so picking a single track from a playlist doesn't\n"
            "pull in the whole thing."
        )
        add_row.addWidget(self.bulk_checkbox)
        self.video_checkbox = QCheckBox("Download video (not audio)")
        self.video_checkbox.setToolTip(
            "Downloads the full video (merged to MP4) instead of extracting audio.\n"
            "For the rare case of pulling down your own uploads — this app is an\n"
            "audio library first, so leave this off for normal music downloads."
        )
        add_row.addWidget(self.video_checkbox)
        add_row.addStretch(1)
        start_btn = QPushButton("Start Downloads")
        start_btn.clicked.connect(self._process_next)
        add_row.addWidget(start_btn)
        layout.addLayout(add_row)

        cookies_row = QHBoxLayout()
        cookies_label = QLabel("Cookies (only if a download fails on an age/login check):")
        cookies_row.addWidget(cookies_label)
        self.cookies_combo = QComboBox()
        self.cookies_combo.addItems(["None", "Chrome", "Firefox", "Edge", "Brave"])
        index = self.cookies_combo.findText(self.config.cookies_browser.capitalize()) if self.config.cookies_browser else 0
        self.cookies_combo.setCurrentIndex(max(index, 0))
        self.cookies_combo.setToolTip(
            "Pulls auth cookies live from the chosen browser's cookie store, so\n"
            "yt-dlp can pass YouTube's age/login gate. Off by default — only turn\n"
            "this on if a download actually fails for that reason."
        )
        self.cookies_combo.currentTextChanged.connect(self._on_cookies_changed)
        cookies_row.addWidget(self.cookies_combo)
        cookies_row.addStretch(1)
        layout.addLayout(cookies_row)

        self.queue_list = QListWidget()
        layout.addWidget(self.queue_list, stretch=1)

        tabs.addTab(queue_tab, "Queue")

        self.library_panel = LibraryPanel()
        tabs.addTab(self.library_panel, "Library")

        # Tags created via the Library tab (Add Tag / Set Tags) should show
        # up as suggestions back on the Queue tab without waiting for a
        # download to finish.
        tabs.currentChanged.connect(lambda _: self.tags_input.set_suggestions(database.get_all_tags()))

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose download folder", self.config.download_dir or str(Path.home())
        )
        if folder:
            self.config.download_dir = folder
            self.config.save()
            self.dir_label.setText(folder)
            self._sync_library()

    def _sync_library(self) -> None:
        sync_library(Path(self.config.download_dir))
        self.library_panel.refresh()
        self.tags_input.set_suggestions(database.get_all_tags())

    def _open_folder(self) -> None:
        if self.config.download_dir:
            os.startfile(self.config.download_dir)

    def _on_cookies_changed(self, text: str) -> None:
        self.config.cookies_browser = text.lower() if text != "None" else ""
        self.config.save()

    def _paste_links(self) -> None:
        self._queue_links(extract_links(QApplication.clipboard().text()))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasText() or event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        text = "\n".join(url.toString() for url in mime.urls()) if mime.hasUrls() else mime.text()
        self._queue_links(extract_links(text))
        event.acceptProposedAction()

    def _queue_links(self, urls: list[str]) -> None:
        if not urls:
            return
        if not self.config.download_dir:
            QMessageBox.warning(self, "No folder set", "Choose a download folder first.")
            return

        bulk = self.bulk_checkbox.isChecked()
        video = self.video_checkbox.isChecked()
        tags = [t.strip() for t in self.tags_input.text().split(",") if t.strip()]
        for url in urls:
            self._add_pending_item(url, bulk, tags, video)

    def _add_pending_item(self, url: str, playlist: bool, tags: list[str], video: bool = False) -> None:
        prefix = "Pending (playlist)" if playlist else "Pending"
        prefix = f"{prefix} [video]" if video else prefix
        tag_suffix = f"  [{', '.join(tags)}]" if tags else ""
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, {"url": url, "playlist": playlist, "tags": tags, "video": video})

        row = QueueRow(f"{prefix}  —  {url}{tag_suffix}")
        row.remove_clicked.connect(lambda item=item: self._remove_item(item))

        self.queue_list.addItem(item)
        item.setSizeHint(row.sizeHint())
        self.queue_list.setItemWidget(item, row)
        self._queue.append(item)

    def _remove_item(self, item: QListWidgetItem) -> None:
        if item is self._current_item:
            return  # actively downloading — button is disabled for this case anyway
        if item in self._queue:
            self._queue.remove(item)
        self.queue_list.takeItem(self.queue_list.row(item))

    def _process_next(self) -> None:
        if self._worker is not None or not self._queue:
            return

        item = self._queue.pop(0)
        data = item.data(Qt.ItemDataRole.UserRole)
        url, playlist, tags, video = data["url"], data["playlist"], data["tags"], data["video"]
        self._current_item = item

        row = self.queue_list.itemWidget(item)
        row.set_text(f"Downloading 0%  —  {url}")
        row.remove_btn.setEnabled(False)

        worker = DownloadWorker(
            url,
            Path(self.config.download_dir),
            playlist=playlist,
            tags=tags,
            video=video,
            cookies_browser=self.config.cookies_browser,
        )
        worker.progress.connect(self._on_progress)
        worker.finished_ok.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_progress(self, percent: int, status: str) -> None:
        if not self._current_item:
            return
        row = self.queue_list.itemWidget(self._current_item)
        url = self._current_item.data(Qt.ItemDataRole.UserRole)["url"]
        suffix = f" ({status})" if status else ""
        row.set_text(f"Downloading {percent}%{suffix}  —  {url}")

    def _on_finished(self, results: list[TrackResult]) -> None:
        if self._current_item:
            row = self.queue_list.itemWidget(self._current_item)
            if len(results) == 1:
                text = f"Done  —  {results[0].path.name}"
                if results[0].similar_titles:
                    text += f"  ⚠ similar to: {', '.join(results[0].similar_titles)}"
            elif results:
                dupes = sum(1 for r in results if r.similar_titles)
                text = f"Done  —  {len(results)} tracks"
                if dupes:
                    text += f"  ⚠ {dupes} possible duplicate(s)"
            else:
                text = "Done  —  no tracks downloaded"
            row.set_text(text)
            row.remove_btn.setEnabled(True)
        self._worker = None
        self._current_item = None
        self.library_panel.refresh()
        self.tags_input.set_suggestions(database.get_all_tags())
        self._process_next()

    def _on_failed(self, message: str) -> None:
        if self._current_item:
            row = self.queue_list.itemWidget(self._current_item)
            data = self._current_item.data(Qt.ItemDataRole.UserRole)
            row.set_text(f"Failed ({message})  —  {data['url']}")
            row.remove_btn.setEnabled(True)
            row.show_retry()
            row.retry_clicked.connect(
                lambda: self._add_pending_item(data["url"], data["playlist"], data["tags"], data["video"])
            )
        self._worker = None
        self._current_item = None
        self._process_next()
