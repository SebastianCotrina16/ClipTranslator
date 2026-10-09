from __future__ import annotations

import pytest

from app.application.pipeline import whisper_task
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


def test_whisper_spellings_of_gevoart_are_fixed() -> None:
    fixer = NameFixer(known_names(""))
    assert fixer.fix("I'm really happy Jibo Art came to my stream.") == (
        "I'm really happy GevoArt came to my stream."
    )
