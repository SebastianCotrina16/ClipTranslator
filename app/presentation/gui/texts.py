from __future__ import annotations

from PySide6.QtCore import QLocale

from app.application.pipeline import STAGE_LABELS, Stage
from app.domain.languages import TARGET_LANGUAGES
from app.domain.models import Flag

MEDIA_FILTER = "Video and audio (*.mp4 *.mkv *.mov *.webm *.avi *.mp3 *.wav *.m4a *.flac *.ogg)"

FLAG_LABELS = {
    Flag.EMPTY: "empty",
    Flag.NO_SPEECH: "no speech",
    Flag.LOW_CONFIDENCE: "low confidence",
    Flag.REPETITIVE: "repetitive",
    Flag.KNOWN_PHRASE: "typical made-up phrase",
    Flag.CORRECTED: "corrected",
    Flag.UNTRANSLATED: "not translated",
    Flag.FAST_READING: "fast reading",
    Flag.MODELS_DISAGREE: "models disagree: click Versions",
    Flag.SECOND_MODEL: "heard by a second model",
}


def stage_label(stage: str) -> str:
    try:
        return STAGE_LABELS[Stage(stage)]
    except ValueError:
        return stage


def flag_labels(flags: list[str]) -> str:
    return ", ".join(FLAG_LABELS.get(flag, flag) for flag in flags)


def language_name(code: str) -> str:
    if code in TARGET_LANGUAGES:
        return TARGET_LANGUAGES[code]
    name = QLocale(code).nativeLanguageName()
    return name[:1].upper() + name[1:] if name else code
