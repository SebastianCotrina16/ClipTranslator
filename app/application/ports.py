from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from app.domain.models import LanguageGuess, Segment

FractionCallback = Callable[[float], None]


class Transcriber(Protocol):
    @property
    def description(self) -> str: ...

    @property
    def cache_identity(self) -> dict[str, Any]: ...

    def detect_language(self, audio: np.ndarray) -> LanguageGuess: ...

    def transcribe(
        self,
        audio: np.ndarray,
        language: str,
        initial_prompt: str | None = None,
        progress: FractionCallback | None = None,
    ) -> list[Segment]: ...

    def unload(self) -> None: ...


class SpeechDetector(Protocol):
    def speech_only(self, audio: np.ndarray) -> np.ndarray: ...


class LanguageModelError(RuntimeError):
    pass


class LanguageModel(Protocol):
    @property
    def description(self) -> str: ...

    def prepare(self, progress: Callable[[float, str], None] | None = None) -> list[str]: ...

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]: ...

    def unload(self) -> None: ...


@dataclass(frozen=True)
class SeparationResult:
    vocals: Path
    device: str
    warning: str = ""


class VocalSeparator(Protocol):
    def separate(
        self, stereo_wav: Path, output: Path, progress: FractionCallback | None = None
    ) -> SeparationResult: ...


class AudioTools(Protocol):
    sample_rate: int
    separation_sample_rate: int

    def extract(self, media: Path, output: Path, sample_rate: int, channels: int) -> Path: ...

    def resample_for_speech(self, source: Path, output: Path) -> Path: ...

    def load_mono(self, path: Path) -> np.ndarray: ...

    def duration(self, path: Path) -> float: ...


class SubtitleWriter(Protocol):
    def write(
        self,
        cues: list[Any],
        media: Path,
        source_language: str,
        target_language: str,
        output_dir: Path | None,
        vtt: bool,
    ) -> list[Path]: ...
