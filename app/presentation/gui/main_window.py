from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, QObject, Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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
from app.config.store import SettingsStore
from app.domain.languages import ENGLISH_NAMES, TARGET_LANGUAGES
from app.presentation.gui.cue_table import Column, CueTableModel
from app.presentation.gui.icons import app_icon, logo_pixmap
from app.presentation.gui.job import JobRequest, RetranslateJob, SubtitleJob
from app.presentation.gui.player import SubtitledPlayer
from app.presentation.gui.setup_dialog import SetupDialog
from app.presentation.gui.texts import MEDIA_FILTER, language_name, stage_label
from app.presentation.gui.widgets import DropZone, NoticeBox, card, icon_button, section_label

WINDOW_SIZE = (1360, 860)
SIDEBAR_WIDTH = 360
PROGRESS_STEPS = 1000


class MainWindow(QMainWindow):
    def __init__(self, store: SettingsStore | None = None, log_file: Path | None = None) -> None:
        super().__init__()
        self._store = store or SettingsStore()
        self._first_run = not self._store.path.exists()
        self._settings = self._store.load()
        self._log_file = log_file
        self._media: Path | None = None
        self._pipeline: Pipeline | None = None
        self._thread: QThread | None = None
        self._job: QObject | None = None
        self._files: list[Path] = []
        self._model = CueTableModel()
        self._player = SubtitledPlayer()
        self._drop_zone = DropZone()
        self._settings_button = icon_button("Settings", "settings", "ghost")
        self._source = QComboBox()
        self._target = QComboBox()
        self._context = QLineEdit()
        self._start_button = icon_button("Generate subtitles", "sparkles", "primary")
        self._cancel_button = icon_button("Cancel", "stop", "danger")
        self._progress = QProgressBar()
        self._stage = QLabel("Choose a file to start.")
        self._percent = QLabel("")
        self._notices = NoticeBox()
        self._table = QTableView()
        self._summary = QLabel("Subtitles will appear here.")
        self._show_original = QCheckBox("Original on video")
        self._retranslate_button = icon_button("Retranslate line", "refresh")
        self._folder_button = icon_button("", "folder")
        self._export_button = icon_button("Export", "download", "primary")
        self._build()

    def open_media(self, media: Path) -> None:
        if not media.is_file() or self._thread is not None:
            return
        self._media = media
        self._pipeline = None
        self._files = []
        self._model.set_cues([])
        self._player.set_cues([])
        self._player.load(media)
        self._drop_zone.show_file(media)
        self._notices.clear()
        self._set_progress(0.0, "Ready to generate subtitles.")
        self._summary.setText("Subtitles will appear here.")
        self._update_buttons()

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
        layout.setSpacing(18)
        layout.addLayout(self._header())
        body = QHBoxLayout()
        body.setSpacing(20)
        body.addWidget(self._sidebar())
        body.addWidget(self._workspace(), stretch=1)
        layout.addLayout(body, stretch=1)
        self.setCentralWidget(root)
        self._update_buttons()
        if self._first_run:
            QTimer.singleShot(0, self._open_settings)

    def _configure_widgets(self) -> None:
        self._fill_languages()
        self._context.setPlaceholderText("Optional: what happens in the clip, names…")
        self._progress.setRange(0, PROGRESS_STEPS)
        self._progress.setTextVisible(False)
        self._percent.setObjectName("percent")
        self._stage.setObjectName("muted")
        self._stage.setWordWrap(True)
        self._summary.setObjectName("muted")
        self._folder_button.setToolTip("Open the output folder")
        self._retranslate_button.setToolTip("Translate the selected line again")
        self._cancel_button.hide()
        self._table.setModel(self._model)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setWordWrap(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
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
        layout.setSpacing(16)
        layout.addWidget(self._drop_zone)
        layout.addWidget(card(section_label("Languages"), options))
        layout.addWidget(card(buttons, progress_row, self._stage, spacing=10))
        layout.addWidget(self._notices)
        layout.addStretch(1)
        return sidebar

    def _workspace(self) -> QWidget:
        toolbar = QHBoxLayout()
        toolbar.addWidget(section_label("Subtitles"))
        toolbar.addSpacing(8)
        toolbar.addWidget(self._summary, stretch=1)
        toolbar.addWidget(self._show_original)
        toolbar.addWidget(self._retranslate_button)
        toolbar.addWidget(self._folder_button)
        toolbar.addWidget(self._export_button)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(16)
        splitter.addWidget(card(self._player))
        splitter.addWidget(card(toolbar, self._table))
        splitter.setSizes([460, 360])
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
        self._drop_zone.file_dropped.connect(self.open_media)
        self._drop_zone.browse_requested.connect(self._choose_file)
        self._settings_button.clicked.connect(self._open_settings)
        self._start_button.clicked.connect(self._start)
        self._cancel_button.clicked.connect(self._cancel)
        self._export_button.clicked.connect(self._export)
        self._folder_button.clicked.connect(self._open_folder)
        self._retranslate_button.clicked.connect(self._retranslate_selected)
        self._show_original.toggled.connect(self._player.show_original)
        self._table.clicked.connect(self._seek_to_row)
        self._model.dataChanged.connect(lambda *_: self._player.refresh_caption())
        self._table.selectionModel().selectionChanged.connect(lambda *_: self._update_buttons())

    def _choose_file(self) -> None:
        if self._thread is not None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open file", "", MEDIA_FILTER)
        if path:
            self.open_media(Path(path))

    def _start(self) -> None:
        if self._media is None or self._thread is not None:
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
        job.cancelled.connect(lambda: self._set_progress(0.0, "Cancelled."))
        job.failed.connect(self._show_error)
        self._notices.clear()
        self._set_progress(0.0, "Starting…")
        self._run_in_background(job)

    def _cancel(self) -> None:
        if isinstance(self._job, SubtitleJob):
            self._job.cancel()
            self._cancel_button.setEnabled(False)
            self._stage.setText("Cancelling after the current step…")

    def _retranslate_selected(self) -> None:
        row = self._selected_row()
        if self._pipeline is None or row is None or self._thread is not None:
            return
        job = RetranslateJob(self._pipeline, row, self._context.text().strip())
        job.succeeded.connect(self._on_retranslated)
        job.failed.connect(self._show_error)
        self._stage.setText(f"Retranslating line {row + 1}…")
        self._run_in_background(job)

    def _run_in_background(self, job: QObject) -> None:
        thread = QThread(self)
        job.moveToThread(thread)
        thread.started.connect(job.run)
        for signal_name in ("succeeded", "failed", "cancelled"):
            signal = getattr(job, signal_name, None)
            if signal is not None:
                signal.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)
        self._thread, self._job = thread, job
        thread.start()
        self._update_buttons()

    def _on_progress(self, overall: float, stage: str) -> None:
        self._set_progress(overall, f"{stage_label(stage)}…")

    def _on_success(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline
        cues = pipeline.state.cues
        self._model.set_cues(cues)
        self._player.set_cues(cues)
        flagged = sum(1 for cue in cues if cue.flags)
        self._set_progress(1.0, "Done. Click a line to preview it, edit any text, then export.")
        self._summary.setText(f"{len(cues)} lines · {flagged} to review")
        for warning in pipeline.state.warnings:
            self._notices.add(warning)
        self._table.resizeRowsToContents()

    def _on_retranslated(self, position: int, text: str) -> None:
        self._model.refresh_row(position)
        self._table.resizeRowToContents(position)
        self._player.refresh_caption()
        self._stage.setText(f"Line {position + 1} retranslated.")

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

    def _on_thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        if self._job is not None:
            self._job.deleteLater()
        self._thread = None
        self._job = None
        self._update_buttons()

    def _export(self) -> None:
        if self._pipeline is None:
            return
        try:
            self._files = self._pipeline.export()
        except OSError as error:
            self._show_error(str(error))
            return
        self._stage.setText(f"Saved {len(self._files)} files next to the video.")
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

    def _seek_to_row(self, index: QModelIndex) -> None:
        cue = self._model.cue_at(index.row())
        if cue is not None:
            self._player.seek(cue.start)

    def _selected_row(self) -> int | None:
        rows = self._table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _set_progress(self, fraction: float, message: str) -> None:
        self._progress.setValue(int(fraction * PROGRESS_STEPS))
        self._percent.setText(f"{fraction:.0%}" if fraction > 0 else "")
        self._stage.setText(message)

    def _update_buttons(self) -> None:
        running = self._thread is not None
        processing = running and isinstance(self._job, SubtitleJob)
        has_result = self._pipeline is not None
        self._start_button.setVisible(not processing)
        self._cancel_button.setVisible(processing)
        self._cancel_button.setEnabled(processing)
        self._start_button.setEnabled(self._media is not None and not running)
        for widget in (self._source, self._target, self._context, self._settings_button):
            widget.setEnabled(not running)
        self._drop_zone.setEnabled(not running)
        self._export_button.setEnabled(has_result and not running)
        self._retranslate_button.setEnabled(
            has_result and not running and self._selected_row() is not None
        )
        self._folder_button.setEnabled(self._media is not None)
