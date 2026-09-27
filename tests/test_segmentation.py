from __future__ import annotations

from app.domain.segmentation import SegmentationRules, UnitBuilder
from tests.builders import make_segment


def build(segments, pause: float = 0.4, max_duration: float = 7.0):
    return UnitBuilder(SegmentationRules(pause, max_duration)).build(segments)


def test_cuts_at_sentence_end() -> None:
    units = build([make_segment("What is that? Is that a cat?")])
    assert [unit.text for unit in units] == ["What is that?", "Is that a cat?"]
    assert [unit.id for unit in units] == [0, 1]


def test_cuts_at_long_pause() -> None:
    units = build([make_segment("okay okay let me guess", pauses={2: 0.6})])
    assert [unit.text for unit in units] == ["okay okay", "let me guess"]


def test_short_gap_keeps_unit_together() -> None:
    assert len(build([make_segment("okay okay let me guess", pauses={2: 0.1})])) == 1


def test_joins_segments_without_boundary() -> None:
    first = make_segment("this is the")
    second = make_segment("worst drawing ever", start=first.end + 0.06, segment_id=1)
    assert [unit.text for unit in build([first, second])] == ["this is the worst drawing ever"]


def test_long_unit_split_near_middle_preferring_commas() -> None:
    text = "one two three four five six seven, eight nine ten eleven twelve thirteen fourteen"
    units = build([make_segment(text, step=0.6)])
    assert len(units) == 2
    assert units[0].text.endswith("seven,")
    assert all(unit.end - unit.start <= 7.0 for unit in units)


def test_flagged_segment_gets_its_own_units() -> None:
    clean = make_segment("hello there")
    flagged = make_segment("thanks for watching", start=clean.end + 0.05, segment_id=1)
    flagged.flags = ["known_phrase"]
    units = build([clean, flagged])
    assert [unit.text for unit in units] == ["hello there", "thanks for watching"]
    assert units[0].flags == []
    assert units[1].flags == ["known_phrase"]


def test_unit_times_come_from_words() -> None:
    segment = make_segment("hi there", start=2.0)
    unit = build([segment])[0]
    assert (unit.start, unit.end) == (segment.words[0].start, segment.words[-1].end)
