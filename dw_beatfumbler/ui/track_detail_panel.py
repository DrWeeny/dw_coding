from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.artist_lookup import ArtistSuggestion
from core.database import TrackRecord
from core.similar import SimilarTrack, clean_title
from ui.flow_layout import FlowLayout
from ui.tag_chip import TagChip
from ui.tag_input import TagLineEdit


class TrackDetailPanel(QWidget):
    """Metadata, tags, and Last.fm similarity suggestions for whichever
    single track is selected in the library list. Purely presentational —
    it emits requests and LibraryPanel does the actual DB/network work,
    then calls back in with fresh data."""

    tags_changed = Signal(int, list)  # track_id, new tag list
    metadata_changed = Signal(int, str, str)  # track_id, title, artist
    find_similar_requested = Signal(int, str, str)  # track_id, artist, cleaned title
    suggest_artist_requested = Signal(int, str, str)  # track_id, source_url, title
    queue_similar_requested = Signal(list)  # list[dict] — same shape MainWindow._queue_similar expects
    open_similar_youtube_requested = Signal(list)  # list[SimilarTrack]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._record: TrackRecord | None = None

        layout = QVBoxLayout(self)

        self.title_label = QLabel("Select a track to see its details.")
        self.title_label.setWordWrap(True)
        font = self.title_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        self.title_label.setFont(font)
        layout.addWidget(self.title_label)

        self.meta_label = QLabel("")
        self.meta_label.setWordWrap(True)
        layout.addWidget(self.meta_label)

        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Title:"))
        self.title_edit = QLineEdit()
        title_row.addWidget(self.title_edit)
        layout.addLayout(title_row)

        artist_row = QHBoxLayout()
        artist_row.addWidget(QLabel("Artist:"))
        self.artist_edit = QLineEdit()
        artist_row.addWidget(self.artist_edit)
        layout.addLayout(artist_row)

        meta_actions_row = QHBoxLayout()
        self.suggestion_label = QLabel("")
        self.suggestion_label.setWordWrap(True)
        self.suggestion_label.setVisible(False)
        meta_actions_row.addWidget(self.suggestion_label, stretch=1)
        self.use_suggestion_btn = QPushButton("Use")
        self.use_suggestion_btn.setVisible(False)
        self.use_suggestion_btn.clicked.connect(self._on_use_suggestion_clicked)
        meta_actions_row.addWidget(self.use_suggestion_btn)
        self.save_meta_btn = QPushButton("Save")
        self.save_meta_btn.clicked.connect(self._on_save_meta_clicked)
        meta_actions_row.addWidget(self.save_meta_btn)
        layout.addLayout(meta_actions_row)

        layout.addWidget(QLabel("Tags:"))
        self.active_tags_container = QWidget()
        self.active_tags_layout = FlowLayout(self.active_tags_container)
        layout.addWidget(self.active_tags_container)

        self.tag_input = TagLineEdit()
        self.tag_input.setPlaceholderText("Add tag(s), comma-separated — Enter to add")
        self.tag_input.returnPressed.connect(self._on_tag_input_submitted)
        layout.addWidget(self.tag_input)

        layout.addWidget(QLabel("Suggested tags:"))
        self.suggested_tags_container = QWidget()
        self.suggested_tags_layout = FlowLayout(self.suggested_tags_container)
        layout.addWidget(self.suggested_tags_container)

        layout.addSpacing(8)
        similar_row = QHBoxLayout()
        similar_row.addWidget(QLabel("Similar (via Last.fm):"))
        similar_row.addStretch(1)
        self.find_similar_btn = QPushButton("Find Similar")
        self.find_similar_btn.clicked.connect(self._on_find_similar_clicked)
        similar_row.addWidget(self.find_similar_btn)
        layout.addLayout(similar_row)

        self.similar_list = QListWidget()
        self.similar_list.setVisible(False)
        layout.addWidget(self.similar_list, stretch=1)

        self.no_results_label = QLabel("")
        self.no_results_label.setWordWrap(True)
        self.no_results_label.setVisible(False)
        layout.addWidget(self.no_results_label)

        self.suggest_artist_btn = QPushButton("Suggest artist (YouTube / Wikipedia)")
        self.suggest_artist_btn.setVisible(False)
        self.suggest_artist_btn.clicked.connect(self._on_suggest_artist_clicked)
        layout.addWidget(self.suggest_artist_btn)

        similar_actions_row = QHBoxLayout()
        self.queue_similar_btn = QPushButton("Queue Selected")
        self.queue_similar_btn.setVisible(False)
        self.queue_similar_btn.clicked.connect(self._on_queue_similar_clicked)
        similar_actions_row.addWidget(self.queue_similar_btn)
        self.open_similar_youtube_btn = QPushButton("Open in YouTube")
        self.open_similar_youtube_btn.setVisible(False)
        self.open_similar_youtube_btn.clicked.connect(self._on_open_similar_youtube_clicked)
        similar_actions_row.addWidget(self.open_similar_youtube_btn)
        layout.addLayout(similar_actions_row)

        layout.addStretch(1)

        self.setEnabled(False)

    def current_track_id(self) -> int | None:
        return self._record.id if self._record else None

    def set_record(self, record: TrackRecord | None, all_tags: list[str]) -> None:
        self._record = record
        self._suggested_artist: str | None = None
        self.tag_input.clear()
        self.clear_similar_results()
        self.set_finding_similar(False)
        self.suggestion_label.setVisible(False)
        self.use_suggestion_btn.setVisible(False)
        self.suggest_artist_btn.setVisible(False)

        if record is None:
            self.setEnabled(False)
            self.title_label.setText("Select a track to see its details.")
            self.meta_label.setText("")
            self.title_edit.clear()
            self.artist_edit.clear()
            self._clear_flow(self.active_tags_layout)
            self._clear_flow(self.suggested_tags_layout)
            return

        self.setEnabled(True)
        self.title_label.setText(record.title)
        self.title_edit.setText(record.title)
        self.artist_edit.setText(record.artist)

        if record.duration:
            duration = f"{int(record.duration // 60)}:{int(record.duration % 60):02d}"
        else:
            duration = "—"
        self.meta_label.setText(f"Duration: {duration}\nDownloaded: {record.downloaded_at[:10]}")

        self.tag_input.set_suggestions(all_tags)

        self._clear_flow(self.active_tags_layout)
        for tag in record.tags:
            chip = TagChip(tag, removable=True)
            chip.removed.connect(self._on_tag_removed)
            self.active_tags_layout.addWidget(chip)

        self._clear_flow(self.suggested_tags_layout)
        for tag in sorted(set(all_tags) - set(record.tags)):
            chip = TagChip(tag, removable=False)
            chip.activated.connect(self._on_tag_activated)
            self.suggested_tags_layout.addWidget(chip)

    def set_finding_similar(self, loading: bool) -> None:
        self.find_similar_btn.setEnabled(not loading)
        self.find_similar_btn.setText("Finding..." if loading else "Find Similar")

    def set_similar_results(self, tracks: list[SimilarTrack]) -> None:
        self.no_results_label.setVisible(False)
        self.suggest_artist_btn.setVisible(False)
        self.similar_list.clear()
        for track in tracks:
            match_str = f"  ({track.match * 100:.0f}% match)" if track.match else ""
            item = QListWidgetItem(f"{track.artist} — {track.title}{match_str}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, track)
            self.similar_list.addItem(item)
        self.similar_list.setVisible(True)
        self.queue_similar_btn.setVisible(True)
        self.open_similar_youtube_btn.setVisible(True)

    def show_no_results(self, artist: str, title: str) -> None:
        self.clear_similar_results()
        query = f"{artist} — {title}" if artist else title
        self.no_results_label.setText(f"No Last.fm matches for: {query}")
        self.no_results_label.setVisible(True)
        self.suggest_artist_btn.setVisible(True)

    def clear_similar_results(self) -> None:
        self.similar_list.clear()
        self.similar_list.setVisible(False)
        self.queue_similar_btn.setVisible(False)
        self.open_similar_youtube_btn.setVisible(False)
        self.no_results_label.setVisible(False)

    def set_artist_suggestion(self, suggestion: ArtistSuggestion | None) -> None:
        self.suggest_artist_btn.setEnabled(True)
        self.suggest_artist_btn.setText("Suggest artist (YouTube / Wikipedia)")
        if suggestion is None:
            self._suggested_artist = None
            self.suggestion_label.setText("No artist suggestion found.")
            self.suggestion_label.setVisible(True)
            self.use_suggestion_btn.setVisible(False)
            return
        self._suggested_artist = suggestion.artist
        self.suggestion_label.setText(f"Suggestion: {suggestion.artist}  (via {suggestion.source})")
        self.suggestion_label.setVisible(True)
        self.use_suggestion_btn.setVisible(True)

    @staticmethod
    def _clear_flow(layout: FlowLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _on_tag_input_submitted(self) -> None:
        if not self._record:
            return
        new_tags = [t.strip() for t in self.tag_input.text().split(",") if t.strip()]
        if not new_tags:
            return
        merged = sorted(set(self._record.tags) | {t.lower() for t in new_tags})
        self.tags_changed.emit(self._record.id, merged)

    def _on_tag_removed(self, tag: str) -> None:
        if not self._record:
            return
        remaining = [t for t in self._record.tags if t != tag]
        self.tags_changed.emit(self._record.id, remaining)

    def _on_tag_activated(self, tag: str) -> None:
        if not self._record:
            return
        merged = sorted(set(self._record.tags) | {tag})
        self.tags_changed.emit(self._record.id, merged)

    def _on_find_similar_clicked(self) -> None:
        if not self._record:
            return
        self.clear_similar_results()
        artist = self.artist_edit.text().strip()
        title = clean_title(self.title_edit.text().strip())
        self.find_similar_requested.emit(self._record.id, artist, title)

    def _on_save_meta_clicked(self) -> None:
        if not self._record:
            return
        title = self.title_edit.text().strip()
        artist = self.artist_edit.text().strip()
        if not title:
            return
        self.metadata_changed.emit(self._record.id, title, artist)

    def _on_suggest_artist_clicked(self) -> None:
        if not self._record:
            return
        self.suggest_artist_btn.setEnabled(False)
        self.suggest_artist_btn.setText("Looking...")
        self.suggestion_label.setVisible(False)
        self.use_suggestion_btn.setVisible(False)
        self.suggest_artist_requested.emit(self._record.id, self._record.source_url, self.title_edit.text())

    def _on_use_suggestion_clicked(self) -> None:
        if self._suggested_artist:
            self.artist_edit.setText(self._suggested_artist)

    def _checked_similar_tracks(self) -> list[SimilarTrack]:
        selected = []
        for i in range(self.similar_list.count()):
            item = self.similar_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))
        return selected

    def _on_queue_similar_clicked(self) -> None:
        if not self._record:
            return
        selected = self._checked_similar_tracks()
        if not selected:
            return
        self.queue_similar_requested.emit(
            [
                {
                    "url": f"ytsearch1:{t.artist} {t.title}",
                    "label": f"{t.artist} — {t.title}",
                    "tags": self._record.tags,
                }
                for t in selected
            ]
        )

    def _on_open_similar_youtube_clicked(self) -> None:
        selected = self._checked_similar_tracks()
        if not selected:
            return
        self.open_similar_youtube_requested.emit(selected)
