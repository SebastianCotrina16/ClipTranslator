from __future__ import annotations

from app.domain.models import Flag, Unit
from app.domain.quality import HallucinationDetector, apply_corrections
from tests.builders import make_segment

DETECTOR = HallucinationDetector()


def test_known_hallucination_is_flagged() -> None:
    segment = make_segment("Subtítulos por la comunidad de Amara.org", avg_logprob=-0.2)
    assert Flag.KNOWN_PHRASE in DETECTOR.flags_for(segment)


def test_normal_speech_is_not_flagged() -> None:
    assert DETECTOR.flags_for(make_segment("What is that drawing?", avg_logprob=-0.2)) == []


def test_no_speech_and_low_confidence() -> None:
    silent = make_segment("hmm", no_speech_prob=0.9, avg_logprob=-1.5)
    unsure = make_segment("hmm", avg_logprob=-1.3)
    assert Flag.NO_SPEECH in DETECTOR.flags_for(silent)
    assert Flag.LOW_CONFIDENCE in DETECTOR.flags_for(unsure)


def test_repetition() -> None:
    assert DETECTOR.is_repetitive("no no no no no no")
    assert DETECTOR.is_repetitive("I love it. I love it. I love it. I love it.")
    assert not DETECTOR.is_repetitive("no no, that's not it")
    assert Flag.REPETITIVE in DETECTOR.flags_for(make_segment("x", compression_ratio=3.0))


def test_corrections_flag_word_changes_only() -> None:
    units = [
        Unit(0, 0, 1, "como hacen para dibujar también", []),
        Unit(1, 1, 2, "que es eso", []),
        Unit(2, 2, 3, "igual", []),
    ]
    apply_corrections(units, {"0": "¿Cómo hacen para dibujar tan bien?", "1": "¿Qué es eso?"})
    assert units[0].text == "¿Cómo hacen para dibujar tan bien?"
    assert units[0].asr_text == "como hacen para dibujar también"
    assert units[0].flags == [Flag.CORRECTED]
    assert units[1].text == "¿Qué es eso?"
    assert units[1].flags == []
    assert units[2].asr_text is None
