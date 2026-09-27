from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.application.edits import EditStore
from app.application.language_detection import LanguageDetector
from app.application.ports import (
    AudioTools,
    LanguageModel,
    LanguageModelError,
    SpeechDetector,
    SubtitleWriter,
    Transcriber,
    VocalSeparator,
)
from app.application.stage_cache import StageCache
from app.application.translation import Request, Task, TranslationService
from app.config.prompts import MERGED_REVIEW_ADDENDUM, REVIEW_PROMPT
from app.config.settings import Settings, SubtitleSettings, redacted
from app.domain.models import (
    Cue,
    LanguageDetection,
    Unit,
    cues_from_records,
    language_detection_from_record,
    segments_from_records,
    to_records,
    units_from_records,
)
from app.domain.quality import HallucinationDetector, apply_corrections
from app.domain.segmentation import SegmentationRules, UnitBuilder
from app.domain.subtitles import CueBuilder, CueRules

log = logging.getLogger(__name__)

ProgressCallback = Callable[[str, float, str], None]


class PipelineError(RuntimeError):
    pass


class Stage(StrEnum):
    AUDIO = "audio"
    SEPARATION = "separation"
    LANGUAGE = "language"
    TRANSCRIPTION = "transcribe"
    UNITS = "units"
    REVIEW = "review"
    TRANSLATION = "translate"
    CUES = "cues"
    EXPORT = "export"


STAGE_LABELS = {
    Stage.AUDIO: "Extracting audio",
    Stage.SEPARATION: "Isolating voice",
    Stage.LANGUAGE: "Detecting language",
    Stage.TRANSCRIPTION: "Transcribing",
    Stage.UNITS: "Segmenting",
    Stage.REVIEW: "Reviewing transcript",
    Stage.TRANSLATION: "Translating",
    Stage.CUES: "Building subtitles",
    Stage.EXPORT: "Exporting",
}

CACHEABLE_STAGES = [stage.value for stage in Stage if stage is not Stage.EXPORT]


@dataclass
class PipelineServices:
    audio: AudioTools
    speech_detector: SpeechDetector
    subtitle_writer: SubtitleWriter
    create_transcriber: Callable[[], Transcriber]
    create_language_model: Callable[[], LanguageModel]
    create_separator: Callable[[], VocalSeparator]
    environment: Callable[[], dict[str, Any]] = dict


@dataclass
class StageRecord:
    stage: str
    seconds: float
    cached: bool
    detail: str = ""


@dataclass
class RunState:
    media: Path
    work_dir: Path
    keys: dict[str, str] = field(default_factory=dict)
    speech_audio: Path | None = None
    duration: float | None = None
    language: str | None = None
    language_detection: dict[str, Any] | None = None
    units: list[Unit] = field(default_factory=list)
    cues: list[Cue] = field(default_factory=list)
    records: list[StageRecord] = field(default_factory=list)
    backends: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    restored_edits: bool = False


def cue_rules_from(subtitles: SubtitleSettings) -> CueRules:
    return CueRules(
        max_line_chars=subtitles.max_line_chars,
        max_lines=subtitles.max_lines,
        min_duration=subtitles.min_duration,
        max_duration=subtitles.max_duration,
        max_cps=subtitles.max_cps,
        gap=subtitles.gap,
        lead_in=subtitles.lead_in,
    )


def _silent(stage: str, fraction: float, message: str) -> None:
    return None


