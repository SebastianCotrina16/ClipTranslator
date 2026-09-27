from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
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
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.application.pipeline import Pipeline
from app.config.store import SettingsStore
from app.domain.languages import ENGLISH_NAMES, TARGET_LANGUAGES
from app.presentation.gui.cue_table import Column, CueTableModel
from app.presentation.gui.job import JobRequest, SubtitleJob
from app.presentation.gui.player import SubtitledPlayer
from app.presentation.gui.setup_dialog import SetupDialog
from app.presentation.gui.texts import MEDIA_FILTER, language_name, stage_label

WINDOW_SIZE = (1280, 800)
PROGRESS_STEPS = 1000


class MainWindow(QMainWindow):
    def __init__(self, store: SettingsStore | None = None) -> None:
        super().__init__()
        self._store = store or SettingsStore()
        self._first_run = not self._store.path.exists()
        self._settings = self._store.load()
        self._media: Path | None = None
        self._pipeline: Pipeline | None = None
        self._thread: QThread | None = None
        self._job: SubtitleJob | None = None
        self._files: list[Path] = []
        self._model = CueTableModel()
        self._player = SubtitledPlayer()
        self._file_label = QLabel("Drop a video or audio file here")
        self._open_button = QPushButton("Open file…")
        self._settings_button = QPushButton("Settings…")
        self._source = QComboBox()
        self._target = QComboBox()
        self._context = QLineEdit()
        self._start_button = QPushButton("Generate subtitles")
        self._progress = QProgressBar()
        self._status = QLabel("Choose a file to start.")
        self._warnings = QLabel()
        self._table = QTableView()
        self._show_original = QCheckBox("Show original on video")
        self._export_button = QPushButton("Export subtitles")
        self._folder_button = QPushButton("Open folder")
        self._build()

    def open_media(self, media: Path) -> None:
        if not media.is_file():
            return
        self._media = media
        self._pipeline = None
        self._model.set_cues([])
        self._player.set_cues([])
        self._player.load(media)
        self._file_label.setText(f"File: {media.name}")
        self._status.setText("")
        self._warnings.clear()
        self._update_buttons()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_media(Path(url.toLocalFile()))
                return

    def _build(self) -> None:
        self.setWindowTitle("ClipTranslator")
        self.resize(*WINDOW_SIZE)
        self.setAcceptDrops(True)
        self._fill_language_choices()
        self._context.setPlaceholderText("Optional: what happens in the clip, names…")
        self._progress.setRange(0, PROGRESS_STEPS)
        self._progress.setTextVisible(False)
        self._warnings.setWordWrap(True)
        self._warnings.setStyleSheet("color: #b8860b;")
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setWordWrap(True)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        for column in (Column.NUMBER, Column.START, Column.END):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(Column.ORIGINAL, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(Column.TRANSLATION, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(Column.FLAGS, QHeaderView.ResizeMode.ResizeToContents)
        self._connect_signals()
        self.setCentralWidget(self._layout())
        self._update_buttons()
        if self._first_run:
            QTimer.singleShot(0, self._open_settings)

    def _layout(self) -> QWidget:
        file_row = QHBoxLayout()
        file_row.addWidget(self._open_button)
        file_row.addWidget(self._file_label, stretch=1)
        file_row.addWidget(self._settings_button)
        options = QFormLayout()
        options.addRow("Source language", self._source)
        options.addRow("Translate to", self._target)
        options.addRow("Context", self._context)
        run_row = QHBoxLayout()
        run_row.addWidget(self._start_button)
        run_row.addWidget(self._progress, stretch=1)
        results = QWidget()
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.addWidget(self._table, stretch=1)
        export_row = QHBoxLayout()
        export_row.addWidget(self._show_original)
        export_row.addStretch(1)
        export_row.addWidget(self._folder_button)
        export_row.addWidget(self._export_button)
        results_layout.addLayout(export_row)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._player)
        splitter.addWidget(results)
        splitter.setSizes([560, 720])
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addLayout(file_row)
        layout.addLayout(options)
        layout.addLayout(run_row)
        layout.addWidget(self._status)
        layout.addWidget(self._warnings)
        layout.addWidget(splitter, stretch=1)
        return root

    def _fill_language_choices(self) -> None:
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
        self._open_button.clicked.connect(self._choose_file)
        self._settings_button.clicked.connect(self._open_settings)
        self._start_button.clicked.connect(self._start)
        self._export_button.clicked.connect(self._export)
        self._folder_button.clicked.connect(self._open_folder)
        self._show_original.toggled.connect(self._player.show_original)
        self._table.clicked.connect(self._seek_to_row)
        self._model.dataChanged.connect(lambda *_: self._player.refresh_caption())

    def _choose_file(self) -> None:
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
        self._job = SubtitleJob(request, self._settings)
        self._thread = QThread(self)
        self._job.moveToThread(self._thread)
        self._thread.started.connect(self._job.run)
        self._job.progressed.connect(self._on_progress)
        self._job.busy_gpu.connect(
            lambda percent: self._add_warning(
                f"The GPU is at {percent}% because of another program (a game?). It will be slower."
            )
        )
        self._job.language_detected.connect(self._on_language_detected)
        self._job.succeeded.connect(self._on_success)
        self._job.failed.connect(self._on_failure)
        self._job.succeeded.connect(self._thread.quit)
        self._job.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._on_thread_finished)
        self._warnings.clear()
        self._progress.setValue(0)
        self._thread.start()
        self._update_buttons()

    def _on_progress(self, overall: float, stage: str) -> None:
        self._progress.setValue(int(overall * PROGRESS_STEPS))
        self._status.setText(stage_label(stage))

    def _on_language_detected(self, language: str, probability: float) -> None:
        self._add_warning(f"Detected language: {language_name(language)} ({probability:.0%})")

    def _on_success(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline
        cues = pipeline.state.cues
        self._model.set_cues(cues)
        self._player.set_cues(cues)
        self._progress.setValue(PROGRESS_STEPS)
        flagged = sum(1 for cue in cues if cue.flags)
        self._status.setText(
            f"{len(cues)} subtitles, {flagged} to review. You can edit the text in the table."
        )
        for warning in pipeline.state.warnings:
            self._add_warning(warning)
        self._table.resizeRowsToContents()

    def _on_failure(self, message: str) -> None:
        self._progress.setValue(0)
        self._status.setText("")
        QMessageBox.critical(self, "Something went wrong", message)

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
            QMessageBox.critical(self, "Something went wrong", str(error))
            return
        self._status.setText(f"Saved to {self._files[0].parent}")
        self._update_buttons()

    def _open_folder(self) -> None:
        folder = self._files[0].parent if self._files else self._media and self._media.parent
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _seek_to_row(self, index: QModelIndex) -> None:
        cue = self._model.cue_at(index.row())
        if cue is not None:
            self._player.seek(cue.start)

    def _add_warning(self, message: str) -> None:
        current = self._warnings.text()
        self._warnings.setText(f"{current}\n{message}" if current else message)

    def _update_buttons(self) -> None:
        running = self._thread is not None
        self._start_button.setEnabled(self._media is not None and not running)
        self._open_button.setEnabled(not running)
        self._settings_button.setEnabled(not running)
        self._export_button.setEnabled(self._pipeline is not None and not running)
        self._folder_button.setEnabled(self._media is not None)

    def _open_settings(self) -> None:
        if SetupDialog(self._store, self).exec():
            self._settings = self._store.load()
            self._fill_targets()
