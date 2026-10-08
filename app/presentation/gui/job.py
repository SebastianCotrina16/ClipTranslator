from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.application.pipeline import Pipeline, Stage
from app.application.updates import Installer, newer_release
from app.bootstrap import create_pipeline
from app.config.settings import Settings
from app.domain.audio_leveling import Leveling
from app.domain.subtitle_style import SubtitleStyle
from app.infrastructure.ffmpeg import render_video
from app.infrastructure.github_releases import GitHubReleases, installed_version
from app.infrastructure.gpu import sustained_utilization
from app.infrastructure.self_update import download_installer
from app.infrastructure.subtitle_files import video_name

log = logging.getLogger(__name__)

BUSY_GPU_PERCENT = 50
MUSIC_REMOVAL_SHARE = 0.5
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


class JobCancelledError(Exception):
    pass


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
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, request: JobRequest, settings: Settings) -> None:
        super().__init__()
        self._request = request
        self._settings = settings
        self._cancel = threading.Event()
        self._owner: threading.Thread | None = None

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        self._owner = threading.current_thread()
        try:
            self._warn_if_gpu_busy()
            pipeline = create_pipeline(self._request.media, self._settings, self._report)
            self._process(pipeline)
        except JobCancelledError:
            self.cancelled.emit()
            return
        except Exception as error:
            log.exception("Subtitle job failed for %s", self._request.media)
            self.failed.emit(str(error))
            return
        self.succeeded.emit(pipeline)

    def _process(self, pipeline: Pipeline) -> None:
        steps = [
            pipeline.isolate_speech,
            self._resolve_language(pipeline),
            pipeline.transcribe,
            lambda: pipeline.translate(self._request.clip_context),
            pipeline.build_cues,
        ]
        for step in steps:
            self._stop_if_cancelled()
            step()

    def _resolve_language(self, pipeline: Pipeline):
        def resolve() -> None:
            if self._request.source_language:
                pipeline.set_language(self._request.source_language)
                return
            detection = pipeline.detect_language()
            self.language_detected.emit(detection.language, detection.probability)

        return resolve

    def _stop_if_cancelled(self) -> None:
        if self._cancel.is_set():
            raise JobCancelledError

    def _warn_if_gpu_busy(self) -> None:
        busy = sustained_utilization()
        if busy is not None and busy >= BUSY_GPU_PERCENT:
            self.busy_gpu.emit(busy)

    def _report(self, stage: str, fraction: float, message: str) -> None:
        self.progressed.emit(overall_progress(stage, fraction), stage)
        if threading.current_thread() is self._owner:
            self._stop_if_cancelled()


class RetranslateJob(QObject):
    succeeded = Signal(int, str)
    failed = Signal(str)

    def __init__(self, pipeline: Pipeline, position: int, clip_context: str) -> None:
        super().__init__()
        self._pipeline = pipeline
        self._position = position
        self._clip_context = clip_context

    @Slot()
    def run(self) -> None:
        try:
            text = self._pipeline.retranslate_cue(self._position, self._clip_context)
        except Exception as error:
            log.exception("Retranslating line %d failed", self._position + 1)
            self.failed.emit(str(error))
            return
        self.succeeded.emit(self._position, text)


class ExportVideoJob(QObject):
    progressed = Signal(float)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        pipeline: Pipeline,
        style: SubtitleStyle | None,
        remove_music: bool = False,
        leveling: Leveling | None = None,
    ) -> None:
        super().__init__()
        self._pipeline = pipeline
        self._style = style
        self._remove_music = remove_music
        self._leveling = leveling

    @Slot()
    def run(self) -> None:
        try:
            media = self._pipeline.state.media
            subtitled, leveled = self._style is not None, self._leveling is not None
            name = video_name(media, subtitled, self._remove_music, leveled)
            output = media.with_name(name)
            subtitles = self._pipeline.export(extras=False)[0] if self._style is not None else None
            audio = None
            start = 0.0
            if self._remove_music:
                start = MUSIC_REMOVAL_SHARE
                audio = self._pipeline.voice_audio(
                    lambda fraction: self.progressed.emit(start * fraction)
                )
            render_video(
                media,
                output,
                subtitles,
                self._style,
                audio,
                self._pipeline.state.duration,
                lambda fraction: self.progressed.emit(start + (1.0 - start) * fraction),
                self._leveling,
            )
        except Exception as error:
            log.exception("Exporting the video failed")
            self.failed.emit(str(error))
            return
        self.succeeded.emit(output)


class UpdateDownloadJob(QObject):
    progressed = Signal(float)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, installer: Installer) -> None:
        super().__init__()
        self._installer = installer

    @Slot()
    def run(self) -> None:
        try:
            path = download_installer(self._installer, progress=self.progressed.emit)
        except Exception as error:
            log.exception("Downloading the update failed")
            self.failed.emit(str(error))
            return
        self.succeeded.emit(path)


class UpdateCheckJob(QObject):
    found = Signal(object)
    finished = Signal()

    @Slot()
    def run(self) -> None:
        try:
            release = newer_release(installed_version(), GitHubReleases())
            if release is not None:
                self.found.emit(release)
        except Exception:
            log.exception("Update check failed")
        self.finished.emit()
