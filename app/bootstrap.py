from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.application.pipeline import (
    Pipeline,
    PipelineServices,
    ProgressCallback,
    cue_rules_from,
)
from app.config.settings import Settings
from app.config.store import data_dir, models_dir
from app.infrastructure.ffmpeg import FfmpegAudio
from app.infrastructure.gpu import detect_gpu
from app.infrastructure.llm.factory import create_language_model
from app.infrastructure.process import lower_current_process_priority
from app.infrastructure.separation.worker import IsolatedVocalSeparator
from app.infrastructure.subtitle_files import SubtitleFileWriter, safe_stem
from app.infrastructure.whisper import FasterWhisperTranscriber, SileroSpeechDetector


def whisper_models_dir() -> Path:
    return models_dir() / "whisper"


def build_services(settings: Settings) -> PipelineServices:
    threads = settings.performance.thread_limit()
    transcription = settings.transcription

    def create_transcriber() -> FasterWhisperTranscriber:
        return FasterWhisperTranscriber.with_hardware_defaults(
            whisper_models_dir(),
            model=transcription.model,
            device=transcription.device,
            compute_type=transcription.compute_type,
            beam_size=transcription.beam_size,
            vad=transcription.vad,
            hallucination_silence_threshold=transcription.hallucination_silence_threshold or None,
            cpu_threads=threads,
        )

    def create_separator() -> IsolatedVocalSeparator:
        return IsolatedVocalSeparator(
            settings.separation.model,
            models_dir(),
            low_impact=settings.performance.low_impact,
            threads=threads,
        )

    def environment() -> dict[str, Any]:
        gpu = detect_gpu()
        return {"gpu": asdict(gpu) if gpu else None}

    return PipelineServices(
        audio=FfmpegAudio(),
        speech_detector=SileroSpeechDetector(),
        subtitle_writer=SubtitleFileWriter(cue_rules_from(settings.subtitles)),
        create_transcriber=create_transcriber,
        create_language_model=lambda: create_language_model(settings.translation, threads),
        create_separator=create_separator,
        environment=environment,
    )


def create_pipeline(
    media: Path,
    settings: Settings,
    progress: ProgressCallback | None = None,
    force: set[str] | None = None,
) -> Pipeline:
    if settings.performance.low_impact:
        lower_current_process_priority()
    work_dir = settings.work_root(data_dir() / "work") / safe_stem(media.stem)
    return Pipeline(media, settings, build_services(settings), work_dir, progress, force)
