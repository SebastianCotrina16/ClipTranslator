from __future__ import annotations

import gc
import io
import logging
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from app.application.ports import FractionCallback
from app.domain.coverage import Region, replace_regions, skipped_regions
from app.domain.models import LanguageGuess, Segment, Word
from app.domain.quality import HallucinationDetector
from app.domain.second_opinion import doubtful_regions, settle, trusted_by
from app.infrastructure.gpu import expose_cuda_libraries, whisper_defaults

log = logging.getLogger(__name__)

TEMPERATURE_FALLBACK = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
ENGINE_REVISION = 5
SECOND_OPINION_DOWNLOAD_SHARE = 0.1
SAMPLE_RATE = 16_000
FIRST_PASS_SHARE = 0.8
SHORT_REGION_SILENCE_MS = 300
SHORT_REGION_MAX_SECONDS = 8.0
SHORT_REGION_PAD_MS = 200


def quiet_model_downloads() -> None:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")


@dataclass(frozen=True)
class WhisperOptions:
    model: str
    device: str
    compute_type: str
    beam_size: int = 5
    vad: bool = True
    hallucination_silence_threshold: float | None = 2.0
    cpu_threads: int = 0
    recover_skipped_speech: bool = True
    second_opinion_model: str = "large-v2"


class FasterWhisperTranscriber:
    def __init__(self, options: WhisperOptions, models_dir: Path) -> None:
        self.options = options
        self._models_dir = models_dir
        self._model: Any = None

    @classmethod
    def with_hardware_defaults(
        cls,
        models_dir: Path,
        model: str = "",
        device: str = "",
        compute_type: str = "",
        **options: Any,
    ) -> FasterWhisperTranscriber:
        defaults = whisper_defaults()
        chosen_device = device or defaults.device
        if not compute_type:
            compute_type = defaults.compute_type if chosen_device == defaults.device else "int8"
        return cls(
            WhisperOptions(
                model=model or defaults.model,
                device=chosen_device,
                compute_type=compute_type,
                **options,
            ),
            models_dir,
        )

    @property
    def description(self) -> str:
        o = self.options
        return f"faster-whisper {o.model} ({o.device}, {o.compute_type})"

    @property
    def cache_identity(self) -> dict[str, Any]:
        return asdict(self.options) | {"revision": ENGINE_REVISION}

    def detect_language(self, audio: np.ndarray) -> LanguageGuess:
        language, probability, all_probabilities = self._loaded_model().detect_language(audio=audio)
        return LanguageGuess(language, probability, list(all_probabilities))

    def transcribe(
        self,
        audio: np.ndarray,
        language: str,
        initial_prompt: str | None = None,
        progress: FractionCallback | None = None,
    ) -> list[Segment]:
        recover = self.options.vad and self.options.recover_skipped_speech
        first_share = FIRST_PASS_SHARE if recover else 1.0
        segments = self._pass(audio, language, initial_prompt, progress, 0.0, first_share)
        if recover:
            from faster_whisper.vad import VadOptions

            trusted = trusted_by(HallucinationDetector())
            long_regions = speech_regions(audio, VadOptions())
            skipped = skipped_regions(long_regions, [s for s in segments if trusted(s)])
            if skipped:
                retried = self._region_by_region(audio, language, initial_prompt, skipped)
                segments = replace_regions(segments, retried, skipped, trusted)
            segments = self._double_check(
                audio, language, segments, long_regions, skipped, progress
            )
        if progress:
            progress(1.0)
        return segments

    def _double_check(
        self,
        audio: np.ndarray,
        language: str,
        segments: list[Segment],
        long_regions: list[Region],
        skipped: list[Region],
        progress: FractionCallback | None,
    ) -> list[Segment]:
        second_name = self.options.second_opinion_model
        if not second_name or second_name == self.options.model:
            return segments
        detector = HallucinationDetector()
        doubtful = doubtful_regions(
            speech_regions(audio, short_region_options()), segments, skipped, detector
        )
        if not doubtful:
            return segments
        second = self._second_model(progress)
        if second is None:
            return segments
        heard: list[Segment] = []
        try:
            for span in long_regions:
                if not any(span.start < gap.end and span.end > gap.start for gap in doubtful):
                    continue
                piece = audio[int(span.start * SAMPLE_RATE) : int(span.end * SAMPLE_RATE)]
                for segment in self._pass(piece, language, None, model=second):
                    heard.append(shifted(segment, span.start, len(heard)))
        finally:
            del second
            gc.collect()
        return settle(segments, heard, doubtful, (self.options.model, second_name), detector)

    def _second_model(self, progress: FractionCallback | None) -> Any:
        name = self.options.second_opinion_model

        def report(fraction: float) -> None:
            if progress:
                progress(FIRST_PASS_SHARE + SECOND_OPINION_DOWNLOAD_SHARE * fraction)

        try:
            if not is_model_downloaded(name, self._models_dir):
                download_whisper_model(name, self._models_dir, report)
            self.unload()
            return self._create_model(name)
        except Exception:
            log.exception("The second opinion model %s is not available", name)
            return None

    def _region_by_region(
        self,
        audio: np.ndarray,
        language: str,
        initial_prompt: str | None,
        skipped: list[Region],
    ) -> list[Segment]:
        segments: list[Segment] = []
        for region in speech_regions(audio, short_region_options()):
            if not any(region.start < gap.end and region.end > gap.start for gap in skipped):
                continue
            piece = audio[int(region.start * SAMPLE_RATE) : int(region.end * SAMPLE_RATE)]
            for segment in self._pass(piece, language, initial_prompt, vad=False):
                segments.append(shifted(segment, region.start, len(segments)))
        return segments

    def _pass(
        self,
        audio: np.ndarray,
        language: str,
        initial_prompt: str | None,
        progress: FractionCallback | None = None,
        progress_from: float = 0.0,
        progress_to: float = 1.0,
        vad: bool | None = None,
        model: Any = None,
    ) -> list[Segment]:
        o = self.options
        raw_segments, info = (model or self._loaded_model()).transcribe(
            audio,
            language=language,
            beam_size=o.beam_size,
            temperature=list(TEMPERATURE_FALLBACK),
            condition_on_previous_text=False,
            word_timestamps=True,
            vad_filter=o.vad if vad is None else vad,
            hallucination_silence_threshold=o.hallucination_silence_threshold,
            initial_prompt=initial_prompt or None,
        )
        total = max(info.duration, 1e-6)
        segments: list[Segment] = []
        for raw in raw_segments:
            segments.append(_to_segment(len(segments), raw))
            if progress:
                done = min(raw.end / total, 1.0)
                progress(progress_from + (progress_to - progress_from) * done)
        return segments

    def unload(self) -> None:
        self._model = None
        gc.collect()

    def _loaded_model(self) -> Any:
        if self._model is None:
            self._model = self._create_model(self.options.model)
        return self._model

    def _create_model(self, name: str) -> Any:
        if self.options.device == "cuda":
            expose_cuda_libraries()
        quiet_model_downloads()
        from faster_whisper import WhisperModel

        return WhisperModel(
            name,
            device=self.options.device,
            compute_type=self.options.compute_type,
            download_root=str(self._models_dir),
            cpu_threads=self.options.cpu_threads,
        )


