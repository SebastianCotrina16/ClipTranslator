from __future__ import annotations

import pytest

from app.domain.coverage import Region, covered_fraction, replace_regions, skipped_regions
from app.domain.models import Flag
from app.domain.quality import HallucinationDetector
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


def test_retried_region_replaces_the_skipped_one_only() -> None:
    before = make_segment("hola", start=1.0, segment_id=0)
    skipped = make_segment("Dark Doran", start=21.4, segment_id=1)
    after = make_segment("adios", start=30.0, segment_id=2)
    retried = [
        make_segment("un zombie", start=1.0),
        make_segment("non mais par contre lui", start=7.0),
        make_segment("Dark Doran et T-Max", start=21.4),
    ]
    merged = replace_regions([before, skipped, after], retried, [Region(5.0, 24.0)])
    assert [segment.text for segment in merged] == [
        "hola",
        "non mais par contre lui",
        "Dark Doran et T-Max",
        "adios",
    ]
    assert [segment.id for segment in merged] == [0, 1, 2, 3]


def test_retry_is_ignored_when_it_finds_less() -> None:
    original = [make_segment("Dark Doran et T-Max", start=21.4)]
    assert replace_regions(original, [], [LONG_SPEECH]) == original


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
