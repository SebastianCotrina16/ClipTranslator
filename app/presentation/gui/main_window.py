from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.application.pipeline import Pipeline
from app.application.updates import Release
from app.config.session import SavedClip, Session, SessionStore
from app.config.store import SettingsStore
from app.domain.languages import ENGLISH_NAMES, TARGET_LANGUAGES
from app.domain.models import Cue
from app.domain.subtitles import format_for_screen
from app.infrastructure.ffmpeg import has_video
from app.infrastructure.self_update import can_update_itself, launch_installer
from app.presentation.gui.background import BackgroundRunner
from app.presentation.gui.clip_queue import ClipList, ClipStatus
from app.presentation.gui.cue_table import Column, CueTableModel
from app.presentation.gui.edit_commands import CueState
from app.presentation.gui.icons import app_icon, logo_pixmap
from app.presentation.gui.job import (
    ExportVideoJob,
    JobRequest,
    RetranslateJob,
    SubtitleJob,
    UpdateCheckJob,
    UpdateDownloadJob,
)
from app.presentation.gui.player import SubtitledPlayer
from app.presentation.gui.setup_dialog import SetupDialog
from app.presentation.gui.texts import MEDIA_FILTER, language_name, stage_label
from app.presentation.gui.versions_dialog import VersionsDialog
from app.presentation.gui.video_style_dialog import VideoStyleDialog
from app.presentation.gui.widgets import NoticeBox, UpdateBanner, card, icon_button, section_label

WINDOW_SIZE = (1400, 900)
SIDEBAR_WIDTH = 370
PROGRESS_STEPS = 1000
DEFAULT_SHIFT_SECONDS = 0.25
JOB_DONE_SIGNALS = ("succeeded", "failed", "cancelled")
INSTALLER_HANDOFF_MS = 800


def restored_status(value: str) -> ClipStatus:
    try:
        status = ClipStatus(value)
    except ValueError:
        return ClipStatus.PENDING
    return ClipStatus.PENDING if status is ClipStatus.PROCESSING else status


