from __future__ import annotations

import pytest

from app.domain.coverage import (
    Region,
    check_windows,
    covered_fraction,
    fill_gaps,
    skipped_regions,
)
from app.domain.models import Flag
from app.domain.quality import HallucinationDetector
from app.domain.second_opinion import trusted_by
from app.infrastructure.whisper import shifted
from tests.builders import make_segment

LONG_SPEECH = Region(0.0, 24.0)


def test_coverage_counts_overlapping_words_once() -> None:
    first = make_segment("one two three", start=0.0, step=1.0)
    again = make_segment("one two three", start=0.0, step=1.0)
    assert covered_fraction(Region(0.0, 3.0), [first, again]) == pytest.approx(0.8)


def test_speech_skipped_by_whisper_is_detected() -> None:
    only_the_end = [make_segment("Dark Doran et T-Max.", start=21.4, step=0.4)]
    assert skipped_regions([LONG_SPEECH], only_the_end) == [LONG_SPEECH]


def test_normal_transcripts_are_left_alone() -> None:
    talking = [make_segment(" ".join(["mot"] * 60), start=0.5, step=0.38)]
    short_laugh = Region(30.0, 32.0)
    assert skipped_regions([LONG_SPEECH, short_laugh], talking) == []


def test_recovery_fills_gaps_and_completes_cut_lines() -> None:
    before = make_segment("hola", start=1.0, segment_id=0)
    skipped = make_segment("Dark Doran", start=21.4, segment_id=1)
    after = make_segment("adios", start=30.0, segment_id=2)
    retried = [
        make_segment("un zombie", start=1.0),
        make_segment("non mais par contre lui", start=7.0),
        make_segment("Dark Doran et T-Max", start=21.4),
    ]
    merged = fill_gaps([before, skipped, after], retried, [Region(5.0, 24.0)])
    assert [segment.text for segment in merged] == [
        "hola",
        "non mais par contre lui",
        "Dark Doran et T-Max",
        "adios",
    ]
    assert [segment.id for segment in merged] == [0, 1, 2, 3]


def test_nothing_changes_when_the_retry_finds_nothing() -> None:
    original = [make_segment("Dark Doran et T-Max", start=21.4)]
    assert fill_gaps(original, [], [LONG_SPEECH]) == original


def test_region_timestamps_are_moved_back_into_the_clip() -> None:
    moved = shifted(make_segment("un zombie", start=0.5), 10.0, 7)
    assert moved.id == 7
    assert moved.start == pytest.approx(10.5)
    assert moved.words[0].start == pytest.approx(10.5)


@pytest.mark.parametrize(
    "text",
    [
        "Sous-titres par Jérémy Diaz",
        "Sous-titres réalisés par la communauté d'Amara.org",
        "Sous-titrage ST' 501",
        "Sous-titrage Société Radio-Canada",
    ],
)
def test_hyphenated_made_up_phrases_are_flagged(text: str) -> None:
    flags = HallucinationDetector().flags_for(make_segment(text))
    assert Flag.KNOWN_PHRASE in flags


def test_close_short_regions_become_windows_of_limited_length() -> None:
    regions = [Region(0.0, 4.0), Region(4.5, 9.0), Region(9.5, 14.0), Region(14.2, 18.0)]
    assert check_windows(regions + [Region(30.0, 32.0)]) == [
        Region(0.0, 14.0),
        Region(14.2, 18.0),
        Region(30.0, 32.0),
    ]


def test_a_gap_inside_one_long_stretch_of_sound_is_found() -> None:
    talk = [make_segment("hola " * 30, start=start, step=0.5) for start in (0.0, 25.0)]
    one_long_region = [Region(0.0, 40.0)]
    assert skipped_regions(one_long_region, talk) == []
    short = [Region(start, start + 4.5) for start in range(0, 40, 5)]
    assert skipped_regions(check_windows(short), talk) == [Region(15.0, 29.5)]


def test_a_line_that_was_heard_is_not_replaced_by_a_different_guess() -> None:
    heard = make_segment("¿Quién es mi padre?", start=37.8, segment_id=0)
    retried = [
        make_segment("Creo que es un poquito más nivel", start=37.6),
        make_segment("En serio queremos sacar a Gevo", start=45.0),
    ]
    merged = fill_gaps([heard], retried, [Region(35.0, 50.0)])
    assert [segment.text for segment in merged] == [
        "¿Quién es mi padre?",
        "En serio queremos sacar a Gevo",
    ]


def test_a_made_up_line_is_replaced_by_real_speech() -> None:
    made_up = make_segment("Sous-titres par Jérémy Diaz", start=1.0, step=0.8)
    detector = HallucinationDetector()
    trusted = trusted_by(detector)
    [line] = fill_gaps(
        [made_up], [make_segment("Ah merde un zombie", start=1.2)], [LONG_SPEECH], trusted
    )
    assert line.text == "Ah merde un zombie"


def test_lines_that_barely_touch_are_both_kept() -> None:
    heard = make_segment("¿Cómo que tu papá?", start=41.7, segment_id=0)
    background = make_segment("creo que subió el nivel", start=40.5, step=0.3)
    merged = fill_gaps([heard], [background], [Region(28.0, 43.0)])
    assert [segment.text for segment in merged] == ["creo que subió el nivel", "¿Cómo que tu papá?"]


def test_a_line_heard_twice_is_not_repeated() -> None:
    stretched = make_segment("eso no llegó", start=122.9, step=1.2)
    again = make_segment("Eso no llegó.", start=125.3, step=0.2)
    assert fill_gaps([stretched], [again], [Region(112.0, 127.0)]) == [stretched]
