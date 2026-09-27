from __future__ import annotations

import pytest

from app.application.updates import Release, newer_release, version_key
from app.domain.models import Cue
from app.domain.timing import (
    InvalidTimingError,
    edit_time_text,
    parse_time_text,
    retime,
    shift,
)


def cue(start: float, end: float) -> Cue:
    return Cue(1, start, end, "hi", "hola", 0)


def test_parse_time_text_accepts_common_formats() -> None:
    assert parse_time_text("1:08.50") == 68.5
    assert parse_time_text("68.5") == 68.5
    assert parse_time_text("0:05,25") == 5.25
    assert parse_time_text("1:00:02.5") == 3602.5
    assert parse_time_text(" 7 ") == 7.0


def test_parse_time_text_rejects_nonsense() -> None:
    for bad in ("", "abc", "1:2:3:4", "-5"):
        with pytest.raises(InvalidTimingError):
            parse_time_text(bad)


def test_edit_time_text_round_trips() -> None:
    assert edit_time_text(68.456) == "1:08.46"
    assert parse_time_text(edit_time_text(125.25)) == 125.25


def test_retime_validates_order() -> None:
    item = cue(1.0, 2.0)
    retime(item, 0.5, 3.0)
    assert (item.start, item.end) == (0.5, 3.0)
    with pytest.raises(InvalidTimingError):
        retime(item, 3.0, 2.0)
    with pytest.raises(InvalidTimingError):
        retime(item, -1.0, 2.0)


def test_shift_keeps_duration_and_never_goes_below_zero() -> None:
    items = [cue(1.0, 2.5), cue(3.0, 4.0)]
    shift(items, 0.25)
    assert [(c.start, c.end) for c in items] == [(1.25, 2.75), (3.25, 4.25)]
    shift(items, -2.0)
    assert [(c.start, c.end) for c in items] == [(0.0, 1.5), (1.25, 2.25)]


class FixedSource:
    def __init__(self, release: Release | None) -> None:
        self.release = release

    def latest(self) -> Release | None:
        return self.release


def test_version_key() -> None:
    assert version_key("v1.2.3") == (1, 2, 3)
    assert version_key("1.10.0") == (1, 10, 0)
    assert version_key("0.0.0-dev.4") == (0, 0, 0)
    assert version_key("latest") is None


def test_newer_release_only_when_greater() -> None:
    newer = Release("v1.2.0", "https://example/r")
    assert newer_release("1.1.0", FixedSource(newer)) == newer
    assert newer_release("1.2.0", FixedSource(newer)) is None
    assert newer_release("1.10.0", FixedSource(newer)) is None
    assert newer_release("1.1.0", FixedSource(None)) is None
    assert newer_release("unknown", FixedSource(newer)) is None