class MainWindow(QMainWindow):
    def __init__(
        self,
        store: SettingsStore | None = None,
        log_file: Path | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        super().__init__()
        self._store = store or SettingsStore()
        self._session_store = session_store or SessionStore()
        self._first_run = not self._store.path.exists()
        self._settings = self._store.load()
        self._log_file = log_file
        self._media: Path | None = None
        self._pipeline: Pipeline | None = None
        self._files: list[Path] = []
        self._queue_active = False
        self._queue_total = 0
        self._release: Release | None = None
        self._updating = False
        self._runner = BackgroundRunner(self)
        self._update_runner = BackgroundRunner(self)
        self._model = CueTableModel()
        self._player = SubtitledPlayer()
        self._banner = UpdateBanner()
        self._clips = ClipList()
        self._add_files_button = icon_button("Add files", "plus")
        self._add_folder_button = icon_button("Add folder", "folder")
        self._process_all_button = icon_button("Process all", "queue")
        self._settings_button = icon_button("Settings", "settings", "ghost")
        self._source = QComboBox()
        self._target = QComboBox()
        self._context = QLineEdit()
        self._start_button = icon_button("Generate subtitles", "sparkles", "primary")
        self._cancel_button = icon_button("Cancel", "stop", "danger")
        self._progress = QProgressBar()
        self._stage = QLabel("Add a video to start.")
        self._percent = QLabel("")
        self._notices = NoticeBox()
        self._table = QTableView()
        self._summary = QLabel("Subtitles will appear here.")
        self._show_original = QCheckBox("Original on video")
        self._undo_button = icon_button("", "undo")
        self._redo_button = icon_button("", "redo")
        self._shift = QDoubleSpinBox()
        self._earlier_button = icon_button("Earlier", "earlier")
        self._later_button = icon_button("Later", "later")
        self._retranslate_button = icon_button("Retranslate", "refresh")
        self._versions_button = icon_button("Versions", "queue")
        self._revert_button = icon_button("Revert", "undo")
        self._folder_button = icon_button("", "folder")
        self._export_video_button = icon_button("Export video", "video")
        self._export_button = icon_button("Export subtitles", "download", "primary")
        self._build()
        self._restore_session()

    def add_media(self, paths: list[Path]) -> None:
        added = self._clips.add(paths)
        if added and not self._runner.busy and not self._queue_active:
            self.open_media(added[0])
        self._update_buttons()

    def open_media(self, media: Path) -> None:
        if not media.is_file() or self._runner.busy:
            return
        self._clips.add([media])
        self._clips.select(media.resolve())
        self._media = media.resolve()
        self._pipeline = None
        self._files = []
        self._model.set_cues([])
        self._player.set_cues([])
        self._player.load(self._media)
        self._notices.clear()
        self._set_progress(0.0, "Ready to generate subtitles.")
        self._summary.setText("Subtitles will appear here.")
        self._update_buttons()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._model.undo_stack.blockSignals(True)
        job = self._runner.job
        if isinstance(job, SubtitleJob):
            job.cancel()
        super().closeEvent(event)

    def _build(self) -> None:
        self.setWindowTitle("ClipTranslator")
        self.setWindowIcon(app_icon())
        self.resize(*WINDOW_SIZE)
        self._configure_widgets()
        self._connect_signals()
        root = QWidget()
        root.setObjectName("root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)
        layout.addLayout(self._header())
        layout.addWidget(self._banner)
        body = QHBoxLayout()
        body.setSpacing(20)
        body.addWidget(self._sidebar())
        body.addWidget(self._workspace(), stretch=1)
        layout.addLayout(body, stretch=1)
        self.setCentralWidget(root)
        self._update_buttons()
        if self._first_run:
            QTimer.singleShot(0, self._open_settings)
        elif self._settings.check_for_updates:
            QTimer.singleShot(1500, self._check_for_updates)

    def _configure_widgets(self) -> None:
        self._fill_languages()
        self._context.setPlaceholderText("Optional: what happens in the clip, names…")
        self._progress.setRange(0, PROGRESS_STEPS)
        self._progress.setTextVisible(False)
        self._percent.setObjectName("percent")
        self._stage.setObjectName("muted")
        self._stage.setWordWrap(True)
        self._summary.setObjectName("muted")
        self._cancel_button.hide()
        self._shift.setRange(0.01, 30.0)
        self._shift.setSingleStep(0.05)
        self._shift.setDecimals(2)
        self._shift.setSuffix(" s")
        self._shift.setValue(DEFAULT_SHIFT_SECONDS)
        self._shift.setFixedWidth(96)
        tips = {
            self._undo_button: "Undo (Ctrl+Z)",
            self._redo_button: "Redo (Ctrl+Y)",
            self._shift: "How far to move the subtitles",
            self._earlier_button: "Show the selected lines earlier (Alt+Left)",
            self._later_button: "Show the selected lines later (Alt+Right)",
            self._retranslate_button: "Translate the selected line again",
            self._versions_button: "See what each model heard on this line and pick one",
            self._revert_button: "Go back to the subtitles as they were generated",
            self._folder_button: "Open the output folder",
            self._export_video_button: "Create a copy of the video with the subtitles burned in",
            self._add_files_button: "Add one or more videos",
            self._add_folder_button: "Add every video in a folder",
            self._process_all_button: "Generate and export subtitles for every pending clip",
        }
        for widget, tip in tips.items():
            widget.setToolTip(tip)
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setWordWrap(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for column in (Column.NUMBER, Column.START, Column.END, Column.FLAGS):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (Column.ORIGINAL, Column.TRANSLATION):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

    def _header(self) -> QHBoxLayout:
        logo = QLabel()
        logo.setPixmap(logo_pixmap(44))
        title = QLabel("ClipTranslator")
        title.setObjectName("title")
        subtitle = QLabel("Detect, transcribe and translate the speech in any clip")
        subtitle.setObjectName("subtitle")
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header = QHBoxLayout()
        header.setSpacing(14)
        header.addWidget(logo)
        header.addLayout(titles)
        header.addStretch(1)
        header.addWidget(self._settings_button)
        return header

    def _sidebar(self) -> QWidget:
        clip_buttons = QHBoxLayout()
        clip_buttons.addWidget(self._add_files_button)
        clip_buttons.addWidget(self._add_folder_button)
        options = QFormLayout()
        options.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        options.setVerticalSpacing(10)
        options.addRow("From", self._source)
        options.addRow("To", self._target)
        options.addRow("Context", self._context)
        buttons = QHBoxLayout()
        buttons.addWidget(self._start_button, stretch=1)
        buttons.addWidget(self._cancel_button, stretch=1)
        progress_row = QHBoxLayout()
        progress_row.addWidget(self._progress, stretch=1)
        progress_row.addWidget(self._percent)
        sidebar = QWidget()
        sidebar.setObjectName("transparent")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(
            card(section_label("Clips"), clip_buttons, self._clips, self._process_all_button),
            stretch=1,
        )
        layout.addWidget(card(section_label("Languages"), options))
        layout.addWidget(card(buttons, progress_row, self._stage, spacing=10))
        layout.addWidget(self._notices)
        return sidebar

    def _workspace(self) -> QWidget:
        title_row = QHBoxLayout()
        title_row.addWidget(section_label("Subtitles"))
        title_row.addSpacing(8)
        title_row.addWidget(self._summary, stretch=1)
        title_row.addWidget(self._show_original)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        for widget in (
            self._undo_button,
            self._redo_button,
            self._shift,
            self._earlier_button,
            self._later_button,
            self._retranslate_button,
            self._versions_button,
            self._revert_button,
        ):
            tools.addWidget(widget)
        tools.addStretch(1)
        for widget in (self._folder_button, self._export_video_button, self._export_button):
            tools.addWidget(widget)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(16)
        splitter.addWidget(card(self._player))
        splitter.addWidget(card(title_row, tools, self._table))
        splitter.setSizes([440, 420])
        splitter.setChildrenCollapsible(False)
        return splitter

    def _fill_languages(self) -> None:
        self._source.addItem("Detect automatically", "")
        for code in sorted(ENGLISH_NAMES, key=language_name):
            self._source.addItem(language_name(code), code)
        self._fill_targets()

    def _fill_targets(self) -> None:
        self._target.clear()
        for code in TARGET_LANGUAGES:
            self._target.addItem(language_name(code), code)
        current = self._settings.translation.target_language
        if self._target.findData(current) < 0:
            self._target.addItem(language_name(current), current)
        self._target.setCurrentIndex(self._target.findData(current))

    def _connect_signals(self) -> None:
        self._clips.paths_dropped.connect(self.add_media)
        self._clips.clip_activated.connect(self._on_clip_activated)
        self._add_files_button.clicked.connect(self._choose_files)
        self._add_folder_button.clicked.connect(self._choose_folder)
        self._process_all_button.clicked.connect(self._process_all)
        self._settings_button.clicked.connect(self._open_settings)
        self._start_button.clicked.connect(self._start)
        self._cancel_button.clicked.connect(self._cancel)
        self._export_button.clicked.connect(self._export)
        self._export_video_button.clicked.connect(self._export_video)
        self._folder_button.clicked.connect(self._open_folder)
        self._retranslate_button.clicked.connect(self._retranslate_selected)
        self._versions_button.clicked.connect(self._choose_version)
        self._revert_button.clicked.connect(self._revert_edits)
        self._undo_button.clicked.connect(self._model.undo_stack.undo)
        self._redo_button.clicked.connect(self._model.undo_stack.redo)
        self._earlier_button.clicked.connect(lambda: self._shift_selected(-1))
        self._later_button.clicked.connect(lambda: self._shift_selected(1))
        self._show_original.toggled.connect(self._player.show_original)
        self._table.clicked.connect(self._seek_to_row)
        self._model.edited.connect(self._on_cues_edited)
        self._model.edit_rejected.connect(self._stage.setText)
        self._model.undo_stack.cleanChanged.connect(lambda *_: self._update_buttons())
        self._model.undo_stack.indexChanged.connect(lambda *_: self._update_buttons())
        self._table.selectionModel().selectionChanged.connect(lambda *_: self._update_buttons())
        self._runner.finished.connect(self._on_job_finished)
        self._banner.download_requested.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        self._banner.update_requested.connect(self._install_update)
        shortcuts = {
            QKeySequence.StandardKey.Undo: self._model.undo_stack.undo,
            QKeySequence.StandardKey.Redo: self._model.undo_stack.redo,
            QKeySequence("Alt+Left"): lambda: self._shift_selected(-1),
            QKeySequence("Alt+Right"): lambda: self._shift_selected(1),
        }
        for sequence, action in shortcuts.items():
            QShortcut(QKeySequence(sequence), self, activated=action)

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add videos", "", MEDIA_FILTER)
        if paths:
            self.add_media([Path(path) for path in paths])

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add every video in a folder")
        if folder:
            before = len(self._clips.paths())
            self.add_media([Path(folder)])
            if len(self._clips.paths()) == before:
                self._stage.setText("No new videos were found in that folder.")

    def _on_clip_activated(self, path: Path) -> None:
        if self._runner.busy or path == self._media:
            return
        self.open_media(path)
        if self._clips.status(path) in (ClipStatus.READY, ClipStatus.EXPORTED):
            self._start()

    def _start(self) -> None:
        if self._media is None or self._runner.busy or self._updating:
            return
        self._settings.translation.target_language = self._target.currentData()
        self._store.save(self._settings)
        request = JobRequest(
            media=self._media,
            source_language=self._source.currentData() or None,
            clip_context=self._context.text().strip(),
        )
        job = SubtitleJob(request, self._settings)
        job.progressed.connect(self._on_progress)
        job.busy_gpu.connect(
            lambda percent: self._notices.add(
                f"The GPU is at {percent}% because of another program (a game?). "
                "Everything will be slower."
            )
        )
        job.language_detected.connect(
            lambda code, probability: self._notices.add(
                f"Detected language: {language_name(code)} ({probability:.0%})"
            )
        )
        job.succeeded.connect(self._on_success)
        job.cancelled.connect(self._on_cancelled)
        job.failed.connect(self._on_failure)
        self._clips.set_status(self._media, ClipStatus.PROCESSING)
        self._set_progress(0.0, self._with_queue_prefix("Starting…"))
        self._runner.start(job, JOB_DONE_SIGNALS)
        self._update_buttons()

    def _process_all(self) -> None:
        if self._updating:
            return
        if self._runner.busy or not self._clips.with_status(ClipStatus.PENDING):
            self._stage.setText("There are no pending clips.")
            return
        self._queue_active = True
        self._queue_total = len(self._clips.with_status(ClipStatus.PENDING))
        self._start_next_in_queue()

    def _start_next_in_queue(self) -> None:
        pending = self._clips.with_status(ClipStatus.PENDING)
        if not self._queue_active or not pending:
            self._finish_queue()
            return
        self.open_media(pending[0])
        self._start()

    def _finish_queue(self) -> None:
        if not self._queue_active:
            return
        self._queue_active = False
        exported = len(self._clips.with_status(ClipStatus.EXPORTED))
        failed = len(self._clips.with_status(ClipStatus.FAILED))
        self._set_progress(1.0, f"Queue finished: {exported} exported, {failed} failed.")
        self._update_buttons()

    def _with_queue_prefix(self, message: str) -> str:
        if not self._queue_active:
            return message
        done = self._queue_total - len(self._clips.with_status(ClipStatus.PENDING))
        return f"Clip {max(done, 1)} of {self._queue_total} · {message}"

    def _cancel(self) -> None:
        job = self._runner.job
        if isinstance(job, SubtitleJob):
            job.cancel()
            self._queue_active = False
            self._cancel_button.setEnabled(False)
            self._stage.setText("Cancelling after the current step…")

    def _on_progress(self, overall: float, stage: str) -> None:
        self._set_progress(overall, self._with_queue_prefix(f"{stage_label(stage)}…"))

    def _on_success(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline
        cues = pipeline.state.cues
        self._model.set_cues(cues)
        self._player.set_cues(cues)
        flagged = sum(1 for cue in cues if cue.flags)
        self._summary.setText(f"{len(cues)} lines · {flagged} to review")
        for warning in pipeline.state.warnings:
            self._notices.add(warning)
        if pipeline.state.restored_edits:
            self._notices.add("Your previous edits for this clip were restored.")
        self._table.resizeRowsToContents()
        self._clips.set_status(pipeline.state.media, ClipStatus.READY)
        if self._queue_active:
            self._export(quiet=True)
        else:
            self._set_progress(1.0, "Done. Click a line to preview it, edit it, then export.")

    def _on_cancelled(self) -> None:
        if self._media is not None:
            self._clips.set_status(self._media, ClipStatus.PENDING)
        self._set_progress(0.0, "Cancelled.")

    def _on_failure(self, message: str) -> None:
        if self._media is not None:
            self._clips.set_status(self._media, ClipStatus.FAILED)
        if self._queue_active and self._media is not None:
            self._notices.add(f"{self._media.name}: {message}")
            return
        self._show_error(message)

    def _on_job_finished(self) -> None:
        self._update_buttons()
        if self._queue_active:
            QTimer.singleShot(0, self._start_next_in_queue)

    def _on_cues_edited(self) -> None:
        self._player.refresh_caption()
        if self._pipeline is None:
            return
        try:
            self._pipeline.save_edits()
        except OSError as error:
            self._stage.setText(f"Could not save your edits: {error}")
            return
        self._pipeline.state.restored_edits = True
        if self._clips.status(self._pipeline.state.media) is ClipStatus.EXPORTED:
            self._clips.set_status(self._pipeline.state.media, ClipStatus.READY)
        self._stage.setText("Edits saved automatically.")
        self._update_buttons()

    def _shift_selected(self, direction: int) -> None:
        if self._pipeline is None or self._runner.busy:
            return
        rows = self._selected_rows() or list(range(self._model.rowCount()))
        self._model.shift_rows(rows, direction * self._shift.value())

    def _retranslate_selected(self) -> None:
        rows = self._selected_rows()
        if self._pipeline is None or len(rows) != 1 or self._runner.busy:
            return
        row = rows[0]
        cue = self._model.cue_at(row)
        if cue is None:
            return
        before = CueState.of(cue)
        job = RetranslateJob(self._pipeline, row, self._context.text().strip())
        job.succeeded.connect(lambda position, _text: self._on_retranslated(position, before))
        job.failed.connect(self._show_error)
        self._stage.setText(f"Retranslating line {row + 1}…")
        self._runner.start(job, ("succeeded", "failed"))
        self._update_buttons()

    def _on_retranslated(self, position: int, before: CueState) -> None:
        self._model.record_external_change(position, before, f"Retranslate line {position + 1}")
        self._model.refresh_row(position)
        self._table.resizeRowToContents(position)
        self._player.refresh_caption()
        self._stage.setText(f"Line {position + 1} retranslated.")

    def _selected_versions(self) -> Cue | None:
        rows = self._selected_rows()
        cue = self._model.cue_at(rows[0]) if len(rows) == 1 else None
        return cue if cue is not None and len(cue.versions) > 1 else None

    def _choose_version(self) -> None:
        cue = self._selected_versions()
        if cue is None or self._runner.busy:
            return
        dialog = VersionsDialog(cue, self)
        if dialog.exec():
            self._model.use_version(self._selected_rows()[0], dialog.chosen())

    def _revert_edits(self) -> None:
        if self._pipeline is None or self._runner.busy:
            return
        answer = QMessageBox.question(
            self,
            "Revert edits",
            "Discard your edits and go back to the subtitles as they were generated?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        cues = self._pipeline.discard_edits()
        self._model.set_cues(cues)
        self._player.set_cues(cues)
        self._table.resizeRowsToContents()
        self._stage.setText("Edits discarded.")
        self._update_buttons()

    def _export(self, quiet: bool = False) -> None:
        if self._pipeline is None:
            return
        try:
            self._files = self._pipeline.export()
        except OSError as error:
            if quiet:
                self._notices.add(f"{self._pipeline.state.media.name}: {error}")
                self._clips.set_status(self._pipeline.state.media, ClipStatus.FAILED)
            else:
                self._show_error(str(error))
            return
        self._clips.set_status(self._pipeline.state.media, ClipStatus.EXPORTED)
        self._set_progress(1.0, f"Saved {len(self._files)} files next to the video.")
        self._update_buttons()

    def _export_video(self) -> None:
        if self._pipeline is None or self._runner.busy:
            return
        sample = self._preview_cue()
        seconds = (sample.start + sample.end) / 2 if sample else self._player.position()
        text = format_for_screen(sample.translation, self._pipeline.cue_rules) if sample else ""
        dialog = VideoStyleDialog(
            self._pipeline.state.media, seconds, text, self._settings.video.style(), self
        )
        if not dialog.exec():
            return
        style = dialog.style()
        self._settings.video.remember(style)
        self._store.save(self._settings)
        job = ExportVideoJob(self._pipeline, style)
        job.progressed.connect(
            lambda fraction: self._set_progress(
                fraction, f"Creating the subtitled video… {fraction:.0%}"
            )
        )
        job.succeeded.connect(self._on_video_exported)
        job.failed.connect(self._show_error)
        self._set_progress(0.0, "Creating the subtitled video…")
        self._runner.start(job, ("succeeded", "failed"))
        self._update_buttons()

    def _preview_cue(self) -> Cue | None:
        rows = self._selected_rows()
        cue = self._model.cue_at(rows[0]) if rows else None
        if cue is not None and cue.translation:
            return cue
        cues = self._pipeline.state.cues if self._pipeline else []
        return next((cue for cue in cues if cue.translation), None)

    def _on_video_exported(self, output: Path) -> None:
        self._files = [output]
        if self._pipeline is not None:
            self._clips.set_status(self._pipeline.state.media, ClipStatus.EXPORTED)
        self._set_progress(1.0, f"Video saved: {output.name}")

    def _show_error(self, message: str) -> None:
        self._set_progress(0.0, "Something went wrong.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Something went wrong")
        box.setText(message)
        if self._log_file is not None:
            log_folder = self._log_file.parent
            box.setInformativeText(f"Details were saved to:\n{self._log_file}")
            logs = box.addButton("Open log folder", QMessageBox.ButtonRole.ActionRole)
            logs.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_folder)))
            )
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()

    def _check_for_updates(self) -> None:
        if self._update_runner.busy:
            return
        job = UpdateCheckJob()
        job.found.connect(
            lambda release: self._show_update(release) if isinstance(release, Release) else None
        )
        self._update_runner.start(job, ("finished",))

    def _show_update(self, release: Release) -> None:
        self._release = release
        automatic = release.installer is not None and can_update_itself()
        self._banner.show_release(release.version, release.url, automatic)

    def _install_update(self) -> None:
        release = self._release
        if release is None or release.installer is None or self._update_runner.busy:
            return
        if self._is_working():
            QMessageBox.information(
                self,
                "Update",
                "ClipTranslator is still working. Wait until it finishes, "
                "or cancel it, and then click Update now.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Update",
            "ClipTranslator will close to install the update and then reopen with your "
            "clips. Your subtitle edits are saved.\n\nUpdate now?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        job = UpdateDownloadJob(release.installer)
        job.progressed.connect(
            lambda fraction: self._banner.show_progress(f"Downloading the update… {fraction:.0%}")
        )
        job.succeeded.connect(self._run_installer)
        job.failed.connect(self._on_update_failed)
        self._updating = True
        self._banner.show_progress("Downloading the update…")
        self._update_runner.start(job, ("succeeded", "failed"))
        self._update_buttons()

    def _run_installer(self, installer: Path) -> None:
        if self._is_working():
            self._on_update_failed("ClipTranslator was busy, so nothing was closed.")
            return
        self._finish_editing()
        try:
            self._session_store.save(self._current_session())
            launch_installer(installer)
        except OSError as error:
            self._session_store.path.unlink(missing_ok=True)
            self._on_update_failed(str(error))
            return
        self._banner.show_progress("Installing the update. ClipTranslator will reopen in a moment.")
        QTimer.singleShot(INSTALLER_HANDOFF_MS, self.close)

    def _is_working(self) -> bool:
        return self._runner.busy or self._queue_active

    def _finish_editing(self) -> None:
        editor = QApplication.focusWidget()
        if editor is None or editor is self._table or not self._table.isAncestorOf(editor):
            return
        self._table.commitData(editor)
        self._table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

    def _current_session(self) -> Session:
        return Session(
            clips=[
                SavedClip(str(path), (self._clips.status(path) or ClipStatus.PENDING).value)
                for path in self._clips.paths()
            ],
            current=str(self._media) if self._media else "",
            source_language=self._source.currentData() or "",
            context=self._context.text(),
        )

    def _restore_session(self) -> None:
        session = self._session_store.take()
        if session is None:
            return
        clips = [clip for clip in session.clips if Path(clip.path).is_file()]
        self._clips.add([Path(clip.path) for clip in clips])
        for clip in clips:
            self._clips.set_status(Path(clip.path), restored_status(clip.status))
        source = self._source.findData(session.source_language)
        if source >= 0:
            self._source.setCurrentIndex(source)
        self._context.setText(session.context)
        current = Path(session.current) if session.current else None
        if current is not None and current.is_file():
            self.open_media(current)
            if self._clips.status(current) in (ClipStatus.READY, ClipStatus.EXPORTED):
                QTimer.singleShot(0, self._start)
        self._stage.setText("ClipTranslator was updated. Your clips are back where you left them.")
        self._update_buttons()

    def _on_update_failed(self, message: str) -> None:
        self._updating = False
        self._banner.show_failure(message)
        self._update_buttons()

    def _open_folder(self) -> None:
        folder = self._files[0].parent if self._files else None
        if folder is None and self._media is not None:
            folder = self._media.parent
        if folder is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _open_settings(self) -> None:
        if SetupDialog(self._store, self).exec():
            self._settings = self._store.load()
            self._fill_targets()
        if self._first_run and self._settings.check_for_updates:
            self._first_run = False
            self._check_for_updates()

    def _seek_to_row(self, index: QModelIndex) -> None:
        cue = self._model.cue_at(index.row())
        if cue is not None:
            self._player.seek(cue.start)

    def _selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self._table.selectionModel().selectedRows()})

    def _set_progress(self, fraction: float, message: str) -> None:
        self._progress.setValue(int(fraction * PROGRESS_STEPS))
        self._percent.setText(f"{fraction:.0%}" if fraction > 0 else "")
        self._stage.setText(message)

    def _update_buttons(self) -> None:
        running = self._runner.busy
        processing = running and isinstance(self._runner.job, SubtitleJob)
        has_result = self._pipeline is not None
        editable = has_result and not running
        stack = self._model.undo_stack
        self._start_button.setVisible(not processing)
        self._cancel_button.setVisible(processing)
        self._cancel_button.setEnabled(processing)
        self._start_button.setEnabled(self._media is not None and not running)
        for widget in (
            self._source,
            self._target,
            self._context,
            self._settings_button,
            self._add_files_button,
            self._add_folder_button,
        ):
            widget.setEnabled(not running)
        self._process_all_button.setEnabled(
            not running and bool(self._clips.with_status(ClipStatus.PENDING))
        )
        self._clips.setEnabled(not running)
        self._undo_button.setEnabled(editable and stack.canUndo())
        self._redo_button.setEnabled(editable and stack.canRedo())
        self._undo_button.setToolTip(
            f"Undo: {stack.undoText()} (Ctrl+Z)" if stack.canUndo() else "Undo (Ctrl+Z)"
        )
        self._redo_button.setToolTip(
            f"Redo: {stack.redoText()} (Ctrl+Y)" if stack.canRedo() else "Redo (Ctrl+Y)"
        )
        for widget in (self._shift, self._earlier_button, self._later_button):
            widget.setEnabled(editable)
        self._retranslate_button.setEnabled(editable and len(self._selected_rows()) == 1)
        self._versions_button.setEnabled(editable and self._selected_versions() is not None)
        self._revert_button.setEnabled(editable and self._pipeline.state.restored_edits)
        self._export_button.setEnabled(editable)
        media_has_video = self._media is not None and has_video(self._media)
        self._export_video_button.setEnabled(editable and media_has_video)
        if self._updating:
            for widget in (
                self._start_button,
                self._process_all_button,
                self._export_video_button,
                self._settings_button,
            ):
                widget.setEnabled(False)
        self._folder_button.setEnabled(self._media is not None)
