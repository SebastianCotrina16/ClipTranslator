from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.config.prompts import translation_prompt_for
from app.domain.audio_leveling import Leveling
from app.domain.subtitle_style import SubtitleStyle

ANTHROPIC_KEY_VARIABLE = "ANTHROPIC_API_KEY"
OPENAI_KEY_VARIABLE = "OPENAI_API_KEY"


@dataclass
class TranscriptionSettings:
    model: str = ""
    device: str = ""
    compute_type: str = ""
    beam_size: int = 5
    vad: bool = True
    hallucination_silence_threshold: float = 2.0
    initial_prompt: str = "Gartic Phone."
    names: str = ""


@dataclass
class SeparationSettings:
    enabled: bool = True
    model: str = "UVR-MDX-NET-Voc_FT"


@dataclass
class TranslationSettings:
    backend: str = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    anthropic_model: str = ""
    openai_model: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)
    system_prompt: str = ""
    target_language: str = "es"
    review_transcript: bool = True
    merge_review: bool = False

    def effective_system_prompt(self) -> str:
        return self.system_prompt.strip() or translation_prompt_for(self.target_language)

    def anthropic_key(self) -> str:
        return os.environ.get(ANTHROPIC_KEY_VARIABLE) or self.anthropic_api_key

    def openai_key(self) -> str:
        return os.environ.get(OPENAI_KEY_VARIABLE) or self.openai_api_key


@dataclass
class SubtitleSettings:
    max_line_chars: int = 42
    max_lines: int = 2
    min_duration: float = 1.0
    max_duration: float = 7.0
    max_cps: float = 20.0
    gap: float = 0.08
    lead_in: float = 0.1
    unit_pause: float = 0.4


@dataclass
class VideoSettings:
    text_color: str = SubtitleStyle.text_color
    background: str = SubtitleStyle.background.value
    box_opacity: int = SubtitleStyle.box_opacity
    font_size: int = SubtitleStyle.font_size
    position: str = SubtitleStyle.position.value
    burn_subtitles: bool = True
    remove_music: bool = False
    level_audio: bool = False
    loudness_target: int = Leveling.target
    tame_loud_moments: str = Leveling.tame.value

    def style(self) -> SubtitleStyle:
        return SubtitleStyle.from_values(
            self.text_color, self.background, self.box_opacity, self.font_size, self.position
        )

    def leveling(self) -> Leveling:
        return Leveling.from_values(self.loudness_target, self.tame_loud_moments)

    def remember_leveling(self, leveling: Leveling) -> None:
        self.loudness_target = leveling.target
        self.tame_loud_moments = leveling.tame.value

    def remember(self, style: SubtitleStyle) -> None:
        self.text_color = style.text_color
        self.background = style.background.value
        self.box_opacity = style.box_opacity
        self.font_size = style.font_size
        self.position = style.position.value


@dataclass
class PerformanceSettings:
    low_impact: bool = True
    cpu_threads: int = 0

    def threads(self) -> int:
        if self.cpu_threads > 0:
            return self.cpu_threads
        cores = os.cpu_count() or 4
        return max(2, cores // 2) if self.low_impact else cores

    def thread_limit(self) -> int:
        return self.threads() if self.low_impact or self.cpu_threads else 0


@dataclass
class Settings:
    transcription: TranscriptionSettings = field(default_factory=TranscriptionSettings)
    separation: SeparationSettings = field(default_factory=SeparationSettings)
    translation: TranslationSettings = field(default_factory=TranslationSettings)
    subtitles: SubtitleSettings = field(default_factory=SubtitleSettings)
    performance: PerformanceSettings = field(default_factory=PerformanceSettings)
    video: VideoSettings = field(default_factory=VideoSettings)
    work_dir: str = ""
    check_for_updates: bool = True

    def work_root(self, default: Path) -> Path:
        return Path(self.work_dir) if self.work_dir else default


SECTION_NAMES = (
    "transcription",
    "separation",
    "translation",
    "subtitles",
    "performance",
    "video",
)
SECRET_FIELDS = {"anthropic_api_key", "openai_api_key"}


def redacted(settings: Settings) -> dict[str, Any]:
    data = asdict(settings)
    for secret in SECRET_FIELDS:
        data["translation"].pop(secret, None)
    data["translation"].pop("system_prompt", None)
    return data
