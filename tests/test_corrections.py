from __future__ import annotations

from pathlib import Path

import pytest

from app.config.corrections import CorrectionStore
from app.domain.corrections import Correction, apply_to_cues, apply_to_text, learn
from app.domain.models import Cue


@pytest.mark.parametrize(
    ("before", "after", "wrong", "right"),
    [
        (
            "and we gave him things like touch tape",
            "and we gave him things like tatti",
            "touch tape",
            "tatti",
        ),
        ("Medusa", "Jellyfish", "Medusa", "Jellyfish"),
        ("Wow, Gewo, Alter.", "Wow, Gevo, Alter.", "Gewo", "Gevo"),
        ("I am happy jibo art came", "I am happy GevoArt came", "jibo art", "GevoArt"),
    ],
)
def test_a_short_fix_is_learned(before: str, after: str, wrong: str, right: str) -> None:
    assert learn(before, after, "en") == Correction(wrong, right, "en")


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("GevoArt set, oh my god", "GevoArt said, oh my god"),
        ("this is the real one", "This is the real one!"),
        ("we gave him things", "we gave him many things"),
        ("we gave him things", "we gave him"),
        ("who is this guy", "where did he come from"),
        ("Gevo is cooking and he is fast", "Gevo cooked and he was fast"),
    ],
)
def test_short_words_rewrites_and_style_edits_are_not_learned(before: str, after: str) -> None:
    assert learn(before, after, "en") is None


def test_fixes_keep_the_capital_letter_and_whole_words() -> None:
    fixes = [Correction("touch tape", "tatti", "en"), Correction("Medusa", "jellyfish", "en")]
    text = "Touch  tape! A medusa, Medusa. touchtape stays"
    assert apply_to_text(text, fixes) == "Tatti! A jellyfish, Jellyfish. touchtape stays"


def test_fixes_only_apply_to_their_language() -> None:
    cue = Cue(
        index=1, start=0.0, end=1.0, original="Gebo dibuja", translation="Gebo draws", unit_id=0
    )
    fixes = [Correction("Gebo", "Gevo", "es")]
    assert apply_to_cues([cue], fixes, "es", "en") == 1
    assert (cue.original, cue.translation) == ("Gevo dibuja", "Gebo draws")


def test_the_store_keeps_one_fix_per_phrase(tmp_path: Path) -> None:
    store = CorrectionStore(tmp_path / "fixes.json")
    store.remember(Correction("touch tape", "testing", "en"))
    store.remember(Correction("Touch tape", "tatti", "en"))
    store.remember(Correction("Gebo", "Gevo", "es"))
    assert store.load() == [
        Correction("Touch tape", "tatti", "en"),
        Correction("Gebo", "Gevo", "es"),
    ]
    store.forget(Correction("Gebo", "Gevo", "es"))
    assert store.load() == [Correction("Touch tape", "tatti", "en")]


def test_an_unreadable_store_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "fixes.json"
    path.write_text("{not json", encoding="utf-8")
    assert CorrectionStore(path).load() == []
