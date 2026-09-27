from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from app.application.setup_advisor import (
    TRANSLATION_MODELS,
    WHISPER_MODELS,
    Recommendation,
    SetupPlan,
    SystemReport,
    pending_download_gb,
    plan_from,
    recommend,
)
from app.config.setup import apply_plan
from app.config.store import SettingsStore, data_dir
from app.domain.languages import TARGET_LANGUAGES
from app.infrastructure import setup_tasks
from app.infrastructure.system_probe import scan
from app.presentation.gui.background import BackgroundRunner
from app.presentation.gui.texts import language_name

PROGRESS_STEPS = 1000
API_ENGINES = {"anthropic": "Anthropic API", "openai": "OpenAI-compatible API"}


class ScanTask(QObject):
    finished = Signal(object, object)
    failed = Signal(str)

    def __init__(self, ollama_url: str) -> None:
        super().__init__()
        self._ollama_url = ollama_url

    @Slot()
    def run(self) -> None:
        try:
            report = scan(data_dir(), self._ollama_url)
            self.finished.emit(report, recommend(report))
        except Exception as error:
            self.failed.emit(str(error))


class InstallTask(QObject):
    progressed = Signal(float, str)
    finished = Signal(object, object)
    failed = Signal(str)

    def __init__(
        self, plan: SetupPlan, ollama_url: str, isolation_model: str, install_ollama: bool
    ) -> None:
        super().__init__()
        self._plan = plan
        self._ollama_url = ollama_url
        self._isolation_model = isolation_model
        self._install_ollama = install_ollama

    @Slot()
    def run(self) -> None:
        try:
            result = self._install()
        except Exception as error:
            self.failed.emit(str(error))
            return
        self.finished.emit(replace(self._plan, compute_type=result.compute_type), result)

    def _install(self) -> setup_tasks.SelfTestResult:
        plan = self._plan
        self.progressed.emit(-1, "Downloading the transcription model…")
        setup_tasks.download_transcription_model(plan.whisper_model)
        if plan.voice_isolation:
            setup_tasks.download_isolation_model(
                self._isolation_model,
                lambda f: self.progressed.emit(f, "Downloading the voice isolation model…"),
            )
        if plan.uses_ollama:
            if self._install_ollama:
                self.progressed.emit(-1, "Installing Ollama…")
                setup_tasks.install_ollama()
            self.progressed.emit(-1, "Starting Ollama…")
            setup_tasks.start_ollama(self._ollama_url)
            setup_tasks.pull_translation_model(
                plan.translation_model,
                self._ollama_url,
                lambda f, status: self.progressed.emit(
                    f, f"Downloading the translation model ({status})…"
                ),
            )
        self.progressed.emit(-1, "Testing transcription on this computer…")
        return setup_tasks.run_speech_self_test(plan.whisper_model, plan.device, plan.compute_type)


