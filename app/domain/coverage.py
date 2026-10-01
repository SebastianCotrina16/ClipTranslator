from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.domain.models import Segment

MIN_CHECKED_REGION = 4.0
MIN_COVERAGE = 0.35


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


def word_count(segments: Iterable[Segment]) -> int:
    return sum(len(segment.text.split()) for segment in segments)


def replace_regions(
    segments: list[Segment], retried: list[Segment], regions: list[Region]
) -> list[Segment]:
    def inside(segment: Segment) -> bool:
        return any(region.holds(segment) for region in regions)

    old = [segment for segment in segments if inside(segment)]
    new = [segment for segment in retried if inside(segment)]
    if word_count(new) <= word_count(old):
        return segments
    merged = sorted(
        [segment for segment in segments if not inside(segment)] + new,
        key=lambda segment: segment.start,
    )
    for position, segment in enumerate(merged):
        segment.id = position
    return merged
