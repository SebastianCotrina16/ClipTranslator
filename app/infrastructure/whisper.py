from __future__ import annotations

import gc
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.application.ports import FractionCallback
from app.domain.models import LanguageGuess, Segment, Word
from app.infrastructure.gpu import expose_cuda_libraries, whisper_defaults

TEMPERATURE_FALLBACK = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


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
        return asdict(self.options)

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
        o = self.options
        raw_segments, info = self._loaded_model().transcribe(
            audio,
            language=language,
            beam_size=o.beam_size,
            temperature=list(TEMPERATURE_FALLBACK),
            condition_on_previous_text=False,
            word_timestamps=True,
            vad_filter=o.vad,
            hallucination_silence_threshold=o.hallucination_silence_threshold,
            initial_prompt=initial_prompt or None,
        )
        total = max(info.duration, 1e-6)
        segments: list[Segment] = []
        for raw in raw_segments:
            segments.append(_to_segment(len(segments), raw))
            if progress:
                progress(min(raw.end / total, 1.0))
        return segments

    def unload(self) -> None:
        self._model = None
        gc.collect()

    def _loaded_model(self) -> Any:
        if self._model is None:
            if self.options.device == "cuda":
                expose_cuda_libraries()
            quiet_model_downloads()
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.options.model,
                device=self.options.device,
                compute_type=self.options.compute_type,
                download_root=str(self._models_dir),
                cpu_threads=self.options.cpu_threads,
            )
        return self._model


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


def download_whisper_model(model: str, models_dir: Path) -> None:
    quiet_model_downloads()
    from faster_whisper.utils import download_model

    download_model(model, cache_dir=str(models_dir))


def vad_model_path() -> Path | None:
    from faster_whisper.utils import get_assets_path

    path = Path(get_assets_path()) / "silero_vad_v6.onnx"
    return path if path.exists() else None
