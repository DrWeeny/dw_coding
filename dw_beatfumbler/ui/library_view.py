from __future__ import annotations

import os
import subprocess
import urllib.parse
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig
from core import database
from core.library_scan import unique_destination
from core.slug import slug_filename
from core.waveform import waveform_path_for
from ui.add_tag_dialog import AddTagDialog
from ui.artist_lookup_worker import ArtistLookupWorker
from ui.convert_worker import ConvertWorker
from ui.mini_player import MiniPlayer
from ui.similar_worker import SimilarWorker
from ui.tag_list_widget import TagListWidget
from ui.track_detail_panel import TrackDetailPanel
from ui.track_list_widget import TrackListWidget


class LibraryPanel(QWidget):
    """Browse downloaded tracks by tag instead of by folder."""

    queue_requested = Signal(list)  # list[dict] — see MainWindow._queue_similar

    def __init__(self, config: AppConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config
        layout = QHBoxLayout(self)

        track_col = QVBoxLayout()
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter by title or artist...")
        self.search_box.textChanged.connect(self._refresh_tracks)
        search_row.addWidget(self.search_box)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Newest first", "date_desc")
        self.sort_combo.addItem("Oldest first", "date_asc")
        self.sort_combo.currentIndexChanged.connect(self._refresh_tracks)
        search_row.addWidget(self.sort_combo)

        track_col.addLayout(search_row)

        self.track_list = TrackListWidget()
        self.track_list.itemDoubleClicked.connect(self._play_track)
        self.track_list.itemSelectionChanged.connect(self._on_track_selection_changed)
        self.track_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.track_list.customContextMenuRequested.connect(self._show_context_menu)
        track_col.addWidget(self.track_list, stretch=1)

        self.player = MiniPlayer()
        track_col.addWidget(self.player)

        layout.addLayout(track_col, stretch=2)

        self.detail_panel = TrackDetailPanel()
        self.detail_panel.tags_changed.connect(self._on_tags_changed)
        self.detail_panel.metadata_changed.connect(self._on_metadata_changed)
        self.detail_panel.find_similar_requested.connect(self._on_find_similar_requested)
        self.detail_panel.suggest_artist_requested.connect(self._on_suggest_artist_requested)
        self.detail_panel.queue_similar_requested.connect(self.queue_requested)
        self.detail_panel.open_similar_youtube_requested.connect(self._on_open_similar_youtube)
        layout.addWidget(self.detail_panel, stretch=2)

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

        self._convert_workers: list[ConvertWorker] = []
        self._similar_workers: list[SimilarWorker] = []
        self._lookup_workers: list[ArtistLookupWorker] = []

        self.refresh()

    def refresh(self) -> None:
        selected_tags = {item.text() for item in self.tag_list.selectedItems()}
        current_id = self._current_single_track_id()

        self.tag_list.blockSignals(True)
        self.tag_list.clear()
        for tag in database.get_all_tags():
            item = QListWidgetItem(tag)
            self.tag_list.addItem(item)
            if tag in selected_tags:
                item.setSelected(True)
        self.tag_list.blockSignals(False)

        self._refresh_tracks()

        if current_id is not None:
            for i in range(self.track_list.count()):
                item = self.track_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole).id == current_id:
                    item.setSelected(True)
                    self.track_list.setCurrentItem(item)
                    break

    def _current_single_track_id(self) -> int | None:
        items = self.track_list.selectedItems()
        if len(items) == 1:
            return items[0].data(Qt.ItemDataRole.UserRole).id
        return None

    def _refresh_tracks(self) -> None:
        selected_tags = [item.text() for item in self.tag_list.selectedItems()]
        records = database.get_tracks(
            tag_filter=selected_tags or None,
            search=self.search_box.text(),
            order=self.sort_combo.currentData(),
        )

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

    def _on_track_selection_changed(self) -> None:
        items = self.track_list.selectedItems()
        if len(items) == 1:
            self.detail_panel.set_record(items[0].data(Qt.ItemDataRole.UserRole), database.get_all_tags())
        else:
            self.detail_panel.set_record(None, [])

    def _on_tags_changed(self, track_id: int, tags: list[str]) -> None:
        database.set_track_tags(track_id, tags)
        self.refresh()

    def _on_metadata_changed(self, track_id: int, title: str, artist: str) -> None:
        database.update_track_metadata(track_id, title, artist)
        self.refresh()

    def _on_find_similar_requested(self, track_id: int, artist: str, title: str) -> None:
        if not self.config.lastfm_api_key:
            QMessageBox.information(
                self,
                "Last.fm API key needed",
                "Set a free Last.fm API key in the Queue tab first "
                "(get one at last.fm/api/account/create).",
            )
            return

        self.detail_panel.set_finding_similar(True)
        worker = SimilarWorker(artist, title, self.config.lastfm_api_key)
        worker.finished_ok.connect(
            lambda tracks, tid=track_id, a=artist, t=title: self._on_similar_found(tid, tracks, a, t)
        )
        worker.failed.connect(lambda message, tid=track_id: self._on_similar_failed(tid, message))
        worker.finished.connect(lambda w=worker: self._similar_workers.remove(w))
        worker.finished.connect(worker.deleteLater)
        self._similar_workers.append(worker)
        worker.start()

    def _on_similar_found(self, track_id: int, tracks: list, artist: str, title: str) -> None:
        if self.detail_panel.current_track_id() != track_id:
            return  # selection moved on to another track while this was in flight
        self.detail_panel.set_finding_similar(False)
        if not tracks:
            self.detail_panel.show_no_results(artist, title)
            return
        self.detail_panel.set_similar_results(tracks)

    def _on_similar_failed(self, track_id: int, message: str) -> None:
        if self.detail_panel.current_track_id() != track_id:
            return
        self.detail_panel.set_finding_similar(False)
        QMessageBox.warning(self, "Similar Tracks", message)

    def _on_suggest_artist_requested(self, track_id: int, source_url: str, title: str) -> None:
        worker = ArtistLookupWorker(source_url, title)
        worker.finished_ok.connect(lambda suggestion, tid=track_id: self._on_artist_suggested(tid, suggestion))
        worker.failed.connect(lambda message, tid=track_id: self._on_artist_suggested(tid, None))
        worker.finished.connect(lambda w=worker: self._lookup_workers.remove(w))
        worker.finished.connect(worker.deleteLater)
        self._lookup_workers.append(worker)
        worker.start()

    def _on_artist_suggested(self, track_id: int, suggestion) -> None:
        if self.detail_panel.current_track_id() != track_id:
            return
        self.detail_panel.set_artist_suggestion(suggestion)

    def _on_open_similar_youtube(self, tracks: list) -> None:
        for track in tracks:
            query = urllib.parse.quote(f"{track.artist} {track.title}")
            webbrowser.open_new_tab(f"https://www.youtube.com/results?search_query={query}")

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
