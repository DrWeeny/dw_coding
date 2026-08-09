from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer, Qt, QUrl
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
from core.comment import compose_comment
from core.paths import resolve_photo_path
from core.scanner import sync_series
from core.scheduler import today_group
from core.series import Group, SeriesState

from .carousel_order import CarouselOrderWidget
from .drag_thumbnail import DraggableThumbnail
from .flow_layout import FlowLayout
from .hashtag_chip import HashtagChip

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
    """Panel showing today's scheduled post: a draggable image (with
    prev/next for carousel posts), an editable caption with a live
    Instagram char counter, hashtags as removable chips, and quick actions.
    Reloads state from disk on every refresh() rather than sharing the
    MainWindow's in-memory model, so the two stay simple and independent.
    Plain embeddable QWidget — no window flags — so it can sit inline in
    MainWindow's layout and, separately, inside TodayPopupWindow for the
    system-tray popup."""

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.config = config
        self.state: Optional[SeriesState] = None
        self.group: Optional[Group] = None

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_caption)

        root = QVBoxLayout(self)

        # --- top bar ---
        top_bar = QHBoxLayout()
        title = QLabel("📅 Daily Photo Post")
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
        date_row.addWidget(QLabel("📅 Date:"))
        self.date_label = QLabel("-")
        date_row.addWidget(self.date_label)
        date_row.addStretch(1)
        desc_col.addLayout(date_row)

        content_row.addLayout(desc_col, 1)
        root.addLayout(content_row, 1)

        # --- hashtags ---
        tags_header = QHBoxLayout()
        tags_header.addWidget(QLabel("# Hashtags"))
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
        self.posted_btn = QPushButton("Mark as posted")
        self.posted_btn.clicked.connect(self._mark_posted)
        buttons_row.addWidget(self.posted_btn)
        root.addLayout(buttons_row)

        self.status_label = QLabel("")
        root.addWidget(self.status_label)

    # --- loading ---

    def refresh(self) -> None:
        series_name = self.config.active_series
        if not series_name:
            self._set_no_group("No active series")
            return

        series_dir = Path(self.config.root_dir) / series_name
        self.state = sync_series(series_dir)
        self.group = today_group(self.state)

        if self.group is None:
            self._set_no_group(f"{series_name}: not started yet")
            return

        self.order_widget.set_photos(self.group.photos)
        self._show_photo_by_filename(self.group.photos[0] if self.group.photos else None)

        self.date_label.setText(date.today().strftime("%b %d, %Y"))

        self.caption_edit.blockSignals(True)
        self.caption_edit.setPlainText(self.group.caption or "")
        self.caption_edit.blockSignals(False)
        self._update_char_count()

        self.caption_suggestion_btn.setVisible(bool(self.group.suggested_caption))
        self.caption_suggestion_btn.setToolTip(self.group.suggested_caption or "")

        self._rebuild_hashtag_chips()
        self.hashtags_suggestion_btn.setVisible(bool(self.group.suggested_hashtags))
        self.hashtags_suggestion_btn.setToolTip(self.group.suggested_hashtags or "")

        self.posted_btn.setEnabled(not self.group.is_posted)
        self.status_label.setText("Already marked posted" if self.group.is_posted else "")

    def _set_no_group(self, message: str) -> None:
        self.group = None
        self.thumb.clear_photo()
        self.order_widget.clear()
        self.caption_edit.blockSignals(True)
        self.caption_edit.setPlainText("")
        self.caption_edit.blockSignals(False)
        self.char_count_label.setText(f"0 / {INSTAGRAM_CAPTION_LIMIT}")
        self.caption_suggestion_btn.setVisible(False)
        self.hashtags_suggestion_btn.setVisible(False)
        self.date_label.setText(date.today().strftime("%b %d, %Y"))
        self._clear_hashtag_chips()
        self.posted_btn.setEnabled(False)
        self.status_label.setText(message)

    # --- image carousel ---

    def _show_photo_by_filename(self, filename: Optional[str]) -> None:
        path = resolve_photo_path(self.state, filename) if (self.state and filename) else None
        if path is not None:
            self.thumb.set_photo(path)
        else:
            self.thumb.clear_photo()

    def _on_photo_selected(self, row: int) -> None:
        item = self.order_widget.item(row)
        filename = item.data(Qt.ItemDataRole.UserRole) if item else None
        self._show_photo_by_filename(filename)

    def _on_photos_reordered(self, new_order: list[str]) -> None:
        if not self.state or not self.group:
            return
        self.group.photos = new_order
        self.state.save()

    # --- caption ---

    def _on_caption_edited(self) -> None:
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
        if not self.state or not self.group:
            return
        self.group.caption = self.caption_edit.toPlainText() or None
        self.state.save()

    def _accept_caption_suggestion(self) -> None:
        if not self.state or not self.group or not self.group.suggested_caption:
            return
        self.group.caption = self.group.suggested_caption
        self.group.suggested_caption = None
        self.state.save()
        self.caption_edit.blockSignals(True)
        self.caption_edit.setPlainText(self.group.caption or "")
        self.caption_edit.blockSignals(False)
        self.caption_suggestion_btn.setVisible(False)
        self._update_char_count()

    # --- hashtags ---

    def _effective_tags(self) -> list[str]:
        if not self.state or not self.group:
            return []
        text = self.group.hashtags if self.group.hashtags is not None else self.state.hashtags
        return text.split() if text else []

    def _clear_hashtag_chips(self) -> None:
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild_hashtag_chips(self) -> None:
        self._clear_hashtag_chips()
        for tag in self._effective_tags():
            chip = HashtagChip(tag, parent=self.tags_container)
            chip.removed.connect(self._remove_hashtag)
            self.tags_layout.addWidget(chip)

    def _set_group_hashtags(self, tags: list[str]) -> None:
        if not self.state or not self.group:
            return
        self.group.hashtags = " ".join(tags) if tags else None
        self.state.save()
        self._rebuild_hashtag_chips()
        self._update_char_count()

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
        tags = [t for t in self._effective_tags() if t != tag]
        self._set_group_hashtags(tags)

    def _accept_hashtags_suggestion(self) -> None:
        if not self.state or not self.group or not self.group.suggested_hashtags:
            return
        self.group.hashtags = self.group.suggested_hashtags
        self.group.suggested_hashtags = None
        self.state.save()
        self._rebuild_hashtag_chips()
        self.hashtags_suggestion_btn.setVisible(False)
        self._update_char_count()

    # --- actions ---

    def _copy_comment(self) -> None:
        if not self.state or not self.group:
            return
        QGuiApplication.clipboard().setText(compose_comment(self.state, self.group))

    def _open_instagram(self) -> None:
        QDesktopServices.openUrl(QUrl(self.config.instagram_profile_url))

    def _mark_posted(self) -> None:
        if not self.state or not self.group or self.group.is_posted:
            return
        reply = QMessageBox.question(
            self,
            "Mark as posted",
            "Move today's photo(s) into archived/? Only do this after you've actually posted.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        archive_group(self.state, self.group)
        self.refresh()


class TodayPopupWindow(QWidget):
    """Floating always-on-top wrapper around TodayPanel, used for the
    system-tray popup."""

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Today's post")
        self.resize(640, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = TodayPanel(config, parent=self)
        layout.addWidget(self.panel)

    def refresh(self) -> None:
        self.panel.refresh()


class TodayTray(QSystemTrayIcon):
    def __init__(
        self, config: AppConfig, app: QApplication, main_window: Optional[QWidget] = None
    ) -> None:
        super().__init__(_make_tray_icon(), app)
        self.app = app
        self.main_window = main_window
        self.popup = TodayPopupWindow(config)

        menu = QMenu()
        show_action = menu.addAction("Show today's post")
        show_action.triggered.connect(self._show_popup)

        if main_window is not None:
            show_window_action = menu.addAction("Show main window")
            show_window_action.triggered.connect(self._show_main_window)
            reset_window_action = menu.addAction("Reset main window position")
            reset_window_action.triggered.connect(self._reset_main_window)

        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(app.quit)
        self.setContextMenu(menu)

        self.setToolTip("dw_insta")
        self.activated.connect(self._on_activated)

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
        self.popup.refresh()
        self.popup.show()
        self.popup.raise_()
        self.popup.activateWindow()
