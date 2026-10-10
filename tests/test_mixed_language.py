from __future__ import annotations

import pytest

from app.application.pipeline import spoken_language, whisper_task
from app.domain.models import LanguageDetection
from app.domain.names import NameFixer, known_names


@pytest.mark.parametrize(
    ("language", "target", "task"),
    [
        ("hi", "en", "translate"),
        ("ur", "en", "translate"),
        ("hi", "es", "transcribe"),
        ("ru", "en", "transcribe"),
        ("en", "en", "transcribe"),
    ],
)
def test_whisper_writes_hindi_straight_in_english(language: str, target: str, task: str) -> None:
    assert whisper_task(language, target) == task


def detection(*top: tuple[str, float]) -> LanguageDetection:
    return LanguageDetection(top[0][0], top[0][1], [], list(top))


@pytest.mark.parametrize(
    ("top", "target", "spoken"),
    [
        ((("en", 0.589), ("hi", 0.27), ("tl", 0.027)), "en", "hi"),
        ((("en", 0.444), ("hi", 0.404), ("ur", 0.034)), "en", "hi"),
        ((("en", 0.5), ("ur", 0.15), ("hi", 0.1)), "en", "ur"),
        ((("en", 0.589), ("hi", 0.27), ("tl", 0.027)), "es", "en"),
        ((("en", 0.804), ("es", 0.156), ("cy", 0.007)), "en", "en"),
        ((("en", 0.9), ("hi", 0.05), ("ur", 0.03)), "en", "en"),
        ((("fr", 0.904), ("en", 0.083)), "en", "fr"),
        ((("hi", 0.69), ("en", 0.262)), "en", "hi"),
    ],
)
def test_hinglish_detected_as_english_is_treated_as_hindi(
    top: tuple[tuple[str, float], ...], target: str, spoken: str
) -> None:
    assert spoken_language(detection(*top), target) == spoken


def test_whisper_spellings_of_gevoart_are_fixed() -> None:
    fixer = NameFixer(known_names(""))
    assert fixer.fix("I'm really happy Jibo Art came to my stream.") == (
        "I'm really happy GevoArt came to my stream."
    )
