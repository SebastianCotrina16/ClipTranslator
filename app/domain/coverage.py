from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.domain.models import Segment

MIN_CHECKED_REGION = 4.0
MIN_COVERAGE = 0.35
MAX_WINDOW_GAP = 1.0
MAX_WINDOW_LENGTH = 15.0
MIN_CHECKED_WINDOW = 1.5
MAX_SHARED_SPEECH = 0.3
MIN_SPOKEN_SECONDS = 0.1
WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class Region:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def holds(self, segment: Segment) -> bool:
        return self.start <= (segment.start + segment.end) / 2 <= self.end


def spoken_spans(segments: Iterable[Segment]) -> list[tuple[float, float]]:
    spans: list[tuple[float, float]] = []
    for segment in segments:
        if segment.words:
            spans.extend((word.start, word.end) for word in segment.words)
        else:
            spans.append((segment.start, segment.end))
    return spans


def covered_fraction(region: Region, segments: Iterable[Segment]) -> float:
    if region.duration <= 0:
        return 1.0
    clipped = sorted(
        (max(start, region.start), min(end, region.end))
        for start, end in spoken_spans(segments)
        if end > region.start and start < region.end
    )
    covered = 0.0
    reach = region.start
    for start, end in clipped:
        if end <= reach:
            continue
        covered += end - max(start, reach)
        reach = end
    return covered / region.duration


def check_windows(
    regions: Iterable[Region],
    max_gap: float = MAX_WINDOW_GAP,
    max_length: float = MAX_WINDOW_LENGTH,
) -> list[Region]:
    windows: list[Region] = []
    for region in sorted(regions, key=lambda region: region.start):
        last = windows[-1] if windows else None
        if (
            last is not None
            and region.start - last.end <= max_gap
            and region.end - last.start <= max_length
        ):
            windows[-1] = Region(last.start, max(last.end, region.end))
        else:
            windows.append(region)
    return windows


def skipped_regions(
    regions: Iterable[Region],
    segments: list[Segment],
    min_region: float = MIN_CHECKED_REGION,
    min_coverage: float = MIN_COVERAGE,
) -> list[Region]:
    return [
        region
        for region in regions
        if region.duration >= min_region and covered_fraction(region, segments) < min_coverage
    ]


def spoken_words(segment: Segment) -> set[str]:
    return {word for word in WORD.findall(segment.text.casefold())}


def overlaps(first: Segment, second: Segment) -> bool:
    spans, other_spans = spoken_spans([first]), spoken_spans([second])
    shared = sum(
        max(0.0, min(end, other_end) - max(start, other_start))
        for start, end in spans
        for other_start, other_end in other_spans
    )
    shorter = min(sum(end - start for start, end in found) for found in (spans, other_spans))
    return shared > MAX_SHARED_SPEECH * max(shorter, MIN_SPOKEN_SECONDS)


def extends(new: Segment, old: list[Segment]) -> bool:
    heard = spoken_words(new)
    return all(spoken_words(segment) <= heard for segment in old) and len(heard) > len(
        set().union(*(spoken_words(segment) for segment in old))
    )


def fill_gaps(
    segments: list[Segment],
    retried: list[Segment],
    regions: list[Region],
    trusted: Callable[[Segment], bool] = lambda segment: True,
) -> list[Segment]:
    def inside(segment: Segment) -> bool:
        return any(region.holds(segment) for region in regions)

    kept = list(segments)
    for new in (segment for segment in retried if inside(segment) and trusted(segment)):
        clashing = [old for old in kept if overlaps(old, new)]
        heard = [old for old in clashing if trusted(old)]
        if heard and not extends(new, heard):
            continue
        gone = {id(old) for old in clashing}
        kept = [old for old in kept if id(old) not in gone] + [new]
    if kept == segments:
        return segments
    merged = sorted(kept, key=lambda segment: segment.start)
    for position, segment in enumerate(merged):
        segment.id = position
    return merged