class SetupDialog(QDialog):
    def __init__(self, store: SettingsStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._settings = store.load()
        self._report: SystemReport | None = None
        self._recommendation: Recommendation | None = None
        self._runner = BackgroundRunner(self)
        self._hardware = QLabel("Checking your computer…")
        self._profile = QLabel()
        self._warnings = QLabel()
        self._whisper = QComboBox()
        self._isolation = QCheckBox("Remove music and background noise before transcribing")
        self._low_impact = QCheckBox(
            "Keep the computer responsive while working (uses fewer CPU cores)"
        )
        self._target = QComboBox()
        self._engine = QComboBox()
        self._api_model = QLineEdit()
        self._api_key = QLineEdit()
        self._api_url = QLineEdit(self._settings.translation.openai_base_url)
        self._download = QLabel()
        self._progress = QProgressBar()
        self._status = QLabel()
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self._build()

    def showEvent(self, event: object) -> None:
        super().showEvent(event)
        if self._report is None and not self._runner.busy:
            self._start(ScanTask(self._settings.translation.ollama_url), self._on_scanned)

    def reject(self) -> None:
        if not self._runner.busy:
            super().reject()

    def _build(self) -> None:
        self.setWindowTitle("ClipTranslator settings")
        self.setMinimumWidth(640)
        self._hardware.setWordWrap(True)
        self._hardware.setObjectName("muted")
        self._profile.setWordWrap(True)
        self._profile.setTextFormat(Qt.TextFormat.RichText)
        self._warnings.setWordWrap(True)
        self._warnings.setStyleSheet("color: #b8860b;")
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("Leave empty to use the environment variable")
        self._progress.setRange(0, PROGRESS_STEPS)
        self._progress.setTextVisible(False)
        self._buttons.button(QDialogButtonBox.StandardButton.Save).setText("Install and save")
        self._buttons.accepted.connect(self._install)
        self._buttons.rejected.connect(self.reject)
        for code in TARGET_LANGUAGES:
            self._target.addItem(language_name(code), code)
        current = self._settings.translation.target_language
        if self._target.findData(current) < 0:
            self._target.addItem(language_name(current), current)
        self._target.setCurrentIndex(self._target.findData(current))
        form = QFormLayout()
        form.addRow("Transcription", self._whisper)
        form.addRow("", self._isolation)
        form.addRow("", self._low_impact)
        form.addRow("Translate to", self._target)
        form.addRow("Translation engine", self._engine)
        form.addRow("API model", self._api_model)
        form.addRow("API key", self._api_key)
        form.addRow("API address", self._api_url)
        self._form = form
        layout = QVBoxLayout(self)
        layout.addWidget(self._profile)
        layout.addWidget(self._hardware)
        layout.addWidget(self._warnings)
        layout.addLayout(form)
        layout.addWidget(self._download)
        layout.addWidget(self._progress)
        layout.addWidget(self._status)
        layout.addWidget(self._buttons)
        for widget in (self._whisper, self._engine):
            widget.currentIndexChanged.connect(self._refresh)
        self._isolation.toggled.connect(self._refresh)
        self._set_editable(False)
        self._refresh()

    def _on_scanned(self, report: SystemReport, recommendation: Recommendation) -> None:
        self._report = report
        self._recommendation = recommendation
        self._profile.setText(f"<b>{recommendation.tier}</b><br>{recommendation.summary}")
        self._hardware.setText(self._describe(report))
        self._warnings.setText("\n".join(recommendation.warnings))
        for option in WHISPER_MODELS:
            tag = "  (recommended)" if option.key == recommendation.whisper_model else ""
            self._whisper.addItem(
                f"{option.label}, {option.size_gb:.1f} GB: {option.note}{tag}", option.key
            )
        self._whisper.setCurrentIndex(self._whisper.findData(recommendation.whisper_model))
        for option in TRANSLATION_MODELS:
            tag = "  (recommended)" if option.key == recommendation.translation_model else ""
            fit = recommendation.fits[option.key]
            self._engine.addItem(
                f"Ollama {option.label}, {option.size_gb:.1f} GB: {fit}{tag}", option.key
            )
        for backend, label in API_ENGINES.items():
            self._engine.addItem(label, backend)
        self._engine.setCurrentIndex(self._engine.findData(recommendation.translation_model))
        self._isolation.setChecked(recommendation.separation)
        self._low_impact.setChecked(
            self._settings.performance.low_impact and recommendation.low_impact
        )
        self._status.setText("")
        self._set_editable(True)
        self._refresh()

    @staticmethod
    def _describe(report: SystemReport) -> str:
        gpu = f"{report.gpu.name} ({report.vram_gb:.0f} GB)" if report.gpu else "no NVIDIA GPU"
        ollama = (
            "running"
            if report.ollama_running
            else ("installed" if report.ollama_installed else "not installed")
        )
        return (
            f"CPU: {report.cpu} · RAM: {report.ram_gb:.0f} GB · GPU: {gpu} · "
            f"Free disk: {report.disk_free_gb:.0f} GB · Ollama: {ollama}"
        )

    def _plan(self) -> SetupPlan | None:
        if self._recommendation is None:
            return None
        plan = plan_from(self._recommendation, self._target.currentData())
        plan.whisper_model = self._whisper.currentData() or plan.whisper_model
        plan.voice_isolation = self._isolation.isChecked()
        plan.low_impact = self._low_impact.isChecked()
        engine = self._engine.currentData()
        if engine in API_ENGINES:
            plan.backend = engine
            plan.api_model = self._api_model.text().strip()
            plan.api_key = self._api_key.text().strip()
            plan.api_base_url = self._api_url.text().strip()
        elif engine:
            plan.translation_model = engine
        return plan

    def _refresh(self) -> None:
        api_engine = self._engine.currentData() in API_ENGINES
        for widget in (self._api_model, self._api_key):
            self._form.setRowVisible(widget, api_engine)
        self._form.setRowVisible(self._api_url, self._engine.currentData() == "openai")
        plan = self._plan()
        if plan is None or self._report is None:
            self._download.setText("")
            return
        size = pending_download_gb(
            plan,
            setup_tasks.whisper_ready(plan.whisper_model),
            setup_tasks.isolation_ready(self._settings.separation.model),
            self._report.ollama_models,
        )
        self._download.setText(
            f"Download needed: about {size:.1f} GB (free: {self._report.disk_free_gb:.0f} GB)."
        )

    def _install(self) -> None:
        plan = self._plan()
        if plan is None or self._report is None:
            return
        if not plan.uses_ollama and not plan.api_model:
            QMessageBox.warning(self, "Missing model", "Enter the API model name.")
            return
        install_ollama = plan.uses_ollama and not self._report.ollama_installed
        if install_ollama and not self._confirm_ollama_install():
            return
        task = InstallTask(
            plan,
            self._settings.translation.ollama_url,
            self._settings.separation.model,
            install_ollama,
        )
        task.progressed.connect(self._on_progress)
        self._set_editable(False)
        self._start(task, self._on_installed)

    def _confirm_ollama_install(self) -> bool:
        answer = QMessageBox.question(
            self,
            "Install Ollama",
            "Ollama runs the local translator and is not installed. Install it now with winget?",
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_progress(self, fraction: float, message: str) -> None:
        if fraction < 0:
            self._progress.setRange(0, 0)
        else:
            self._progress.setRange(0, PROGRESS_STEPS)
            self._progress.setValue(int(fraction * PROGRESS_STEPS))
        self._status.setText(message)

    def _on_installed(self, plan: SetupPlan, result: setup_tasks.SelfTestResult) -> None:
        self._store.save(apply_plan(self._settings, plan))
        self._progress.setRange(0, PROGRESS_STEPS)
        self._progress.setValue(PROGRESS_STEPS)
        speed = (
            f" Transcription runs at about {result.speed:.0f}x real time." if result.speed else ""
        )
        QMessageBox.information(self, "Ready", f"Settings saved.{speed}")
        self.accept()

    def _on_failure(self, message: str) -> None:
        self._progress.setRange(0, PROGRESS_STEPS)
        self._progress.setValue(0)
        self._status.setText("")
        self._set_editable(self._recommendation is not None)
        QMessageBox.critical(self, "Something went wrong", message)

    def _set_editable(self, editable: bool) -> None:
        for widget in (
            self._whisper,
            self._isolation,
            self._low_impact,
            self._target,
            self._engine,
            self._api_model,
            self._api_key,
            self._api_url,
        ):
            widget.setEnabled(editable)
        self._buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(editable)

    def _start(self, task: QObject, on_finished: object) -> None:
        task.finished.connect(on_finished)
        task.failed.connect(self._on_failure)
        self._runner.start(task, ("finished", "failed"))
