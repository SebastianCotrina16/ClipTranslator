from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.application.pipeline import Pipeline, Stage
from app.application.updates import Installer, newer_release
from app.bootstrap import SharedModels, create_pipeline
from app.config.settings import Settings
from app.domain.audio_leveling import Leveling
from app.domain.screen_prompts import PromptStyle
from app.domain.subtitle_style import SubtitleStyle
from app.infrastructure.ffmpeg import render_video
from app.infrastructure.github_releases import GitHubReleases, installed_version
from app.infrastructure.gpu import sustained_utilization
from app.infrastructure.prompt_renderer import PromptRenderer
from app.infrastructure.self_update import download_installer
from app.infrastructure.subtitle_files import video_name

log = logging.getLogger(__name__)

BUSY_GPU_PERCENT = 50
MUSIC_REMOVAL_WEIGHT = 1.0
PROMPT_SCAN_WEIGHT = 0.6
PREPARE_STAGES = [Stage.AUDIO, Stage.SEPARATION, Stage.LANGUAGE, Stage.TRANSCRIPTION]
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


@dataclass(frozen=True)
class VideoOptions:
    style: SubtitleStyle | None
    remove_music: bool = False
    leveling: Leveling | None = None
    prompts: PromptStyle | None = None


def export_shares(options: VideoOptions) -> dict[str, tuple[float, float]]:
    weights = {
        "prompts": PROMPT_SCAN_WEIGHT if options.prompts is not None else 0.0,
        "music": MUSIC_REMOVAL_WEIGHT if options.remove_music else 0.0,
        "video": 1.0,
    }
    total = sum(weights.values())
    shares, start = {}, 0.0
    for step, weight in weights.items():
        shares[step] = (start / total, weight / total)
        start += weight
    return shares


def render_clip_video(
    pipeline: Pipeline, options: VideoOptions, progress: Callable[[float], None]
) -> Path:
    media = pipeline.state.media
    subtitled, leveled = options.style is not None, options.leveling is not None
    prompts = options.prompts is not None
    output = media.with_name(video_name(media, subtitled, options.remove_music, leveled, prompts))
    subtitles = pipeline.export(extras=False)[0] if subtitled else None
    shares = export_shares(options)

    def reporter(step: str) -> Callable[[float], None]:
        start, share = shares[step]
        return lambda fraction: progress(start + share * fraction)

    frame_filter = None
    if options.prompts is not None:
        scan = pipeline.read_screen_prompts(reporter("prompts"))
        translations = pipeline.translate_screen_prompts(scan)
        renderer = PromptRenderer(
            scan.detections, scan.templates, translations, scan.fps, options.prompts
        )
        frame_filter = renderer.apply if renderer.active else None
    audio = pipeline.voice_audio(reporter("music")) if options.remove_music else None
    render_video(
        media,
        output,
        subtitles,
        options.style,
        audio,
        pipeline.state.duration,
        reporter("video"),
        options.leveling,
        frame_filter,
    )
    return output


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

    def __init__(
        self, request: JobRequest, settings: Settings, shared: SharedModels | None = None
    ) -> None:
        super().__init__()
        self._request = request
        self._settings = settings
        self._shared = shared
        self._cancel = threading.Event()
        self._owner: threading.Thread | None = None

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        self._owner = threading.current_thread()
        try:
            self._warn_if_gpu_busy()
            pipeline = create_pipeline(
                self._request.media, self._settings, self._report, shared=self._shared
            )
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
            chosen = pipeline.state.language or detection.language
            self.language_detected.emit(
                chosen, dict(detection.top).get(chosen, detection.probability)
            )

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


