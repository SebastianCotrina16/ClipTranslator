from __future__ import annotations

from app.domain.models import Flag
from app.domain.subtitles import CueBuilder, CueRules, fits_on_screen, wrap_lines
from tests.builders import make_unit

RULES = CueRules()


def build(units):
    return CueBuilder(RULES).build(units)


def test_short_text_is_one_line() -> None:
    assert wrap_lines("¿Es un gato?") == ["¿Es un gato?"]


def test_long_text_is_balanced_in_two_lines() -> None:
    lines = wrap_lines("Este es el peor dibujo que he visto en toda mi vida entera")
    assert len(lines) == 2
    assert all(len(line) <= 42 for line in lines)


def test_line_break_prefers_comma() -> None:
    assert wrap_lines("No, espera, es un perro, montando una patineta enorme")[0].endswith(",")


def test_three_lines_do_not_fit() -> None:
    assert not fits_on_screen("palabra " * 20, RULES)


def test_short_unit_is_one_cue() -> None:
    cues = build([make_unit("Is that a cat?", "¿Es un gato?", start=1.0)])
    assert len(cues) == 1
    assert (cues[0].original, cues[0].translation) == ("Is that a cat?", "¿Es un gato?")


def test_long_unit_is_split_with_shared_timing() -> None:
    text = (
        "this drawing is honestly the most incredible thing that anyone has ever made in the "
        "whole history of this game and I cannot believe it"
    )
    translation = (
        "este dibujo es honestamente lo más increíble que alguien haya hecho en toda "
        "la historia de este juego y no lo puedo creer"
    )
    cues = build([make_unit(text, translation, step=0.25)])
    assert len(cues) >= 2
    assert all(
        fits_on_screen(c.translation, RULES) and fits_on_screen(c.original, RULES) for c in cues
    )
    assert " ".join(c.translation for c in cues).split() == translation.split()
    assert " ".join(c.original for c in cues).split() == text.split()


def test_cues_never_overlap() -> None:
    cues = build(
        [
            make_unit("hello", "hola", start=0.0, unit_id=0),
            make_unit("there", "ahí", start=0.3, unit_id=1),
            make_unit("friend", "amigo", start=0.6, unit_id=2),
        ]
    )
    for first, second in zip(cues, cues[1:], strict=False):
        assert second.start >= first.end + RULES.gap - 1e-6
        assert first.end > first.start


def test_short_cue_is_extended_to_minimum_duration() -> None:
    cue = build([make_unit("wow", "guau", start=5.0)])[0]
    assert cue.end - cue.start >= RULES.min_duration - 1e-6


def test_lead_in_is_applied() -> None:
    assert build([make_unit("wow", "guau", start=5.0)])[0].start == 5.0 - RULES.lead_in


def test_fast_reading_is_flagged_when_there_is_no_room() -> None:
    long_translation = "esto es una traducción larguísima que no hay forma de leer tan rápido"
    cues = build(
        [
            make_unit("go", long_translation, start=0.0, unit_id=0),
            make_unit("next", "siguiente", start=0.5, unit_id=1),
        ]
    )
    assert Flag.FAST_READING in cues[0].flags


def test_missing_translation_is_flagged() -> None:
    cue = build([make_unit("hello there", None)])[0]
    assert Flag.UNTRANSLATED in cue.flags
    assert (cue.translation, cue.original) == ("", "hello there")


def test_cues_are_numbered_from_one() -> None:
    units = [make_unit("a b", "a b", start=i * 3.0, unit_id=i) for i in range(3)]
    assert [cue.index for cue in build(units)] == [1, 2, 3]


def test_reviewed_text_replaces_whisper_words() -> None:
    unit = make_unit("oigan como hacen para dibujar también", None, step=0.4)
    unit.asr_text = unit.text
    unit.text = "Oigan, ¿cómo hacen para dibujar tan bien?"
    unit.translation = "Hey guys, how do you draw so well?"
    assert " ".join(cue.original for cue in build([unit])) == unit.text


def test_reviewed_long_text_keeps_every_word_when_split() -> None:
    text = " ".join(f"palabra{i}" for i in range(40))
    unit = make_unit(text, None, step=0.25)
    unit.text = text.replace("palabra3 ", "palabra tres ")
    unit.translation = " ".join(f"word{i}" for i in range(40))
    cues = build([unit])
    assert len(cues) >= 2
    assert " ".join(cue.original for cue in cues).split() == unit.text.split()
