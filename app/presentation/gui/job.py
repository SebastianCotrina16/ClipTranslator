from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.application.pipeline import Pipeline, Stage
from app.bootstrap import create_pipeline
from app.config.settings import Settings
from app.infrastructure.gpu import sustained_utilization

BUSY_GPU_PERCENT = 50
STAGE_ORDER = [
    Stage.AUDIO,
    Stage.SEPARATION,
    Stage.LANGUAGE,
    Stage.TRANSCRIPTION,
    Stage.UNITS,
    Stage.REVIEW,
    Stage.TRANSLATION,
    Stage.CUES,
]


@dataclass(frozen=True)
class JobRequest:
    media: Path
    source_language: str | None
    clip_context: str


def overall_progress(stage: str, fraction: float) -> float:
    try:
        index = STAGE_ORDER.index(Stage(stage))
    except ValueError:
        return 1.0
    return (index + min(max(fraction, 0.0), 1.0)) / len(STAGE_ORDER)


class SubtitleJob(QObject):
    progressed = Signal(float, str)
    busy_gpu = Signal(int)
    language_detected = Signal(str, float)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, request: JobRequest, settings: Settings) -> None:
        super().__init__()
        self._request = request
        self._settings = settings

    @Slot()
    def run(self) -> None:
        try:
            self._warn_if_gpu_busy()
            pipeline = create_pipeline(self._request.media, self._settings, self._report)
            self._process(pipeline)
        except Exception as error:
            self.failed.emit(str(error))
            return
        self.succeeded.emit(pipeline)

    def _process(self, pipeline: Pipeline) -> None:
        pipeline.isolate_speech()
        if self._request.source_language:
            pipeline.set_language(self._request.source_language)
        else:
            detection = pipeline.detect_language()
            self.language_detected.emit(detection.language, detection.probability)
        pipeline.transcribe()
        pipeline.translate(self._request.clip_context)
        pipeline.build_cues()

    def _warn_if_gpu_busy(self) -> None:
        busy = sustained_utilization()
        if busy is not None and busy >= BUSY_GPU_PERCENT:
            self.busy_gpu.emit(busy)

    def _report(self, stage: str, fraction: float, message: str) -> None:
        self.progressed.emit(overall_progress(stage, fraction), stage)
