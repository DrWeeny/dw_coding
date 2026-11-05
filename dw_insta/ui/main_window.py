from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from config import INSTAGRAM_BASE_URL, AppConfig
from core import grouping
from core.archive import archive_group, unarchive_group
from core.comment import accept_all_caption_suggestions, accept_all_hashtags_suggestions
from core.contact_sheet import build_contact_sheet
from core.paths import resolve_group_cover
from core.scheduler import pending_groups, posted_on
from core.series import SeriesState

from .collapsible_section import CollapsibleSection
from .mosaic_view import MosaicView
from .preview_dialog import PreviewDialog
from .series_model import COL_CAPTION, COL_HASHTAGS, COL_PHOTOS, SeriesTableModel
from .series_store import SeriesStore
from .suggestion_delegate import SuggestionDelegate
from .today_widget import TodayPanel
from .window_state import (
    get_hide_archived,
    get_thumb_size,
    reset_window_state,
    restore_window_state,
    save_window_state,
    set_hide_archived,
    set_thumb_size,
)


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, store: SeriesStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.store = store
        # Group ids in the order they were selected: the first one picked is
        # the one whose caption a merge keeps.
        self._selection_order: list[str] = []

        self.setWindowTitle("dw_insta")
        self.resize(1000, 940)

        self.settings_menu = self.menuBar().addMenu("Settings")
        self.change_root_action = self.settings_menu.addAction("Change Root Folder...")
        self.change_root_action.triggered.connect(self._change_root_folder)
        self.set_handle_action = self.settings_menu.addAction("Set Instagram Handle...")
        self.set_handle_action.triggered.connect(self._set_instagram_handle)
        self.set_webhook_action = self.settings_menu.addAction("Set Discord Webhook...")
        self.set_webhook_action.triggered.connect(self._set_discord_webhook)

        self.window_menu = self.menuBar().addMenu("Window")
        self.reset_position_action = self.window_menu.addAction("Reset Window Position")
        self.reset_position_action.setShortcut("Ctrl+Shift+R")
        self.reset_position_action.triggered.connect(self.reset_window_position)

        self.view_menu = self.menuBar().addMenu("View")
        thumb_size_widget = QWidget()
        thumb_size_layout = QVBoxLayout(thumb_size_widget)
        self.thumb_size_label = QLabel("Thumbnail size: 48px")
        thumb_size_layout.addWidget(self.thumb_size_label)
        self.thumb_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.thumb_size_slider.setRange(24, 256)
        self.thumb_size_slider.setSingleStep(8)
        self.thumb_size_slider.setPageStep(16)
        self.thumb_size_slider.setTickInterval(16)
        self.thumb_size_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.thumb_size_slider.setMinimumWidth(180)
        self.thumb_size_slider.valueChanged.connect(self._on_thumb_size_changed)
        thumb_size_layout.addWidget(self.thumb_size_slider)
        self.thumb_size_action = QWidgetAction(self)
        self.thumb_size_action.setDefaultWidget(thumb_size_widget)
        self.view_menu.addAction(self.thumb_size_action)

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Series:"))
        self.series_combo = QComboBox()
        self.series_combo.currentTextChanged.connect(self._on_series_changed)
        top_row.addWidget(self.series_combo, 1)
        top_row.addWidget(QLabel("Not before:"))
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_date_edit.setToolTip(
            "Don't plan any post before this day, to line a series up ahead of time. "
            "A day in the past has no effect: the queue always carries on from today."
        )
        self.start_date_edit.dateChanged.connect(self._on_start_date_changed)
        top_row.addWidget(self.start_date_edit)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_series)
        top_row.addWidget(refresh_btn)
        layout.addLayout(top_row)

        self.today_panel = TodayPanel(config, store, parent=central)
        layout.addWidget(self.today_panel)

        self.queue_label = QLabel("Queue: -")
        layout.addWidget(self.queue_label)

        self.ai_section = CollapsibleSection("AI", color="#2f6fed", expanded=False)
        layout.addWidget(self.ai_section)

        notes_row = QHBoxLayout()
        notes_col = QVBoxLayout()
        notes_col.addWidget(QLabel("Series notes (event, location, personal angle, voice examples — read before drafting captions):"))
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setFixedHeight(70)
        self.notes_edit.setPlaceholderText(
            "e.g. La Fête de la Musique, Canal Saint Martin, Paris — explain the event for an "
            "international audience, casual/personal tone, first person."
        )
        notes_col.addWidget(self.notes_edit)
        notes_row.addLayout(notes_col, 1)
        save_notes_btn = QPushButton("Save notes")
        save_notes_btn.clicked.connect(self._save_notes)
        notes_row.addWidget(save_notes_btn, alignment=Qt.AlignmentFlag.AlignBottom)
        self.ai_section.content_layout.addLayout(notes_row)

        ai_actions_row = QHBoxLayout()
        contact_sheets_btn = QPushButton("Generate contact sheets")
        contact_sheets_btn.clicked.connect(self._generate_contact_sheets)
        ai_actions_row.addWidget(contact_sheets_btn)
        apply_hashtags_btn = QPushButton("Apply all suggested hashtags")
        apply_hashtags_btn.clicked.connect(self._apply_all_hashtag_suggestions)
        ai_actions_row.addWidget(apply_hashtags_btn)
        apply_captions_btn = QPushButton("Apply all suggested captions")
        apply_captions_btn.clicked.connect(self._apply_all_caption_suggestions)
        ai_actions_row.addWidget(apply_captions_btn)
        self.ai_section.content_layout.addLayout(ai_actions_row)

        self.gear_line_checkbox = QCheckBox("Include \"Shot on ...\" camera/lens line from EXIF in the comment")
        self.gear_line_checkbox.toggled.connect(self._toggle_gear_line)
        self.ai_section.content_layout.addWidget(self.gear_line_checkbox)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        list_tab = QWidget()
        list_layout = QVBoxLayout(list_tab)

        table_options_row = QHBoxLayout()
        self.hide_archived_checkbox = QCheckBox("Hide posted and skipped")
        self.hide_archived_checkbox.toggled.connect(self._toggle_hide_archived)
        table_options_row.addWidget(self.hide_archived_checkbox)
        table_options_row.addStretch(1)
        list_layout.addLayout(table_options_row)

        self.table = QTableView()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setWordWrap(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(84)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_context_menu)
        self.table.doubleClicked.connect(self._on_table_double_clicked)
        list_layout.addWidget(self.table, 1)

        actions_row = QHBoxLayout()

        merge_btn = QPushButton("Merge selected into carousel")
        merge_btn.setToolTip(
            "Ctrl+click rows in the order the photos should appear. "
            "The first row you pick keeps its caption and hashtags."
        )
        merge_btn.clicked.connect(self._merge_selected)
        actions_row.addWidget(merge_btn)

        split_btn = QPushButton("Split group...")
        split_btn.clicked.connect(self._split_selected)
        actions_row.addWidget(split_btn)

        archive_btn = QPushButton("Mark as posted / Archive")
        archive_btn.clicked.connect(self._archive_selected)
        actions_row.addWidget(archive_btn)

        list_layout.addLayout(actions_row)
        self.tabs.addTab(list_tab, "List")

        mosaic_tab = QWidget()
        mosaic_layout = QVBoxLayout(mosaic_tab)
        mosaic_hint = QLabel(
            "Drag tiles to reorder the queue: the first post that isn't posted or skipped is "
            "the next one. Always shows the full series, regardless of the Hide posted and "
            "skipped setting on the List tab."
        )
        mosaic_hint.setWordWrap(True)
        mosaic_hint.setStyleSheet("color: #888;")
        mosaic_layout.addWidget(mosaic_hint)
        self.mosaic_view = MosaicView()
        self.mosaic_view.reordered.connect(self._on_mosaic_reordered)
        mosaic_layout.addWidget(self.mosaic_view, 1)
        self.tabs.addTab(mosaic_tab, "Mosaic")

        self.thumb_size_slider.blockSignals(True)
        self.thumb_size_slider.setValue(get_thumb_size())
        self.thumb_size_slider.blockSignals(False)
        self.thumb_size_label.setText(f"Thumbnail size: {self.thumb_size_slider.value()}px")

        self.hide_archived_checkbox.blockSignals(True)
        self.hide_archived_checkbox.setChecked(get_hide_archived())
        self.hide_archived_checkbox.blockSignals(False)

        self.model = SeriesTableModel(
            store,
            thumb_size=self.thumb_size_slider.value(),
            hide_archived=self.hide_archived_checkbox.isChecked(),
        )
        self.table.setModel(self.model)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        delegate = SuggestionDelegate(self.table)
        self.table.setItemDelegateForColumn(COL_CAPTION, delegate)
        self.table.setItemDelegateForColumn(COL_HASHTAGS, delegate)

        store.changed.connect(self._on_store_changed)
        store.warning.connect(self._on_store_warning)

        if not Path(self.config.root_dir).is_dir():
            self._prompt_for_root_dir()

        self._populate_series_combo()
        restore_window_state(self, self.table)
        self._apply_thumb_size(self.thumb_size_slider.value())

    @property
    def state(self) -> SeriesState | None:
        return self.store.state

    def reset_window_position(self) -> None:
        """Recenter the window on the primary screen at the default size and
        persist it immediately. Useful when a saved position from a
        multi-monitor setup ends up off-screen after going back to a single
        screen. Also reachable from the tray menu since that's the one UI
        element still reachable when the window itself is lost off-screen."""
        reset_window_state(self)
        save_window_state(self, self.table)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        save_window_state(self, self.table)
        super().closeEvent(event)

    def _prompt_for_root_dir(self) -> bool:
        start_dir = self.config.root_dir if Path(self.config.root_dir).is_dir() else str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose the folder containing your series folders", start_dir
        )
        if not chosen:
            return False
        self.config.root_dir = chosen
        self.config.active_series = None
        self.config.save()
        return True

    def _change_root_folder(self) -> None:
        if self._prompt_for_root_dir():
            self._populate_series_combo()

    def _set_instagram_handle(self) -> None:
        current = self.config.instagram_profile_url
        handle = current[len(INSTAGRAM_BASE_URL):].strip("/") if current.startswith(INSTAGRAM_BASE_URL) else ""
        text, ok = QInputDialog.getText(self, "Instagram handle", "Handle (without @):", text=handle)
        if not ok:
            return
        handle = text.strip().lstrip("@")
        self.config.instagram_profile_url = f"{INSTAGRAM_BASE_URL}{handle}/" if handle else INSTAGRAM_BASE_URL
        self.config.save()

    def _set_discord_webhook(self) -> None:
        text, ok = QInputDialog.getText(
            self,
            "Discord webhook",
            "Webhook URL (channel Settings > Integrations > Webhooks), empty to remove:",
            text=self.config.discord_webhook_url or "",
        )
        if not ok:
            return
        self.config.discord_webhook_url = text.strip() or None
        self.config.save()

    def _populate_series_combo(self) -> None:
        root = Path(self.config.root_dir)
        names = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
        name = self.config.active_series if self.config.active_series in names else (names[0] if names else "")

        self.series_combo.blockSignals(True)
        self.series_combo.clear()
        self.series_combo.addItems(names)
        self.series_combo.setCurrentText(name)
        self.series_combo.blockSignals(False)

        if name:
            self._on_series_changed(name)
        else:
            self.store.clear()

    def _on_series_changed(self, name: str) -> None:
        if not name:
            return
        # out_4x5/ is what the scanner (and every thumbnail) reads, so the
        # store fills it first: photos not yet processed get their canvas
        # there, the rest are copied through untouched.
        try:
            report = self.store.open_series(name)
        except OSError as exc:
            QMessageBox.warning(self, "Series", f"Could not open {name}:\n{exc}")
            return
        self._show_process_report(report)

        self.notes_edit.blockSignals(True)
        self.notes_edit.setPlainText(self.state.caption_template)
        self.notes_edit.blockSignals(False)

    def _show_process_report(self, report: dict[str, list[str]]) -> None:
        portraits = len(report["padded"]) + len(report["copied"])
        landscapes = len(report["landscape"])
        parts = []
        if portraits or landscapes:
            parts.append(f"Processed {portraits} portrait and {landscapes} landscape photo(s) into out_4x5")
        if report["replaced"]:
            parts.append(f"{len(report['replaced'])} replaced an older version")
        if report["failed"]:
            parts.append(f"{len(report['failed'])} unreadable, will retry on Refresh: {report['failed'][0]}")
        if parts:
            self.statusBar().showMessage(", ".join(parts), 15000 if report["failed"] else 8000)

    def _on_store_warning(self, message: str) -> None:
        QMessageBox.warning(self, "Series state", message)

    def _on_store_changed(self) -> None:
        self.model.refresh()
        self.mosaic_view.populate(self.state)
        self._refresh_labels()

        if self.state is None:
            return
        start = self.state.start_date or date.today().isoformat()
        self.start_date_edit.blockSignals(True)
        self.start_date_edit.setDate(QDate.fromString(start, Qt.DateFormat.ISODate))
        self.start_date_edit.blockSignals(False)

        self.gear_line_checkbox.blockSignals(True)
        self.gear_line_checkbox.setChecked(self.state.include_gear_line)
        self.gear_line_checkbox.blockSignals(False)

    def _on_start_date_changed(self, qdate: QDate) -> None:
        """Lets you plan several series ahead of time: pick any series from
        the combo and set the first day it may post."""
        new_date = date(qdate.year(), qdate.month(), qdate.day()).isoformat()
        if not self.state or self.state.start_date == new_date:
            return

        def apply(state: SeriesState) -> None:
            state.start_date = new_date

        self.store.mutate(apply)

    def _refresh_series(self) -> None:
        name = self.series_combo.currentText()
        if name:
            self._on_series_changed(name)

    def _apply_thumb_size(self, value: int) -> None:
        """Single source of truth for everything the thumbnail size affects:
        the model's decoration size, the row height, and the Photos column
        width. Called both live (slider drag) and once at startup after
        restoring the persisted value, so the two paths can never drift
        apart (that drift was the cause of thumbnails not fitting their
        column after reopening the app)."""
        self.model.set_thumb_size(value)
        self.table.verticalHeader().setDefaultSectionSize(max(84, value + 16))
        self.table.setColumnWidth(COL_PHOTOS, value + 16)
        self.mosaic_view.set_icon_size(value)

    def _on_thumb_size_changed(self, value: int) -> None:
        self.thumb_size_label.setText(f"Thumbnail size: {value}px")
        self._apply_thumb_size(value)
        set_thumb_size(value)

    def _toggle_hide_archived(self, checked: bool) -> None:
        self.model.set_hide_archived(checked)
        set_hide_archived(checked)

    def _on_mosaic_reordered(self, order_ids: list[str]) -> None:
        try:
            self.store.mutate(lambda state: grouping.reorder_groups(state, order_ids))
        except ValueError as exc:
            QMessageBox.warning(self, "Reorder failed", str(exc))
            self.mosaic_view.populate(self.state, force=True)  # snap the view back to the real order

    def _save_notes(self) -> None:
        notes = self.notes_edit.toPlainText()

        def apply(state: SeriesState) -> None:
            state.caption_template = notes

        self.store.mutate(apply)

    def _toggle_gear_line(self, checked: bool) -> None:
        def apply(state: SeriesState) -> None:
            state.include_gear_line = checked

        self.store.mutate(apply)

    def _generate_contact_sheets(self) -> None:
        if not self.state:
            return
        out_dir = self.state.out_dir
        photos = [
            (f"{i:02d}", out_dir / group.photos[0])
            for i, group in enumerate(self.state.groups, start=1)
            if group.photos and group.is_pending
        ]
        if not photos:
            QMessageBox.information(self, "Contact sheets", "No pending photos to lay out.")
            return

        sheets_dir = Path(self.state.source_dir) / "contact_sheets"
        if sheets_dir.is_dir():
            for old_sheet in sheets_dir.glob("sheet_*.jpg"):
                old_sheet.unlink()

        chunk_size = 20
        sheet_paths = []
        for start in range(0, len(photos), chunk_size):
            chunk = photos[start : start + chunk_size]
            sheet_path = sheets_dir / f"sheet_{start // chunk_size + 1}.jpg"
            build_contact_sheet(chunk, sheet_path, columns=5)
            sheet_paths.append(sheet_path)

        QMessageBox.information(
            self,
            "Contact sheets",
            f"Generated {len(sheet_paths)} sheet(s) (tile numbers = position in the table) in:\n{sheets_dir}",
        )

    def _apply_all_hashtag_suggestions(self) -> None:
        if not self.state:
            return
        count = self.store.mutate(accept_all_hashtags_suggestions)
        QMessageBox.information(self, "Hashtags applied", f"Applied {count} suggested hashtag set(s).")

    def _apply_all_caption_suggestions(self) -> None:
        if not self.state:
            return
        count = self.store.mutate(accept_all_caption_suggestions)
        QMessageBox.information(self, "Captions applied", f"Applied {count} suggested caption(s).")

    def _refresh_labels(self) -> None:
        if not self.state:
            self.queue_label.setText("Queue: -")
            return
        groups = self.state.groups
        posted = sum(1 for g in groups if g.is_posted)
        skipped = sum(1 for g in groups if g.skipped and not g.is_posted)
        text = f"Queue: {len(pending_groups(self.state))} to post, {posted} posted, {skipped} skipped"
        posted_today = posted_on(self.state, date.today())
        if posted_today:
            text += f" ({posted_today} today)"
        self.queue_label.setText(text)

    def _on_selection_changed(self, selected, deselected) -> None:
        for gid in self._group_ids_in(deselected):
            if gid in self._selection_order:
                self._selection_order.remove(gid)
        for gid in self._group_ids_in(selected):
            if gid not in self._selection_order:
                self._selection_order.append(gid)

    def _group_ids_in(self, selection) -> list[str]:
        rows = sorted({idx.row() for idx in selection.indexes()})
        return [self.model.group_at(r).id for r in rows if r < self.model.rowCount()]

    def _selected_group_ids(self) -> list[str]:
        """Selected groups, in the order they were picked. A model reset clears
        the selection without signalling it, hence the filter against what's
        selected right now."""
        rows = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        current = [self.model.group_at(r).id for r in rows]
        ordered = [gid for gid in self._selection_order if gid in current]
        ordered += [gid for gid in current if gid not in ordered]
        self._selection_order = ordered
        return list(ordered)

    def _selected_groups(self) -> list:
        groups = (self.state.find_group(gid) for gid in self._selected_group_ids())
        return [g for g in groups if g is not None]

    def _on_table_double_clicked(self, index) -> None:
        if index.column() != COL_PHOTOS:
            return
        self._show_preview_for_row(index.row())

    def _show_table_context_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        selected_rows = {i.row() for i in self.table.selectionModel().selectedRows()}
        if index.row() not in selected_rows:
            self.table.selectRow(index.row())

        group = self.model.group_at(index.row())
        groups = self._selected_groups()
        menu = QMenu(self)
        preview_action = menu.addAction("Show preview")
        preview_action.triggered.connect(lambda: self._show_preview_for_row(index.row()))
        next_action = menu.addAction("Make this the next post")
        next_action.setEnabled(group.is_pending)
        next_action.triggered.connect(lambda: self._make_next(group.id))
        menu.addSeparator()
        skip_action = menu.addAction("Skip (not worth posting)")
        skip_action.setEnabled(any(g.is_pending for g in groups))
        skip_action.triggered.connect(self._skip_selected)
        restore_action = menu.addAction("Put back in the queue")
        restore_action.setEnabled(any(g.skipped and not g.is_posted for g in groups))
        restore_action.triggered.connect(self._restore_selected)
        not_posted_action = menu.addAction("Mark as not posted")
        not_posted_action.setEnabled(any(g.is_posted for g in groups))
        not_posted_action.triggered.connect(self._unarchive_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _show_preview_for_row(self, row: int) -> None:
        """Preview navigates whatever the table currently shows (respects
        the hide-archived filter), so Left/Right in the dialog matches
        stepping through visible rows."""
        if not self.state:
            return
        items = [
            (group.photos[0] if group.photos else f"({i + 1})", resolve_group_cover(self.state, group))
            for i, group in enumerate(self.model.visible_groups())
        ]
        PreviewDialog(items, start_index=row, parent=self).exec()

    def _make_next(self, group_id: str) -> None:
        try:
            self.store.mutate(lambda state: grouping.move_to_next(state, group_id))
        except ValueError as exc:
            QMessageBox.information(self, "Next post", str(exc))

    def _set_skipped(self, skipped: bool) -> None:
        ids = self._selected_group_ids()

        def apply(state: SeriesState) -> None:
            for gid in ids:
                group = state.find_group(gid)
                if group is not None and not group.is_posted:
                    group.skipped = skipped

        self.store.mutate(apply)

    def _skip_selected(self) -> None:
        self._set_skipped(True)

    def _restore_selected(self) -> None:
        self._set_skipped(False)

    def _merge_selected(self) -> None:
        ids = self._selected_group_ids()
        if len(ids) < 2:
            QMessageBox.information(
                self, "Merge", "Select two or more rows to merge into one carousel post."
            )
            return
        try:
            self.store.mutate(lambda state: grouping.merge_groups(state, ids))
        except ValueError as exc:
            QMessageBox.warning(self, "Merge failed", str(exc))

    def _split_selected(self) -> None:
        groups = self._selected_groups()
        if len(groups) != 1:
            QMessageBox.information(self, "Split", "Select exactly one multi-photo row to split.")
            return
        group = groups[0]
        if len(group.photos) < 2:
            QMessageBox.information(self, "Split", "This post only has one photo.")
            return
        text, ok = QInputDialog.getText(
            self,
            "Split group",
            f"Photos: {', '.join(group.photos)}\nEnter comma-separated filenames to split off:",
        )
        if not ok or not text.strip():
            return
        to_split = [t.strip() for t in text.split(",") if t.strip()]
        group_id = group.id
        try:
            self.store.mutate(lambda state: grouping.split_group(state, group_id, to_split))
        except ValueError as exc:
            QMessageBox.warning(self, "Split failed", str(exc))

    def _archive_selected(self) -> None:
        ids = self._selected_group_ids()
        if not ids:
            QMessageBox.information(self, "Archive", "Select one or more rows to mark as posted.")
            return
        reply = QMessageBox.question(
            self,
            "Mark as posted",
            f"Move {len(ids)} post(s) worth of photos into archived/?\n"
            "Only do this after you've actually posted them.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def apply(state: SeriesState) -> None:
            for gid in ids:
                group = state.find_group(gid)
                if group is not None and not group.is_posted:
                    archive_group(state, group)

        self.store.flush()
        try:
            self.store.mutate(apply)
        except OSError as exc:
            QMessageBox.warning(self, "Mark as posted", f"Could not move the photos:\n{exc}")

    def _unarchive_selected(self) -> None:
        ids = self._selected_group_ids()

        def apply(state: SeriesState) -> None:
            for gid in ids:
                group = state.find_group(gid)
                if group is not None and group.is_posted:
                    unarchive_group(state, group)

        try:
            self.store.mutate(apply)
        except OSError as exc:
            QMessageBox.warning(self, "Mark as not posted", f"Could not move the photos:\n{exc}")