class Pipeline:
    def __init__(
        self,
        media: Path,
        settings: Settings,
        services: PipelineServices,
        work_dir: Path,
        progress: ProgressCallback | None = None,
        force: set[str] | None = None,
    ) -> None:
        media = media.resolve()
        if not media.is_file():
            raise FileNotFoundError(media)
        self.settings = settings
        self.services = services
        self.progress = progress or _silent
        self.force = set(force or ())
        self.state = RunState(media=media, work_dir=work_dir)
        self.cache = StageCache(work_dir)
        self.edits = EditStore(work_dir)
        self._transcriber: Transcriber | None = None
        self._language_model: LanguageModel | None = None

    @property
    def cue_rules(self) -> CueRules:
        return cue_rules_from(self.settings.subtitles)

    @property
    def transcriber(self) -> Transcriber:
        if self._transcriber is None:
            self._transcriber = self.services.create_transcriber()
            self.state.backends["transcription"] = self._transcriber.description
        return self._transcriber

    @property
    def language_model(self) -> LanguageModel:
        if self._language_model is None:
            self._language_model = self.services.create_language_model()
        return self._language_model

    def run(
        self,
        language: str | None = None,
        clip_context: str = "",
        initial_prompt: str | None = None,
        output_dir: Path | None = None,
        vtt: bool = False,
    ) -> list[Path]:
        self.isolate_speech()
        if language:
            self.set_language(language)
        else:
            self.detect_language()
        self.transcribe(initial_prompt)
        self.translate(clip_context)
        self.build_cues()
        return self.export(output_dir, vtt)

    def extract_audio(self) -> Path:
        audio = self.services.audio
        media = self.state.media
        wav = self.state.work_dir / "audio_16k.wav"

        def compute() -> dict[str, Any]:
            audio.extract(media, wav, audio.sample_rate, 1)
            return {"wav": wav.name, "duration": audio.duration(wav)}

        stat = media.stat()
        params = {"media": str(media), "size": stat.st_size, "mtime": stat.st_mtime}
        data = self._run_stage(Stage.AUDIO, params, compute, require_file="wav")
        self.state.speech_audio = self.state.work_dir / data["wav"]
        self.state.duration = data.get("duration")
        return self.state.speech_audio

    def isolate_speech(self) -> Path:
        if self.state.speech_audio is None:
            self.extract_audio()
        separation = self.settings.separation
        if not separation.enabled:
            self.state.keys[Stage.SEPARATION] = self.state.keys[Stage.AUDIO]
            self.state.backends["separation"] = "desactivada"
            return self._current_speech_audio()
        work = self.state.work_dir
        audio = self.services.audio
        vocals_16k = work / "vocals_16k.wav"

        def compute() -> dict[str, Any]:
            stereo = audio.extract(
                self.state.media, work / "audio_44k.wav", audio.separation_sample_rate, 2
            )
            result = self.services.create_separator().separate(
                stereo, work / "vocals_44k.wav", self._fraction_reporter(Stage.SEPARATION)
            )
            if result.warning:
                self._warn(result.warning)
            audio.resample_for_speech(result.vocals, vocals_16k)
            stereo.unlink(missing_ok=True)
            return {"wav": vocals_16k.name, "device": result.device}

        data = self._run_stage(
            Stage.SEPARATION,
            {"model": separation.model},
            compute,
            upstream=self.state.keys[Stage.AUDIO],
            require_file="wav",
        )
        self.state.backends["separation"] = f"{separation.model} ({data.get('device', '?')})"
        self.state.speech_audio = work / data["wav"]
        return self.state.speech_audio

    def detect_language(self) -> LanguageDetection:
        speech_audio = self._speech_audio()
        detector = LanguageDetector(
            self.transcriber, self.services.speech_detector, self.services.audio.sample_rate
        )

        def compute() -> dict[str, Any]:
            return asdict(detector.detect(self.services.audio.load_mono(speech_audio)))

        data = self._run_stage(
            Stage.LANGUAGE,
            {"model": self.transcriber.cache_identity.get("model", "")},
            compute,
            upstream=self.state.keys[Stage.SEPARATION],
        )
        detection = language_detection_from_record(data)
        self.state.language_detection = data
        if self.state.language is None:
            self.state.language = detection.language
        return detection

    def set_language(self, code: str) -> None:
        self.state.language = code

    def transcribe(self, initial_prompt: str | None = None) -> list[Unit]:
        speech_audio = self._speech_audio()
        language = self.state.language or self.detect_language().language
        prompt = (
            self.settings.transcription.initial_prompt if initial_prompt is None else initial_prompt
        )
        transcriber = self.transcriber

        def compute_segments() -> list[dict[str, Any]]:
            segments = transcriber.transcribe(
                self.services.audio.load_mono(speech_audio),
                language=language,
                initial_prompt=prompt,
                progress=self._fraction_reporter(Stage.TRANSCRIPTION),
            )
            return to_records(HallucinationDetector().flag(segments))

        raw_segments = self._run_stage(
            Stage.TRANSCRIPTION,
            {"engine": transcriber.cache_identity, "language": language, "prompt": prompt},
            compute_segments,
            upstream=self.state.keys[Stage.SEPARATION],
        )
        segments = segments_from_records(raw_segments)
        rules = SegmentationRules(
            pause=self.settings.subtitles.unit_pause,
            max_duration=self.settings.subtitles.max_duration,
        )

        def compute_units() -> list[dict[str, Any]]:
            return to_records(UnitBuilder(rules).build(segments))

        raw_units = self._run_stage(
            Stage.UNITS, asdict(rules), compute_units, upstream=self.state.keys[Stage.TRANSCRIPTION]
        )
        self.state.units = units_from_records(raw_units)
        return self.state.units

    def review(self, clip_context: str = "") -> list[Unit]:
        if Stage.UNITS not in self.state.keys:
            self.transcribe()
        units = self.state.units
        translation = self.settings.translation
        language = self.state.language or "und"
        units_key = self.state.keys[Stage.UNITS]
        if not translation.review_transcript or not units:
            self.state.keys[Stage.REVIEW] = units_key + "-skipped"
            return units
        if language != translation.target_language and translation.merge_review:
            self.state.keys[Stage.REVIEW] = units_key + "-merged"
            return units
        self._release_transcriber()
        model = self.language_model
        request = Request(Task.REVIEW, language, language, clip_context)

        def compute() -> dict[str, Any]:
            self._prepare_language_model(model, Stage.REVIEW)
            result, report = TranslationService(model).run(
                units, request, REVIEW_PROMPT, self._fraction_reporter(Stage.REVIEW)
            )
            return {"corrections": _string_keys(result), "report": asdict(report)}

        params = {
            "backend": model.description,
            "prompt": REVIEW_PROMPT,
            "context": clip_context,
            "language": language,
        }
        try:
            data = self._run_stage(Stage.REVIEW, params, compute, upstream=units_key)
        except LanguageModelError as error:
            self._warn(f"Could not review the transcript ({error}); using it as is.")
            self.state.keys[Stage.REVIEW] = units_key + "-failed"
            return units
        apply_corrections(units, data["corrections"])
        if data["report"]["untranslated"]:
            self.cache.invalidate(Stage.REVIEW)
        return units

    def translate(self, clip_context: str = "") -> list[Unit]:
        if Stage.REVIEW not in self.state.keys:
            self.review(clip_context)
        units = self.state.units
        language = self.state.language or "und"
        translation = self.settings.translation
        if language == translation.target_language:
            return self._keep_original_language(units)
        self._release_transcriber()
        model = self.language_model
        self.state.backends["translation"] = model.description
        merged = self.state.keys[Stage.REVIEW].endswith("-merged")
        task = Task.REVIEW_AND_TRANSLATE if merged else Task.TRANSLATE
        system_prompt = translation.effective_system_prompt()
        if merged:
            system_prompt += MERGED_REVIEW_ADDENDUM
        request = Request(task, language, translation.target_language, clip_context)

        def compute() -> dict[str, Any]:
            self._prepare_language_model(model, Stage.TRANSLATION)
            result, report = TranslationService(model).run(
                units, request, system_prompt, self._fraction_reporter(Stage.TRANSLATION)
            )
            if not result and units:
                detail = report.errors[-1] if report.errors else "invalid responses"
                raise LanguageModelError(f"Nothing could be translated: {detail}")
            return {
                "translations": _string_keys(result),
                "corrections": _string_keys(report.corrections),
                "report": asdict(report),
            }

        params = {
            "backend": model.description,
            "system_prompt": system_prompt,
            "task": task.value,
            "target": translation.target_language,
            "context": clip_context,
            "language": language,
        }
        try:
            data = self._run_stage(
                Stage.TRANSLATION, params, compute, upstream=self.state.keys[Stage.REVIEW]
            )
        finally:
            model.unload()
        apply_corrections(units, data.get("corrections", {}))
        for unit in units:
            unit.translation = data["translations"].get(str(unit.id))
        self.state.records[-1].detail = json.dumps(data["report"], ensure_ascii=False)
        if data["report"]["untranslated"]:
            self.cache.invalidate(Stage.TRANSLATION)
        return units

    def retranslate_cue(self, position: int, clip_context: str = "", neighbours: int = 4) -> str:
        cues = self.state.cues
        if not 0 <= position < len(cues):
            raise PipelineError("That subtitle does not exist.")
        target = cues[position]
        language = self.state.language or "und"
        translation = self.settings.translation
        model = self.services.create_language_model()
        try:
            for warning in model.prepare():
                self._warn(warning)
            low, high = max(position - neighbours, 0), min(position + neighbours + 1, len(cues))
            surrounding = [
                {"id": cue.index, "text": cue.original, "translation": cue.translation}
                for cue in cues[low:high]
                if cue is not target
            ]
            request = Request(Task.TRANSLATE, language, translation.target_language, clip_context)
            text = TranslationService(model).translate_one(
                {"id": target.index, "text": target.original},
                request,
                translation.effective_system_prompt(),
                surrounding,
            )
        finally:
            model.unload()
        if text is None:
            raise LanguageModelError("The model did not return a translation for that line.")
        target.translation = text
        self.save_edits()
        return text

    def build_cues(self) -> list[Cue]:
        if Stage.TRANSLATION not in self.state.keys:
            self.translate()
        units = self.state.units
        rules = self.cue_rules

        def compute() -> list[dict[str, Any]]:
            return to_records(CueBuilder(rules).build(units))

        raw = self._run_stage(
            Stage.CUES, asdict(rules), compute, upstream=self.state.keys[Stage.TRANSLATION]
        )
        self.state.cues = cues_from_records(raw)
        edited = self.edits.load(self.state.keys[Stage.CUES])
        if edited is not None and len(edited) == len(self.state.cues):
            self.state.cues = edited
            self.state.restored_edits = True
        return self.state.cues

    def save_edits(self) -> None:
        if self.state.cues and Stage.CUES in self.state.keys:
            self.edits.save(self.state.keys[Stage.CUES], self.state.cues)

    def discard_edits(self) -> list[Cue]:
        self.edits.discard()
        self.state.restored_edits = False
        self.state.keys.pop(Stage.CUES, None)
        return self.build_cues()

    def export(self, output_dir: Path | None = None, vtt: bool = False) -> list[Path]:
        if not self.state.cues:
            self.build_cues()
        self.progress(Stage.EXPORT, 0.0, STAGE_LABELS[Stage.EXPORT])
        files = self.services.subtitle_writer.write(
            self.state.cues,
            self.state.media,
            self.state.language or "und",
            self.settings.translation.target_language,
            output_dir,
            vtt,
        )
        self.progress(Stage.EXPORT, 1.0, STAGE_LABELS[Stage.EXPORT])
        self._append_run_log(files)
        return files

    def _keep_original_language(self, units: list[Unit]) -> list[Unit]:
        for unit in units:
            unit.translation = unit.text
        self.state.keys[Stage.TRANSLATION] = self.state.keys[Stage.REVIEW] + "-same-language"
        self.state.backends["translation"] = "not translated (same language)"
        if self._language_model is not None:
            self._language_model.unload()
        return units

    def _prepare_language_model(self, model: LanguageModel, stage: Stage) -> None:
        def report_download(fraction: float, status: str) -> None:
            self.progress(stage, fraction * 0.5, f"Downloading model: {status}")

        for warning in model.prepare(report_download):
            self._warn(warning)

    def _speech_audio(self) -> Path:
        if Stage.SEPARATION not in self.state.keys:
            self.isolate_speech()
        return self._current_speech_audio()

    def _current_speech_audio(self) -> Path:
        if self.state.speech_audio is None:
            raise PipelineError("No audio was extracted from the file.")
        return self.state.speech_audio

    def _release_transcriber(self) -> None:
        if self._transcriber is not None:
            self._transcriber.unload()

    def _fraction_reporter(self, stage: Stage) -> Callable[[float], None]:
        return lambda fraction: self.progress(stage, fraction, STAGE_LABELS[stage])

    def _warn(self, message: str) -> None:
        if message not in self.state.warnings:
            self.state.warnings.append(message)
            log.warning(message)

    def _run_stage(
        self,
        stage: Stage,
        params: dict[str, Any],
        compute: Callable[[], Any],
        upstream: str = "",
        require_file: str | None = None,
    ) -> Any:
        self.progress(stage, 0.0, STAGE_LABELS[stage])
        started = time.perf_counter()
        result = self.cache.get_or_compute(
            stage, params, compute, upstream=upstream, force=stage in self.force
        )
        if require_file and not (self.state.work_dir / result.data[require_file]).exists():
            result = self.cache.get_or_compute(stage, params, compute, upstream, force=True)
        elapsed = time.perf_counter() - started
        self.state.keys[stage] = result.key
        self.state.records.append(StageRecord(stage, round(elapsed, 2), result.from_cache))
        suffix = " (cached)" if result.from_cache else f" ({elapsed:.1f} s)"
        self.progress(stage, 1.0, STAGE_LABELS[stage] + suffix)
        return result.data

    def _append_run_log(self, files: list[Path]) -> None:
        entry = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "media": str(self.state.media),
            "environment": self.services.environment(),
            "language": self.state.language,
            "language_detection": self.state.language_detection,
            "backends": self.state.backends,
            "stages": [asdict(record) for record in self.state.records],
            "flags": _count_flags(self.state.cues),
            "warnings": self.state.warnings,
            "files": [str(path) for path in files],
            "settings": redacted(self.settings),
        }
        with (self.state.work_dir / "run.log").open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _string_keys(values: dict[int, str]) -> dict[str, str]:
    return {str(key): value for key, value in values.items()}


def _count_flags(cues: list[Cue]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for cue in cues:
        for flag in cue.flags:
            counts[flag] = counts.get(flag, 0) + 1
    return counts