def short_region_options() -> Any:
    from faster_whisper.vad import VadOptions

    return VadOptions(
        min_silence_duration_ms=SHORT_REGION_SILENCE_MS,
        max_speech_duration_s=SHORT_REGION_MAX_SECONDS,
        speech_pad_ms=SHORT_REGION_PAD_MS,
    )


def speech_regions(audio: np.ndarray, options: Any) -> list[Region]:
    from faster_whisper.vad import get_speech_timestamps

    return [
        Region(stamp["start"] / SAMPLE_RATE, stamp["end"] / SAMPLE_RATE)
        for stamp in get_speech_timestamps(audio, options)
    ]


def shifted(segment: Segment, seconds: float, segment_id: int) -> Segment:
    words = [
        Word(word.start + seconds, word.end + seconds, word.text, word.probability)
        for word in segment.words
    ]
    return replace(
        segment,
        id=segment_id,
        start=segment.start + seconds,
        end=segment.end + seconds,
        words=words,
    )


def _to_segment(segment_id: int, raw: Any) -> Segment:
    words = [
        Word(start=w.start, end=w.end, text=w.word, probability=w.probability)
        for w in (raw.words or [])
    ]
    return Segment(
        id=segment_id,
        start=raw.start,
        end=raw.end,
        text=raw.text.strip(),
        words=words,
        avg_logprob=raw.avg_logprob,
        no_speech_prob=raw.no_speech_prob,
        compression_ratio=raw.compression_ratio,
    )


class SileroSpeechDetector:
    def __init__(self, min_silence_ms: int = 500) -> None:
        self._min_silence_ms = min_silence_ms

    def speech_only(self, audio: np.ndarray) -> np.ndarray:
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        stamps = get_speech_timestamps(
            audio, VadOptions(min_silence_duration_ms=self._min_silence_ms)
        )
        if not stamps:
            return audio
        return np.concatenate([audio[stamp["start"] : stamp["end"]] for stamp in stamps])


def is_model_downloaded(model: str, models_dir: Path) -> bool:
    quiet_model_downloads()
    from faster_whisper.utils import download_model

    try:
        download_model(model, local_files_only=True, cache_dir=str(models_dir))
    except Exception:
        return False
    return True


WHISPER_FILES = (
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
)
MAX_REPORTED_FRACTION = 0.99


def download_whisper_model(
    model: str, models_dir: Path, progress: FractionCallback | None = None
) -> None:
    quiet_model_downloads()
    if progress is None:
        from faster_whisper.utils import download_model

        download_model(model, cache_dir=str(models_dir))
        return
    from huggingface_hub import snapshot_download

    snapshot_download(
        _repository_for(model),
        cache_dir=str(models_dir),
        allow_patterns=list(WHISPER_FILES),
        tqdm_class=_reporting_progress_bar(progress),
    )
    progress(1.0)


def _repository_for(model: str) -> str:
    from faster_whisper.utils import _MODELS

    return _MODELS.get(model, model)


def _reporting_progress_bar(progress: FractionCallback) -> type:
    from tqdm.auto import tqdm

    class ReportingProgressBar(tqdm):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs.pop("name", None)
            kwargs["file"] = io.StringIO()
            super().__init__(*args, **kwargs)

        def update(self, n: float | None = 1) -> bool | None:
            shown = super().update(n)
            if self.unit == "B" and self.total:
                progress(min(self.n / self.total, MAX_REPORTED_FRACTION))
            return shown

    return ReportingProgressBar


def vad_model_path() -> Path | None:
    from faster_whisper.utils import get_assets_path

    path = Path(get_assets_path()) / "silero_vad_v6.onnx"
    return path if path.exists() else None
