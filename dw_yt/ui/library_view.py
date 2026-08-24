from __future__ import annotations

import os
import subprocess
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import database
from core.library_scan import unique_destination
from core.slug import slug_filename
from core.waveform import waveform_path_for
from ui.add_tag_dialog import AddTagDialog
from ui.convert_worker import ConvertWorker
from ui.mini_player import MiniPlayer
from ui.tag_list_widget import TagListWidget
from ui.track_list_widget import TrackListWidget


class LibraryPanel(QWidget):
    """Browse downloaded tracks by tag instead of by folder."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)

        tag_col = QVBoxLayout()
        tag_col.addWidget(QLabel("Tags  (drag tracks here to tag them)"))
        self.tag_list = TagListWidget()
        self.tag_list.itemSelectionChanged.connect(self._refresh_tracks)
        self.tag_list.tracks_dropped.connect(self._on_tracks_dropped)
        tag_col.addWidget(self.tag_list, stretch=1)
        clear_btn = QPushButton("Clear filter")
        clear_btn.clicked.connect(self.tag_list.clearSelection)
        tag_col.addWidget(clear_btn)
        layout.addLayout(tag_col, stretch=1)

        track_col = QVBoxLayout()
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter by title or artist...")
        self.search_box.textChanged.connect(self._refresh_tracks)
        search_row.addWidget(self.search_box)
        track_col.addLayout(search_row)

        self.track_list = TrackListWidget()
        self.track_list.itemDoubleClicked.connect(self._play_track)
        self.track_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.track_list.customContextMenuRequested.connect(self._show_context_menu)
        track_col.addWidget(self.track_list, stretch=1)

        self.player = MiniPlayer()
        track_col.addWidget(self.player)

        actions_row = QHBoxLayout()
        add_tag_btn = QPushButton("Add Tag...")
        add_tag_btn.clicked.connect(self._add_tag_to_selection)
        actions_row.addWidget(add_tag_btn)
        set_tags_btn = QPushButton("Set Tags...")
        set_tags_btn.setToolTip("Replace this track's entire tag list (single track only).")
        set_tags_btn.clicked.connect(self._set_tags_on_current)
        actions_row.addWidget(set_tags_btn)
        actions_row.addStretch(1)
        delete_btn = QPushButton("Delete...")
        delete_btn.clicked.connect(self._delete_selected)
        actions_row.addWidget(delete_btn)
        track_col.addLayout(actions_row)

        layout.addLayout(track_col, stretch=2)

        self._convert_workers: list[ConvertWorker] = []

        self.refresh()

    def refresh(self) -> None:
        selected_tags = {item.text() for item in self.tag_list.selectedItems()}

        self.tag_list.blockSignals(True)
        self.tag_list.clear()
        for tag in database.get_all_tags():
            item = QListWidgetItem(tag)
            self.tag_list.addItem(item)
            if tag in selected_tags:
                item.setSelected(True)
        self.tag_list.blockSignals(False)

        self._refresh_tracks()

    def _refresh_tracks(self) -> None:
        selected_tags = [item.text() for item in self.tag_list.selectedItems()]
        records = database.get_tracks(tag_filter=selected_tags or None, search=self.search_box.text())

        self.track_list.clear()
        for record in records:
            tag_str = f"  [{', '.join(record.tags)}]" if record.tags else ""
            artist = f" — {record.artist}" if record.artist else ""
            item = QListWidgetItem(f"{record.title}{artist}{tag_str}")
            item.setData(Qt.ItemDataRole.UserRole, record)
            self.track_list.addItem(item)

    def _play_track(self, item: QListWidgetItem) -> None:
        record = item.data(Qt.ItemDataRole.UserRole)
        if record and os.path.exists(record.filepath):
            self.player.play(record.filepath, record.title)

    def _open_web_link(self) -> None:
        item = self.track_list.currentItem()
        if not item:
            return
        record = item.data(Qt.ItemDataRole.UserRole)
        if not record or not record.source_url:
            QMessageBox.information(self, "Open Web Link", "No source link recorded for this track.")
            return
        webbrowser.open(record.source_url)

    def _reveal_in_explorer(self) -> None:
        item = self.track_list.currentItem()
        if not item:
            return
        record = item.data(Qt.ItemDataRole.UserRole)
        if record and os.path.exists(record.filepath):
            subprocess.run(f'explorer /select,"{record.filepath}"')

    def _show_context_menu(self, pos) -> None:
        if not self.track_list.selectedItems():
            return
        menu = QMenu(self)
        add_action = menu.addAction("Add Tag...")
        reveal_action = menu.addAction("Find in Explorer")
        web_action = menu.addAction("Open Web Link")
        convert_action = menu.addAction("Convert to MP3")
        slugify_action = menu.addAction("Slugify Filename")
        menu.addSeparator()
        delete_action = menu.addAction("Delete...")
        chosen = menu.exec(self.track_list.viewport().mapToGlobal(pos))
        if chosen is add_action:
            self._add_tag_to_selection()
        elif chosen is web_action:
            self._open_web_link()
        elif chosen is reveal_action:
            self._reveal_in_explorer()
        elif chosen is convert_action:
            self._convert_selected_to_mp3()
        elif chosen is slugify_action:
            self._slugify_selected_filenames()
        elif chosen is delete_action:
            self._delete_selected()

    def _add_tag_to_selection(self) -> None:
        items = self.track_list.selectedItems()
        if not items:
            return
        dialog = AddTagDialog(database.get_all_tags(), len(items), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        tags = dialog.tags()
        track_ids = [item.data(Qt.ItemDataRole.UserRole).id for item in items]
        for tag in tags:
            database.add_tag_to_tracks(tag, track_ids)
        self.refresh()

    def _convert_selected_to_mp3(self) -> None:
        items = self.track_list.selectedItems()
        targets = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in items
            if not item.data(Qt.ItemDataRole.UserRole).filepath.lower().endswith(".mp3")
        ]
        if not targets:
            QMessageBox.information(self, "Convert to MP3", "Selected track(s) are already MP3.")
            return

        for record in targets:
            worker = ConvertWorker(record.id, Path(record.filepath))
            worker.finished_ok.connect(self._on_convert_finished)
            worker.failed.connect(self._on_convert_failed)
            worker.finished.connect(lambda w=worker: self._convert_workers.remove(w))
            worker.finished.connect(worker.deleteLater)
            self._convert_workers.append(worker)
            worker.start()

    def _slugify_selected_filenames(self) -> None:
        items = self.track_list.selectedItems()
        records = [item.data(Qt.ItemDataRole.UserRole) for item in items]
        targets = [r for r in records if Path(r.filepath).name != slug_filename(r.title, r.video_id, Path(r.filepath).suffix)]
        if not targets:
            QMessageBox.information(self, "Slugify Filename", "Selected track(s) already have a slugified filename.")
            return

        renamed = 0
        for record in targets:
            path = Path(record.filepath)
            new_path = unique_destination(path.parent, slug_filename(record.title, record.video_id, path.suffix))

            if self.player.current_path() == str(path):
                self.player.stop()  # release the file handle so Windows lets us rename it

            try:
                path.rename(new_path)
            except OSError as exc:
                QMessageBox.warning(self, "Rename failed", f"Could not rename \"{record.title}\": {exc}")
                continue

            old_waveform = waveform_path_for(path)
            if old_waveform.exists():
                old_waveform.rename(waveform_path_for(new_path))

            database.update_track_filepath(record.id, str(new_path))
            renamed += 1

        if renamed:
            self.refresh()

    def _on_convert_finished(self, track_id: int, new_path: Path) -> None:
        self.refresh()

    def _on_convert_failed(self, track_id: int, message: str) -> None:
        QMessageBox.warning(self, "Conversion failed", message)

    def _delete_selected(self) -> None:
        items = self.track_list.selectedItems()
        if not items:
            return
        records = [item.data(Qt.ItemDataRole.UserRole) for item in items]

        if len(records) == 1:
            prompt = f"Delete \"{records[0].title}\"? This permanently removes the file from disk."
        else:
            titles = "\n".join(f"  • {r.title}" for r in records)
            prompt = f"Delete these {len(records)} tracks? This permanently removes the files from disk.\n\n{titles}"

        confirmed = QMessageBox.question(
            self, "Delete", prompt, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return

        deleted_paths = {record.filepath for record in records}
        if self.player.current_path() in deleted_paths:
            self.player.stop()  # release the file handle so Windows lets us delete it

        for record in records:
            try:
                os.remove(record.filepath)
            except OSError:
                pass  # already missing on disk — still drop it from the library
            waveform_path_for(Path(record.filepath)).unlink(missing_ok=True)
            database.delete_track(record.id)

        self.refresh()

    def _on_tracks_dropped(self, tag: str, track_ids: list[int]) -> None:
        database.add_tag_to_tracks(tag, track_ids)
        self.refresh()

    def _set_tags_on_current(self) -> None:
        item = self.track_list.currentItem()
        if not item:
            return
        record = item.data(Qt.ItemDataRole.UserRole)

        text, ok = QInputDialog.getText(
            self, "Set Tags", f"Tags for \"{record.title}\" (comma-separated):", text=", ".join(record.tags)
        )
        if not ok:
            return

        tags = [t.strip() for t in text.split(",") if t.strip()]
        database.set_track_tags(record.id, tags)
        self.refresh()