class PrepareJob(QObject):
    progressed = Signal(float, str)
    clip_started = Signal(object)
    clip_prepared = Signal(object)
    clip_failed = Signal(object, str)
    language_detected = Signal(str, float)
    succeeded = Signal()
    cancelled = Signal()

    def __init__(
        self, requests: list[JobRequest], settings: Settings, shared: SharedModels
    ) -> None:
        super().__init__()
        self._requests = requests
        self._settings = settings
        self._shared = shared
        self._cancel = threading.Event()
        self._number = 0

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        try:
            for number, request in enumerate(self._requests):
                self._number = number
                if self._cancel.is_set():
                    raise JobCancelledError
                self.clip_started.emit(request.media)
                try:
                    self._prepare(request)
                except JobCancelledError:
                    raise
                except Exception as error:
                    log.exception("Preparing %s failed", request.media)
                    self.clip_failed.emit(request.media, str(error))
                    continue
                self.clip_prepared.emit(request.media)
        except JobCancelledError:
            self._shared.release()
            self.cancelled.emit()
            return
        self._shared.release_transcriber()
        self.succeeded.emit()

    def _prepare(self, request: JobRequest) -> None:
        pipeline = create_pipeline(request.media, self._settings, self._report, shared=self._shared)
        pipeline.isolate_speech()
        if request.source_language:
            pipeline.set_language(request.source_language)
        else:
            detection = pipeline.detect_language()
            chosen = pipeline.state.language or detection.language
            self.language_detected.emit(
                chosen, dict(detection.top).get(chosen, detection.probability)
            )
        pipeline.transcribe()
        pipeline.record_run()

    def _report(self, stage: str, fraction: float, message: str) -> None:
        if self._cancel.is_set():
            raise JobCancelledError
        try:
            step = PREPARE_STAGES.index(Stage(stage))
        except ValueError:
            return
        inside = (step + min(max(fraction, 0.0), 1.0)) / len(PREPARE_STAGES)
        overall = (self._number + inside) / max(len(self._requests), 1)
        self.progressed.emit(overall, stage)


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

    def __init__(self, pipeline: Pipeline, options: VideoOptions) -> None:
        super().__init__()
        self._pipeline = pipeline
        self._options = options

    @Slot()
    def run(self) -> None:
        try:
            output = render_clip_video(self._pipeline, self._options, self.progressed.emit)
        except Exception as error:
            log.exception("Exporting the video failed")
            self.failed.emit(str(error))
            return
        self.succeeded.emit(output)


class ExportAllVideosJob(QObject):
    progressed = Signal(float, str)
    clip_exported = Signal(object, object)
    clip_failed = Signal(object, str)
    succeeded = Signal(object)
    cancelled = Signal()

    def __init__(
        self,
        requests: list[JobRequest],
        settings: Settings,
        options: VideoOptions,
        shared: SharedModels,
    ) -> None:
        super().__init__()
        self._requests = requests
        self._settings = settings
        self._options = options
        self._shared = shared
        self._cancel = threading.Event()
        self._number = 0

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        outputs: list[Path] = []
        try:
            for number, request in enumerate(self._requests):
                self._number = number
                if self._cancel.is_set():
                    raise JobCancelledError
                self._report(0.0)
                try:
                    output = self._export(request)
                except JobCancelledError:
                    raise
                except Exception as error:
                    log.exception("Exporting the video of %s failed", request.media)
                    self.clip_failed.emit(request.media, str(error))
                    continue
                outputs.append(output)
                self.clip_exported.emit(request.media, output)
        except JobCancelledError:
            self._shared.release()
            self.cancelled.emit()
            return
        self._shared.release()
        self.succeeded.emit(outputs)

    def _export(self, request: JobRequest) -> Path:
        pipeline = create_pipeline(
            request.media, self._settings, self._stop_if_cancelled, shared=self._shared
        )
        pipeline.isolate_speech()
        if request.source_language:
            pipeline.set_language(request.source_language)
        else:
            pipeline.detect_language()
        pipeline.transcribe()
        pipeline.translate(request.clip_context)
        pipeline.build_cues()
        return render_clip_video(pipeline, self._options, self._report)

    def _stop_if_cancelled(self, *_: object) -> None:
        if self._cancel.is_set():
            raise JobCancelledError

    def _report(self, fraction: float) -> None:
        total = max(len(self._requests), 1)
        overall = (self._number + min(max(fraction, 0.0), 1.0)) / total
        media = self._requests[self._number].media
        self.progressed.emit(overall, f"Video {self._number + 1} of {total} · {media.name}")


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
