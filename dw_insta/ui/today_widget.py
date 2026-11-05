from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QThreadPool, QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig
from core.archive import archive_group
from core.comment import (
    HASHTAG_CAP,
    accept_caption_suggestion,
    accept_hashtags_suggestion,
    compose_comment,
    effective_tags,
)
from core.paths import resolve_original_photo_path, resolve_photo_path
from core.scheduler import next_group, pending_groups, planned_dates, posted_on
from core.series import Group, SeriesState

from .carousel_order import CarouselOrderWidget
from .discord_task import DiscordPostTask
from .drag_thumbnail import DraggableThumbnail
from .flow_layout import FlowLayout
from .hashtag_chip import HashtagChip
from .series_store import SeriesStore

INSTAGRAM_CAPTION_LIMIT = 2200
CAPTION_SAVE_DEBOUNCE_MS = 400


def _make_tray_icon() -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#ff5fa2"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 28, 28)
    painter.end()
    return QIcon(pixmap)


def _suggestion_button(parent: Optional[QWidget] = None) -> QToolButton:
    btn = QToolButton(parent)
    btn.setText("●")
    btn.setStyleSheet("QToolButton { color: #ff5fa2; border: none; font-size: 13px; }")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setVisible(False)
    return btn


class TodayPanel(QWidget):
    """Panel showing the next post in the queue: a draggable image (with
    prev/next for carousel posts), an editable caption with a live Instagram
    char counter, hashtags as removable chips, and quick actions. Reads from
    the shared SeriesStore and changes things only through it. Plain
    embeddable QWidget — no window flags — so it can sit inline in
    MainWindow's layout and, separately, inside TodayPopupWindow for the
    system-tray popup."""

    def __init__(self, config: AppConfig, store: SeriesStore, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.config = config
        self.store = store
        self.state: Optional[SeriesState] = None
        self.group: Optional[Group] = None
        self._caption_group_id: Optional[str] = None
        self._discord_task: Optional[DiscordPostTask] = None

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_caption)

        root = QVBoxLayout(self)

        # --- top bar ---
        top_bar = QHBoxLayout()
        title = QLabel("📅 Next Post")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        top_bar.addWidget(title)
        top_bar.addStretch(1)
        open_btn = QPushButton("Open Instagram")
        open_btn.clicked.connect(self._open_instagram)
        top_bar.addWidget(open_btn)
        root.addLayout(top_bar)

        # --- image + description row ---
        content_row = QHBoxLayout()

        self.thumb = DraggableThumbnail(size=260, parent=self)
        content_row.addWidget(self.thumb)

        self.order_widget = CarouselOrderWidget(self)
        self.order_widget.photo_selected.connect(self._on_photo_selected)
        self.order_widget.reordered.connect(self._on_photos_reordered)
        content_row.addWidget(self.order_widget)

        desc_col = QVBoxLayout()

        desc_header = QHBoxLayout()
        desc_header.addWidget(QLabel("Description"))
        self.caption_suggestion_btn = _suggestion_button(self)
        self.caption_suggestion_btn.clicked.connect(self._accept_caption_suggestion)
        desc_header.addWidget(self.caption_suggestion_btn)
        desc_header.addStretch(1)
        self.char_count_label = QLabel(f"0 / {INSTAGRAM_CAPTION_LIMIT}")
        self.char_count_label.setStyleSheet("color: #888;")
        desc_header.addWidget(self.char_count_label)
        desc_col.addLayout(desc_header)

        self.caption_edit = QPlainTextEdit()
        self.caption_edit.textChanged.connect(self._on_caption_edited)
        desc_col.addWidget(self.caption_edit, 1)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("📅 Planned:"))
        self.date_label = QLabel("-")
        date_row.addWidget(self.date_label)
        date_row.addStretch(1)
        desc_col.addLayout(date_row)

        content_row.addLayout(desc_col, 1)
        root.addLayout(content_row, 1)

        # --- hashtags ---
        tags_header = QHBoxLayout()
        tags_header.addWidget(QLabel("# Hashtags"))
        self.tag_count_label = QLabel(f"0 / {HASHTAG_CAP}")
        self.tag_count_label.setStyleSheet("color: #888;")
        tags_header.addWidget(self.tag_count_label)
        self.hashtags_suggestion_btn = _suggestion_button(self)
        self.hashtags_suggestion_btn.clicked.connect(self._accept_hashtags_suggestion)
        tags_header.addWidget(self.hashtags_suggestion_btn)
        tags_header.addStretch(1)
        add_tag_btn = QPushButton("+ Add Hashtag")
        add_tag_btn.clicked.connect(self._add_hashtag)
        tags_header.addWidget(add_tag_btn)
        root.addLayout(tags_header)

        self.tags_container = QWidget()
        self.tags_layout = FlowLayout(self.tags_container, spacing=6)
        root.addWidget(self.tags_container)

        # --- bottom actions ---
        buttons_row = QHBoxLayout()
        copy_btn = QPushButton("Copy comment")
        copy_btn.clicked.connect(self._copy_comment)
        buttons_row.addWidget(copy_btn)
        self.discord_btn = QPushButton("Post to Discord")
        self.discord_btn.clicked.connect(self._post_to_discord)
        buttons_row.addWidget(self.discord_btn)
        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setToolTip(
            "Not worth posting: take it out of the queue. The files stay where they are, "
            "and it can be restored from the table's right-click menu."
        )
        self.skip_btn.clicked.connect(self._skip)
        buttons_row.addWidget(self.skip_btn)
        self.posted_btn = QPushButton("Mark as posted")
        self.posted_btn.clicked.connect(self._mark_posted)
        buttons_row.addWidget(self.posted_btn)
        root.addLayout(buttons_row)

        self.status_label = QLabel("")
        root.addWidget(self.status_label)

        store.changed.connect(self.refresh)
        store.flush_requested.connect(self.flush)

    # --- loading ---

    def refresh(self) -> None:
        typing_on_group = self._save_timer.isActive()
        group = next_group(self.store.state) if self.store.state else None
        if typing_on_group and (group is None or group.id != self._caption_group_id):
            # The queue moved on under an edit still waiting to be saved.
            self.flush()
            typing_on_group = False
            group = next_group(self.store.state) if self.store.state else None

        self.state = self.store.state
        if self.state is None:
            self._set_no_group("No active series")
            return
        if group is None:
            self._set_no_group(f"{self.state.series_name}: nothing left in the queue")
            return

        self.group = group

        if self.order_widget.current_order() != group.photos:
            self.order_widget.set_photos(group.photos)
        filename = self._current_photo_filename() or (group.photos[0] if group.photos else None)
        self._show_photo_by_filename(filename)
        self.thumb.set_drag_paths(self._resolve_ordered_paths())

        self._update_date_and_status()

        if typing_on_group:
            # This group object may be fresh off the disk: it hasn't seen the
            # text that's still waiting to be saved.
            group.caption = self.caption_edit.toPlainText() or None
        elif self.caption_edit.toPlainText() != (group.caption or ""):
            self.caption_edit.blockSignals(True)
            self.caption_edit.setPlainText(group.caption or "")
            self.caption_edit.blockSignals(False)
        self._update_char_count()

        self._rebuild_hashtag_chips()
        self._update_suggestion_buttons()

        self.posted_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)

    def _update_date_and_status(self) -> None:
        today = date.today()
        planned = planned_dates(self.state, today).get(self.group.id)
        self.date_label.setText("Today" if planned == today else planned.strftime("%b %d, %Y"))
        posted_today = posted_on(self.state, today)
        left = len(pending_groups(self.state))
        message = f"{left} left in the queue"
        if posted_today:
            message += f", {posted_today} marked posted today"
        self.status_label.setText(message)

    def _set_no_group(self, message: str) -> None:
        self.group = None
        self.thumb.clear_photo()
        self.order_widget.clear()
        self.caption_edit.blockSignals(True)
        self.caption_edit.setPlainText("")
        self.caption_edit.blockSignals(False)
        self.char_count_label.setText(f"0 / {INSTAGRAM_CAPTION_LIMIT}")
        self.char_count_label.setStyleSheet("color: #888;")
        self.tag_count_label.setText(f"0 / {HASHTAG_CAP}")
        self.caption_suggestion_btn.setVisible(False)
        self.hashtags_suggestion_btn.setVisible(False)
        self.date_label.setText("-")
        self._clear_hashtag_chips()
        self.posted_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.status_label.setText(message)

    # --- image carousel ---

    def _show_photo_by_filename(self, filename: Optional[str]) -> None:
        path = resolve_photo_path(self.state, filename) if (self.state and filename) else None
        if path is not None:
            self.thumb.set_photo(path)
        else:
            self.thumb.clear_photo()

    def _resolve_ordered_paths(self) -> list[Path]:
        if not self.state or not self.group:
            return []
        paths = [resolve_photo_path(self.state, filename) for filename in self.group.photos]
        return [p for p in paths if p is not None]

    def _current_photo_filename(self) -> Optional[str]:
        item = self.order_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_photo_selected(self, row: int) -> None:
        item = self.order_widget.item(row)
        filename = item.data(Qt.ItemDataRole.UserRole) if item else None
        self._show_photo_by_filename(filename)
        self._update_suggestion_buttons()

    def _on_photos_reordered(self, new_order: list[str]) -> None:
        if not self.group:
            return
        self._update_group(self.group.id, "photos", new_order)

    def _update_group(self, group_id: str, attribute: str, value: object) -> None:
        def apply(state: SeriesState) -> None:
            group = state.find_group(group_id)
            if group is not None:
                setattr(group, attribute, value)

        self.store.mutate(apply)

    # --- caption ---

    def _on_caption_edited(self) -> None:
        if self.group is None:
            return
        # Live in memory straight away so the counter and Copy comment see the
        # text as typed. Only the write to disk waits for a pause.
        self.group.caption = self.caption_edit.toPlainText() or None
        self._caption_group_id = self.group.id
        self._update_char_count()
        self._save_timer.start(CAPTION_SAVE_DEBOUNCE_MS)

    def _update_char_count(self) -> None:
        if self.state and self.group:
            length = len(compose_comment(self.state, self.group))
        else:
            length = len(self.caption_edit.toPlainText())
        over = length > INSTAGRAM_CAPTION_LIMIT
        self.char_count_label.setText(f"{length} / {INSTAGRAM_CAPTION_LIMIT}")
        self.char_count_label.setStyleSheet("color: #e05555;" if over else "color: #888;")

    def _save_caption(self) -> None:
        if self._caption_group_id is None:
            return
        self._update_group(self._caption_group_id, "caption", self.caption_edit.toPlainText() or None)

    def flush(self) -> None:
        """Write a caption still waiting on the debounce."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_caption()

    def _update_suggestion_buttons(self) -> None:
        """Pink-dot suggestion buttons track whichever photo is currently
        selected in the carousel order widget, not the group as a whole —
        each photo can carry its own pending AI-drafted caption/hashtags."""
        filename = self._current_photo_filename()
        caption_text = self.group.suggested_captions.get(filename) if (self.group and filename) else None
        hashtags_text = self.group.suggested_hashtags.get(filename) if (self.group and filename) else None
        self.caption_suggestion_btn.setVisible(bool(caption_text))
        self.caption_suggestion_btn.setToolTip(caption_text or "")
        self.hashtags_suggestion_btn.setVisible(bool(hashtags_text))
        self.hashtags_suggestion_btn.setToolTip(hashtags_text or "")

    def _accept_suggestion(self, accept) -> None:
        filename = self._current_photo_filename()
        if not self.group or not filename:
            return
        self.flush()
        group_id = self.group.id

        def apply(state: SeriesState) -> None:
            group = state.find_group(group_id)
            if group is not None:
                accept(group, filename=filename)

        self.store.mutate(apply)

    def _accept_caption_suggestion(self) -> None:
        self._accept_suggestion(accept_caption_suggestion)

    # --- hashtags ---

    def _effective_tags(self) -> list[str]:
        if not self.state or not self.group:
            return []
        return effective_tags(self.state, self.group)

    def _clear_hashtag_chips(self) -> None:
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()  # deleteLater waits for the event loop; don't leave it drawn until then
                widget.deleteLater()

    def _rebuild_hashtag_chips(self) -> None:
        self._clear_hashtag_chips()
        tags = self._effective_tags()
        for position, tag in enumerate(tags):
            chip = HashtagChip(tag, over_cap=position >= HASHTAG_CAP, parent=self.tags_container)
            chip.removed.connect(self._remove_hashtag)
            chip.promoted.connect(self._promote_hashtag)
            self.tags_layout.addWidget(chip)

        over = len(tags) - HASHTAG_CAP
        text = f"{min(len(tags), HASHTAG_CAP)} / {HASHTAG_CAP}"
        if over > 0:
            text += f" (+{over} not copied)"
        self.tag_count_label.setText(text)
        self.tag_count_label.setStyleSheet("color: #e0a055;" if over > 0 else "color: #888;")

    def _set_group_hashtags(self, tags: list[str]) -> None:
        """Always stores a string: "" means this post has no hashtags, whereas
        None would bring the series' hashtags straight back."""
        if self.group:
            self._update_group(self.group.id, "hashtags", " ".join(tags))

    def _add_hashtag(self) -> None:
        if not self.state or not self.group:
            return
        text, ok = QInputDialog.getText(self, "Add hashtag", "Hashtag:")
        text = text.strip()
        if not ok or not text:
            return
        if not text.startswith("#"):
            text = f"#{text}"
        tags = self._effective_tags()
        if text not in tags:
            tags.append(text)
        self._set_group_hashtags(tags)

    def _remove_hashtag(self, tag: str) -> None:
        self._set_group_hashtags([t for t in self._effective_tags() if t != tag])

    def _promote_hashtag(self, tag: str) -> None:
        """Bring an over-cap tag to the front, which pushes the last one out."""
        self._set_group_hashtags([tag] + [t for t in self._effective_tags() if t != tag])

    def _accept_hashtags_suggestion(self) -> None:
        self._accept_suggestion(accept_hashtags_suggestion)

    # --- actions ---

    def _copy_comment(self) -> None:
        if not self.state or not self.group:
            return
        QGuiApplication.clipboard().setText(compose_comment(self.state, self.group))
        total = len(self._effective_tags())
        detail = f" with {HASHTAG_CAP} of its {total} hashtags" if total > HASHTAG_CAP else ""
        self.status_label.setText(f"Comment copied{detail}")

    def _open_instagram(self) -> None:
        QDesktopServices.openUrl(QUrl(self.config.instagram_profile_url))

    def _post_to_discord(self) -> None:
        if not self.state or not self.group:
            return
        if not self.config.discord_webhook_url:
            QMessageBox.warning(
                self,
                "Discord",
                "No Discord webhook configured — add one with Settings > Set Discord Webhook "
                "(channel Settings > Integrations > Webhooks > New Webhook > Copy Webhook URL).",
            )
            return
        filename = self._current_photo_filename() or (self.group.photos[0] if self.group.photos else None)
        path = resolve_original_photo_path(self.state, filename) if filename else None
        if path is None:
            QMessageBox.warning(self, "Discord", "Could not find the original photo file.")
            return
        self.discord_btn.setEnabled(False)
        self.status_label.setText(f"Posting {filename} to Discord...")
        self._discord_task = DiscordPostTask(self.config.discord_webhook_url, path)
        self._discord_task.signals.finished.connect(self._on_discord_finished)
        QThreadPool.globalInstance().start(self._discord_task)

    def _on_discord_finished(self, filename: str, error: str) -> None:
        self._discord_task = None
        self.discord_btn.setEnabled(True)
        if error:
            self.status_label.setText("")
            QMessageBox.warning(self, "Discord", f"Failed to post to Discord:\n{error}")
        else:
            self.status_label.setText(f"Posted {filename} to Discord")

    def _skip(self) -> None:
        if self.group:
            self.flush()
            self._update_group(self.group.id, "skipped", True)

    def _mark_posted(self) -> None:
        if not self.group or self.group.is_posted:
            return
        reply = QMessageBox.question(
            self,
            "Mark as posted",
            "Move this post's photo(s) into archived/? Only do this after you've actually posted.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.flush()
        group_id = self.group.id

        def apply(state: SeriesState) -> None:
            group = state.find_group(group_id)
            if group is not None:
                archive_group(state, group)

        try:
            self.store.mutate(apply)
        except OSError as exc:
            QMessageBox.warning(self, "Mark as posted", f"Could not move the photos:\n{exc}")


class TodayPopupWindow(QWidget):
    """Floating always-on-top wrapper around TodayPanel, used for the
    system-tray popup."""

    def __init__(self, config: AppConfig, store: SeriesStore, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Next post")
        self.resize(640, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = TodayPanel(config, store, parent=self)
        layout.addWidget(self.panel)

    def refresh(self) -> None:
        self.panel.refresh()


class TodayTray(QSystemTrayIcon):
    def __init__(
        self,
        config: AppConfig,
        store: SeriesStore,
        app: QApplication,
        main_window: Optional[QWidget] = None,
    ) -> None:
        super().__init__(_make_tray_icon(), app)
        self.app = app
        self.store = store
        self.main_window = main_window
        self.popup = TodayPopupWindow(config, store)

        menu = QMenu()
        show_action = menu.addAction("Show next post")
        show_action.triggered.connect(self._show_popup)

        if main_window is not None:
            show_window_action = menu.addAction("Show main window")
            show_window_action.triggered.connect(self._show_main_window)
            reset_window_action = menu.addAction("Reset main window position")
            reset_window_action.triggered.connect(self._reset_main_window)

        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._quit)
        self.setContextMenu(menu)

        self.setToolTip("dw_insta")
        self.activated.connect(self._on_activated)

        # A visible QSystemTrayIcon holds a native window handle on Windows;
        # if it's not hidden before quit() the process hangs on exit (shows
        # up as repeated "not responding" prompts). aboutToQuit is a safety
        # net for any quit path that doesn't go through _quit().
        app.aboutToQuit.connect(self.hide)

    def _quit(self) -> None:
        self.store.flush()
        self.hide()
        self._teardown_windows()
        self.app.quit()

    def _teardown_windows(self) -> None:
        """MainWindow/TodayPopupWindow close() just hides them (by design,
        so 'Show main window'/tray click can bring them back while running
        in the tray) — it never deletes the underlying Qt objects. Without
        an explicit deleteLater() here those hidden windows, and everything
        they own (child widgets, QTimers), are still alive when the
        interpreter starts tearing down Qt, which is what stalls process
        exit. Force the deferred deletes to run now, while the event loop
        is still up, rather than leaving them queued."""
        self.popup.close()
        self.popup.deleteLater()
        if self.main_window is not None:
            self.main_window.close()
            self.main_window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _show_main_window(self) -> None:
        if self.main_window is not None:
            self.main_window.show()
            self.main_window.raise_()
            self.main_window.activateWindow()

    def _reset_main_window(self) -> None:
        if self.main_window is not None:
            self.main_window.reset_window_position()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_popup()

    def _show_popup(self) -> None:
        if not self.store.reload_if_changed():
            self.popup.refresh()
        self.popup.show()
        self.popup.raise_()
        self.popup.activateWindow()
