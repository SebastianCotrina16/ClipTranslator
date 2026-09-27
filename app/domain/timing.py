from __future__ import annotations

import re
from collections.abc import Iterable

from app.domain.models import Cue

_TIME_PATTERN = re.compile(r"^\s*(?:(\d+):)?(?:(\d+):)?(\d+(?:[.,]\d+)?)\s*$")
MIN_CUE_DURATION = 0.1


class InvalidTimingError(ValueError):
    pass


def parse_time_text(text: str) -> float:
    match = _TIME_PATTERN.match(text)
    if not match:
        raise InvalidTimingError(f"Not a valid time: {text!r}. Use m:ss.cc, for example 1:08.50.")
    first, second, seconds = match.groups()
    parts = [int(part) for part in (first, second) if part is not None]
    value = float(seconds.replace(",", "."))
    if len(parts) == 2:
        value += parts[0] * 3600 + parts[1] * 60
    elif len(parts) == 1:
        value += parts[0] * 60
    return round(value, 3)


def edit_time_text(seconds: float) -> str:
    minutes, rest = divmod(max(seconds, 0.0), 60)
    return f"{int(minutes)}:{rest:05.2f}"


def retime(cue: Cue, start: float, end: float) -> None:
    if start < 0:
        raise InvalidTimingError("A subtitle cannot start before 0:00.")
    if end - start < MIN_CUE_DURATION:
        raise InvalidTimingError("The end time must be after the start time.")
    cue.start, cue.end = round(start, 3), round(end, 3)


def shift(cues: Iterable[Cue], seconds: float) -> None:
    for cue in cues:
        duration = cue.end - cue.start
        start = max(cue.start + seconds, 0.0)
        cue.start, cue.end = round(start, 3), round(start + duration, 3)
